"""Build and disclose the offline resource-delta edition of PrototypeZh."""
import argparse
import base64
from difflib import SequenceMatcher
from io import BytesIO
import json
import lzma
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path[:0] = [str(HERE), str(PROJECT / 'tools')]
from build_release import EXE, PYTHON_SHA, digest, make_installer, portable_metadata
import delta_resources as delta
from export_contents import managed_zip
from resources import rcf_read, sha, swf_tags, unpack_rz

CONTENTS = 'installer-contents'
DEPENDENCY = 'build-dependencies/python-3.13.12-embed-amd64.zip'
SOURCE_ZIP = 'Prototype-Chinese-v0.2.13-delta-source.zip'
LICENSES = ('NotoSansCJK-LICENSE.txt', 'NotoSans-LICENSE.txt', 'NotoSansMath-LICENSE.txt')
PAYLOAD = ('package/manifest.json', 'package/' + delta.FONTS, 'package/' + delta.UI,
           'package/XInput1_3.dll', *('licenses/' + name for name in LICENSES))


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def b64(data):
    return base64.b64encode(data).decode('ascii')


def copy_parts(old, new):
    """Copy unchanged byte runs from the player's SWF record and store only intervening literals."""
    parts = []
    pos = 0
    # Unique aligned prefix/suffix also keep long runs of low-entropy geometry out of literals.
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-1-suffix] == new[-1-suffix]:
        suffix += 1
    if prefix:
        parts.append([0, prefix])
        pos = prefix
    a, b = old[prefix:len(old)-suffix], new[prefix:len(new)-suffix]
    for i, j, size in SequenceMatcher(None, a, b).get_matching_blocks():
        if size < 8:
            continue
        if j + prefix > pos:
            parts.append(b64(new[pos:j+prefix]))
        parts.append([i+prefix, size])
        pos = j+prefix+size
    if pos < len(new)-suffix:
        parts.append(b64(new[pos:len(new)-suffix]))
    if suffix:
        parts.append([len(old)-suffix, suffix])
    return parts


def ui_recipe(old, target):
    _, before = swf_tags(old)
    _, after = swf_tags(target)
    hashes = [sha(raw) for _, _, raw in before]
    result = []
    matcher = SequenceMatcher(None, hashes, [sha(raw) for _, _, raw in after], autojunk=False)
    for op, i, j, a, b in matcher.get_opcodes():
        if op == 'equal':
            continue
        if op == 'replace' and j-i == b-a:
            for index, (left, right) in enumerate(zip(before[i:j], after[a:b]), i):
                if left[0] != right[0]:
                    raise ValueError('UI record type changed')
                result.append({'at': index, 'from': hashes[index], 'to': sha(right[2]),
                               'parts': copy_parts(left[2], right[2])})
        elif op == 'insert' and b-a == 1:
            raw = after[a][2]
            result.append(dict(at=i, left=hashes[max(0, i-3):i], right=hashes[i:i+3],
                               data=b64(raw), to=sha(raw)))
        else:
            raise ValueError(f'Unrecognized UI edit {op} {i}:{j} {a}:{b}')
    if delta.patch_ui(old, result, True) != target:
        raise ValueError('UI recipe failed reference round trip')
    return result


def font_records(old, target):
    _, before = swf_tags(old)
    _, after = swf_tags(target)
    changes = {}
    for (code, payload, a), (newcode, newpayload, b) in zip(before, after, strict=True):
        if a == b:
            continue
        face = delta.font_name(code, payload)
        if (code != 75 or newcode != 1005 or face != delta.font_name(newcode, newpayload)
                or face in changes):
            raise ValueError('Unexpected font movie change')
        changes[face] = b
    if delta.patch_font(old, changes) != target:
        raise ValueError('Font recipe failed reference round trip')
    return changes


def write_payload(path, files):
    if set(files) != set(PAYLOAD):
        raise ValueError('Unexpected payload file set')
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as archive:
        for name in PAYLOAD:
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0x20
            archive.writestr(info, files[name], compress_type=ZIP_STORED if name.endswith('.xz') else ZIP_DEFLATED,
                             compresslevel=6)


def prepare(game, package, output):
    manifest = portable_metadata(json.loads((package / 'manifest.json').read_bytes()))
    reference = package / 'PrototypeZh.rcf'
    if digest(reference) != manifest['archive_sha256'] or digest(package / 'XInput1_3.dll') != manifest['runtime_support']['sha256']:
        raise ValueError('Reference package differs from its manifest')
    ui, fonts = {}, []
    for number, row in enumerate(manifest['resources']):
        if row['kind'] not in ('font', 'save-ui-labels', 'initial-ui-labels'):
            continue
        name = row['asset']
        old = rcf_read(game / row['archive'], name)
        new = rcf_read(reference, name)
        if sha(old) != row['source_sha256'] or sha(new) != row['sha256']:
            raise ValueError('Reference asset differs: ' + name)
        if row['kind'] == 'font':
            changes = font_records(unpack_rz(old), unpack_rz(new))
            fonts.extend((face.encode('ascii'), number, tag) for face, tag in changes.items())
        else:
            ui[name] = ui_recipe(unpack_rz(old), unpack_rz(new))
    blob = bytearray()
    for face, number, tag in sorted(fonts):
        blob.extend(struct.pack('<IIB', number, len(tag), len(face)) + face + tag)
    font_data = lzma.compress(blob, preset=6)
    ui_data = encoded(ui)
    manifest['distribution'] = {'format': delta.FORMAT,
                                'files': {delta.FONTS: sha(font_data), delta.UI: sha(ui_data)}}
    files = {'package/manifest.json': encoded(manifest), 'package/' + delta.FONTS: font_data,
             'package/' + delta.UI: ui_data, 'package/XInput1_3.dll': (package / 'XInput1_3.dll').read_bytes()}
    files.update({'licenses/' + name: (package / name).read_bytes() for name in LICENSES})
    write_payload(output, files)
    print(f'{len(fonts)} font records, {len(ui)} UI recipes, {output.stat().st_size} payload bytes', flush=True)


def inspect(exe):
    data = exe.read_bytes()
    with ZipFile(BytesIO(data)) as outer:
        if tuple(outer.namelist()) != PAYLOAD or outer.testzip() is not None:
            raise ValueError('Unexpected installer payload')
        start = min(entry.header_offset for entry in outer.infolist())
        files = {name: outer.read(name) for name in PAYLOAD}
    pe, payload = data[:start], data[start:]
    offset, bootstrap = managed_zip(pe)
    files.update({'launcher.pe.bin': pe, 'payload.zip': payload, 'bootstrap.zip': bootstrap})
    with ZipFile(BytesIO(bootstrap)) as inner:
        if inner.testzip() is not None or len(set(inner.namelist())) != len(inner.infolist()):
            raise ValueError('Invalid embedded bootstrap')
        for name in inner.namelist():
            if Path(name).name != name:
                raise ValueError('Unexpected embedded bootstrap path')
            files['bootstrap/' + name] = inner.read(name)
    index = {'installer': {'name': exe.name, 'bytes': len(data), 'sha256': sha(data)},
             'payload_offset': start, 'bootstrap_offset_in_pe': offset,
             'contents': {k: {'bytes': len(v), 'sha256': sha(v)} for k, v in files.items()}}
    return index, files


def source_archive(output):
    """Distribute authored source and translation tables; local builds regenerate all game data."""
    suffixes = {'.as', '.cpp', '.cs', '.def', '.h', '.java', '.js', '.json',
                '.manifest', '.md', '.ps1', '.py', '.txt'}
    entries = {'README.md': HERE / 'SOURCE.md', '.gitignore': HERE / 'repository.gitignore',
               '.gitattributes': HERE / 'repository.gitattributes'}
    for folder in ('catalog', 'licenses', 'runtime', 'src', 'tools', 'packaging'):
        for file in (PROJECT / folder).rglob('*'):
            relative = file.relative_to(PROJECT)
            if not file.is_file() or '__pycache__' in relative.parts:
                continue
            if relative.as_posix() == 'catalog/bilingual-catalog.json':
                continue
            if file.suffix.lower() in suffixes or file in (HERE / 'repository.gitignore', HERE / 'repository.gitattributes'):
                entries['source/PrototypeZh/' + relative.as_posix()] = file
    for file in [*PROJECT.glob('PrototypeZh-*.ps1'), *(PROJECT / name for name in (
            'README.txt', 'KNOWN_ISSUES.txt', 'translations.sample.json'))]:
        entries['source/PrototypeZh/' + file.name] = file
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        target = Path(temp) / 'source.zip'
        with ZipFile(target, 'w') as archive:
            for name, file in sorted(entries.items()):
                if not name.isascii():
                    raise ValueError('Public source paths must use ASCII names: ' + name)
                data = file.read_bytes()
                data.decode('utf-8-sig')
                if b'\0' in data:
                    raise ValueError('Binary file in the source tree: ' + name)
                info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.create_system = 0
                info.external_attr = 0x20
                archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
        with ZipFile(target) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(entries):
                raise ValueError('Invalid source archive')
        target.replace(output)


def finish(output, embed=None, bilingual=None):
    inspect(output / EXE)
    if embed is not None and digest(embed) != PYTHON_SHA:
        raise ValueError('Unexpected embedded Python build dependency')
    if bilingual is not None and not bilingual.is_file():
        raise FileNotFoundError(bilingual)
    docs = HERE / 'README.md'
    source_archive(output / SOURCE_ZIP)
    shutil.copyfile(docs, output / docs.name)
    names = [EXE, SOURCE_ZIP, docs.name]
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(output / name) + '  ' + name + '\n' for name in names),
                                          encoding='utf-8')


def source_layout(root):
    # The earlier 0.2.13 source ZIP used localized directory names.
    if not (root / CONTENTS).exists() and (root / 'EXE内容').is_dir():
        return root / 'EXE内容', root / '构建依赖' / Path(DEPENDENCY).name
    return root / CONTENTS, root / DEPENDENCY


def exact(root, output):
    folder, _ = source_layout(root)
    index = json.loads((folder / 'file-index.json').read_bytes())
    raw = b''.join((folder / name).read_bytes() for name in ('launcher.pe.bin', 'payload.zip'))
    if len(raw) != index['installer']['bytes'] or sha(raw) != index['installer']['sha256']:
        raise ValueError('Disclosed installer components do not match the original executable')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(raw)
    print(index['installer']['sha256'], output, flush=True)


def recompile(root, output):
    root, output = root.resolve(), output.resolve()
    contents, embed = source_layout(root)
    if (output / EXE).exists():
        raise FileExistsError(output / EXE)
    with tempfile.TemporaryDirectory() as tmp:
        payload = Path(tmp) / 'payload.zip'
        write_payload(payload, {name: (contents / name).read_bytes() for name in PAYLOAD})
        make_installer(payload, embed, output)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='command', required=True)
    for name, args in [('prepare', ('game', 'package', 'output')), ('installer', ('payload', 'python_embed', 'output')),
                       ('source', ('output',)), ('finish', ('output',)), ('exact', ('root', 'output')),
                       ('recompile', ('root', 'output'))]:
        parser = sub.add_parser(name)
        for arg in args:
            parser.add_argument(arg, type=Path)
        if name == 'finish':
            for legacy_arg in ('python_embed', 'bilingual'):
                parser.add_argument(legacy_arg, type=Path, nargs='?')
    args = cli.parse_args()
    values = [v.resolve() for k, v in vars(args).items() if k != 'command' and v is not None]
    {'prepare': prepare, 'installer': make_installer, 'source': source_archive, 'finish': finish,
     'exact': exact, 'recompile': recompile}[args.command](*values)


if __name__ == '__main__':
    main()
