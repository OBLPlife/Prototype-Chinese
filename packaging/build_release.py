"""Build the Road Rash-style, offline Windows localization installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PYTHON_SHA = '76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0'
EXE = 'Prototype_ZH_CN_Setup.exe'
CORE = ('setup.py', 'resources.py', 'subtitle_support.py', 'subtitle_capture_support.py')
DELTA_TOOLS = ('full_resources.py', 'inventory_all.py', 'audio_dialogue.py', 'lua_display.py', 'audit_lua_context.py')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def portable_metadata(value):
    if isinstance(value, dict):
        return {k: (PureWindowsPath(v).name if k in ('source', 'source_file')
                    and isinstance(v, str) and PureWindowsPath(v).is_absolute()
                    else portable_metadata(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [portable_metadata(item) for item in value]
    return value


def make_payload(package, output):
    manifest = portable_metadata(json.loads((package / 'manifest.json').read_bytes()))
    for name, expected in [('PrototypeZh.rcf', manifest['archive_sha256']),
                           ('XInput1_3.dll', manifest['runtime_support']['sha256'])]:
        if digest(package / name) != expected:
            raise ValueError('Build input checksum mismatch: ' + name)
    with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('package/manifest.json', json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).encode())
        for name in ('PrototypeZh.rcf', 'XInput1_3.dll'):
            z.write(package / name, 'package/' + name)
        for name in ('NotoSansCJK-LICENSE.txt', 'NotoSans-LICENSE.txt', 'NotoSansMath-LICENSE.txt'):
            z.write(package / name, 'licenses/' + name)
    print('Payload bytes:', output.stat().st_size, flush=True)


def make_installer(payload, embed, output):
    if digest(embed) != PYTHON_SHA:
        raise ValueError('Unexpected Windows embeddable Python package')
    with ZipFile(payload) as z:
        data = json.loads(z.read('package/manifest.json'))
        delta = data.get('distribution', {}).get('format') == 'local-resource-delta-v1'
        if delta:
            if 'package/PrototypeZh.rcf' in z.namelist():
                raise ValueError('A local delta must not include the complete overlay')
            for name, expected in data['distribution']['files'].items():
                if hashlib.sha256(z.read('package/' + name)).hexdigest() != expected:
                    raise ValueError('Damaged release input: ' + name)
        elif z.getinfo('package/PrototypeZh.rcf').file_size <= 0:
            raise ValueError('Empty localization overlay')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temp:
        stage = Path(temp)
        bootstrap = stage / 'bootstrap.zip'
        with ZipFile(bootstrap, 'w', ZIP_DEFLATED) as z, ZipFile(embed) as python:
            # Standard library comes precompiled in python313.zip. Include the
            # official redistributable and its notices without a system install.
            for item in python.infolist():
                if not item.is_dir():
                    z.writestr(item.filename, python.read(item), compress_type=ZIP_STORED
                               if item.filename.endswith('.zip') else ZIP_DEFLATED)
            for name in CORE + (DELTA_TOOLS if delta else ()):
                z.write(PROJECT / 'tools' / name, name)
            z.write(HERE / 'release_install.py', 'release_install.py')
            z.write(HERE / 'registration.p3d', 'registration.p3d')
            if delta:
                z.write(HERE / 'delta_resources.py', 'delta_resources.py')
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        stub = stage / EXE
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64',
                        '/optimize+', '/utf8output', '/codepage:65001', *(['/define:DELTA_PACKAGE'] if delta else []),
                        '/out:' + str(stub), '/resource:' + str(bootstrap) + ',bootstrap.zip',
                        '/win32manifest:' + str(HERE / 'app.manifest'),
                        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                        '/reference:System.IO.Compression.dll', str(HERE / 'Installer.cs')], check=True)
        # A regular ZIP appended to the PE. The bundled zipfile reader supports
        # prepended executable data and can stream the RCF directly to disk.
        with stub.open('ab') as dst, payload.open('rb') as src:
            shutil.copyfileobj(src, dst, 4 << 20)
        with ZipFile(stub) as z:
            data = json.loads(z.read('package/manifest.json'))
            if z.testzip() is not None:
                raise ValueError('Damaged installer payload')
        stub.replace(output / EXE)
    print(data['version'], digest(output / EXE), flush=True)


def source_and_sums(output, version, contents_zip, bilingual=None):
    source_zip = output / ('Prototype-Chinese-v' + version + '-source.zip')
    with ZipFile(source_zip, 'w', ZIP_DEFLATED) as z:
        folders = ('catalog', 'runtime', 'src', 'tools', 'packaging')
        files = [file for folder in folders for file in (PROJECT / folder).rglob('*')]
        files.extend(PROJECT.glob('PrototypeZh-*.ps1'))
        files.extend(PROJECT / name for name in ('README.txt', 'KNOWN_ISSUES.txt', 'translations.sample.json'))
        for file in sorted(files):
            if bilingual is not None and file == PROJECT / 'catalog/bilingual-catalog.json':
                continue
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                z.write(file, 'PrototypeZh/' + file.relative_to(PROJECT).as_posix())
        if bilingual is not None:
            z.write(bilingual, 'PrototypeZh/catalog/bilingual-catalog.json')
        with ZipFile(output / EXE) as exe:
            for name in exe.namelist():
                if name.startswith('licenses/'):
                    z.writestr('PrototypeZh/' + name, exe.read(name))
        z.write(PROJECT / 'README.md', 'PrototypeZh/README.md')
        z.write(PROJECT / 'README_EN.md', 'PrototypeZh/README_EN.md')
    files = (output / EXE, source_zip, contents_zip)
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in files),
                                          encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('payload')
    p.add_argument('package', type=Path)
    p.add_argument('output', type=Path)
    p = commands.add_parser('installer')
    p.add_argument('payload', type=Path)
    p.add_argument('python_embed', type=Path)
    p.add_argument('output', type=Path)
    p = commands.add_parser('finish')
    p.add_argument('output', type=Path)
    p.add_argument('version')
    p.add_argument('--bilingual', type=Path)
    a = parser.parse_args()
    if a.command == 'payload':
        make_payload(a.package, a.output)
    elif a.command == 'installer':
        make_installer(a.payload, a.python_embed, a.output)
    else:
        from export_contents import export_contents
        contents = export_contents(a.output / EXE, a.output / ('Prototype-Chinese-v' + a.version + '-contents.zip'))
        source_and_sums(a.output, a.version, contents, a.bilingual)
