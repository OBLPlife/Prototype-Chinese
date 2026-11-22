"""Disclose the bytes of a finished installer, without starting it or using a game installation."""
import collections
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from read_contents import BLOCK, asset_path, expand, file_digest, original_digest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
from resources import rcf_index

PE_FILE = 'installer/launcher.pe.bin'
BOOTSTRAP = 'installer/bootstrap.zip'
DIRECTORY_FILE = 'installer/original-zip-directory.bin'


def managed_zip(pe):
    """The C# build embeds exactly one length-prefixed resource in its CLR resource directory."""
    header = struct.unpack_from('<I', pe, 60)[0]
    if pe[:2] != b'MZ' or pe[header:header + 4] != b'PE\0\0':
        raise ValueError('Invalid installer PE')
    optional = header + 24
    sections = struct.unpack_from('<H', pe, header + 6)[0]
    table = optional + struct.unpack_from('<H', pe, header + 20)[0]
    magic = struct.unpack_from('<H', pe, optional)[0]
    directories = optional + {0x10b: 96, 0x20b: 112}[magic]

    def disk_offset(rva, length):
        for i in range(sections):
            _, address, size, raw = struct.unpack_from('<4I', pe, table + i * 40 + 8)
            if address <= rva and rva + length <= address + size:
                return raw + rva - address
        raise ValueError('Managed resource lies outside the installer PE')

    clr_rva, clr_size = struct.unpack_from('<II', pe, directories + 14 * 8)
    clr = disk_offset(clr_rva, clr_size)
    rva, size = struct.unpack_from('<II', pe, clr + 24)
    start = disk_offset(rva, size)
    length = struct.unpack_from('<I', pe, start)[0]
    if length + 4 != size or pe[start + 4:start + 8] != b'PK\x03\x04':
        raise ValueError('Expected exactly one embedded ZIP in the published installer')
    return start + 4, pe[start + 4:start + 4 + length]


def extract_zip(z, directory):
    files = []
    for entry in z.infolist():
        if entry.is_dir():
            continue
        name = asset_path(entry.filename)
        if name != entry.filename:
            raise ValueError('Unexpected ZIP path ' + entry.filename)
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with z.open(entry) as src, path.open('xb') as dst:
            shutil.copyfileobj(src, dst, BLOCK)
        files.append(path)
    return files


def make_resource_index(folder, manifest):
    archive = folder / 'package/PrototypeZh.rcf'
    expected = {r['asset']: r for r in manifest['resources']}
    if len(expected) != len(manifest['resources']):
        raise ValueError('Duplicate resource in embedded manifest')
    kinds = collections.Counter()
    with (folder / 'resource-index.jsonl').open('x', encoding='utf-8', newline='\n') as out:
        for row in rcf_index(archive):
            info = expected.pop(row['name'])
            item = dict(asset=row['name'], base_archive=info['archive'], kind=info['kind'],
                        offset=row['offset'], bytes=row['size'], sha256=info['sha256'])
            out.write(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n')
            kinds[info['kind']] += 1
    if expected:
        raise ValueError('Missing entries in the published RCF')
    return kinds


def check_public_zip(archive):
    with ZipFile(archive) as z:
        index = json.loads(z.read('file-index.json'))
        names = z.namelist()
        expected = {r['path'] for r in index['files']} | {'file-index.json'}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError('Public ZIP inventory mismatch')
        for row in index['files']:
            with z.open(row['path']) as src:
                if (z.getinfo(row['path']).file_size != row['bytes'] or
                        hashlib.file_digest(src, 'sha256').hexdigest() != row['sha256']):
                    raise ValueError('Public ZIP entry differs from the disclosure: ' + row['path'])
    original_digest(archive)
    return index


def create(exe, archive, folder):
    exe = exe.resolve()
    file_rows = []

    def record(path, origin):
        file_rows.append(dict(path=path.relative_to(folder).as_posix(), origin=origin,
                              bytes=path.stat().st_size, sha256=file_digest(path)))

    with ZipFile(exe) as packaged:
        stub_size = min(entry.header_offset for entry in packaged.infolist())
        member_bytes = packaged.start_dir - stub_size
        (folder / 'installer').mkdir(parents=True)
        with exe.open('rb') as raw:
            stub = raw.read(stub_size)
            (folder / PE_FILE).write_bytes(stub)
            # The public ZIP inherits the compressed game payload byte for byte.
            with archive.open('xb') as out:
                shutil.copyfileobj(raw, out, BLOCK)
            raw.seek(packaged.start_dir)
            (folder / DIRECTORY_FILE).write_bytes(raw.read())
        original_payload_sha = file_digest(archive)
        for path in extract_zip(packaged, folder):
            record(path, 'installer payload')
    record(folder / PE_FILE, 'installer PE')
    record(folder / DIRECTORY_FILE, 'original payload ZIP central directory and end records')
    boot_offset, data = managed_zip(stub)
    bootstrap = folder / BOOTSTRAP
    bootstrap.write_bytes(data)
    record(bootstrap, 'PE managed resource')
    with ZipFile(bootstrap) as z:
        helpers = extract_zip(z, folder / 'installer/bootstrap')
    for path in helpers:
        record(path, 'bootstrap ZIP member')
    manifest = json.loads((folder / 'package/manifest.json').read_bytes())
    hashes = {r['path']: r['sha256'] for r in file_rows}
    if (hashes['package/PrototypeZh.rcf'] != manifest['archive_sha256']
            or hashes['package/XInput1_3.dll'] != manifest['runtime_support']['sha256']):
        raise ValueError('Published localization does not match its embedded manifest')
    kinds = make_resource_index(folder, manifest)
    count = expand(folder)
    if count != len(manifest['resources']):
        raise ValueError('Incomplete local RCF expansion')
    print('Expanded and verified %d game resources' % count, flush=True)
    for name in ('read_contents.py', 'full-installer-contents.txt'):
        shutil.copyfile(HERE / name, folder / name)
    for name in ('resource-index.jsonl', 'read_contents.py', 'full-installer-contents.txt'):
        record(folder / name, 'disclosure companion')
    index = dict(version=manifest['version'], installer=exe.name, installer_bytes=exe.stat().st_size,
                 installer_sha256=file_digest(exe), pe_file=PE_FILE, pe_bytes=stub_size,
                 original_zip_bytes=exe.stat().st_size - stub_size, original_zip_sha256=original_payload_sha,
                 original_zip_member_bytes=member_bytes, original_zip_directory_file=DIRECTORY_FILE,
                 managed_resource=BOOTSTRAP, managed_resource_pe_offset=boot_offset,
                 bootstrap_files=len(helpers), rcf_resource_count=count, rcf_resource_kinds=dict(kinds),
                 files=file_rows)
    index_file = folder / 'file-index.json'
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Appending replaces only the old central directory, retained above for
    # independent verification of every original EXE byte without a second RCF.
    with ZipFile(archive, 'a', ZIP_DEFLATED) as z:
        existing = set(z.namelist())
        for name in [r['path'] for r in file_rows] + [index_file.name]:
            if name not in existing:
                method = ZIP_STORED if name.endswith('.zip') else ZIP_DEFLATED
                z.write(folder / name, name, compress_type=method)
    check_public_zip(archive)


def export_contents(exe, archive):
    folder = archive.parent / 'installer-contents'
    legacy = archive.parent / 'EXE实际内容'
    if archive.is_file() and not folder.exists() and legacy.is_dir():
        folder = legacy
    if archive.exists() or folder.exists():
        # A repeated finish may reuse the disclosure only for this exact EXE.
        index = check_public_zip(archive)
        with ZipFile(archive) as z:
            if (index['installer_sha256'] != file_digest(exe) or
                    (folder / 'file-index.json').read_bytes() != z.read('file-index.json')):
                raise ValueError('Existing disclosure belongs to a different installer')
        for row in index['files']:
            if file_digest(folder / row['path']) != row['sha256']:
                raise ValueError('Existing disclosed file differs: ' + row['path'])
        if expand(folder) != index['rcf_resource_count']:
            raise ValueError('Local RCF expansion incomplete')
        return archive
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix='.contents-') as temp:
        stage = Path(temp)
        local = stage / folder.name
        output = stage / archive.name
        create(exe, output, local)
        local.rename(folder)
        try:
            output.rename(archive)
        except OSError:
            folder.rename(local)
            raise
    return archive
