"""Read the disclosed installer contents. Uses only the Python standard library."""
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile


BLOCK = 4 * 1024 * 1024


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def asset_path(native):
    # A single leading backslash in RCF names denotes the game's asset root.
    name = native.removeprefix('\\').replace('\\', '/')
    path = PureWindowsPath(name)
    if not name or path.anchor or ':' in name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('无效的资源路径 ' + native)
    return name


def expand(root):
    archive = root / 'package/PrototypeZh.rcf'
    destination = root / 'game-resources'
    count = 0
    paths = set()
    with (root / 'resource-index.jsonl').open(encoding='utf-8') as index, archive.open('rb') as source:
        for line in index:
            row = json.loads(line)
            name = asset_path(row['asset'])
            if name.casefold() in paths:
                raise ValueError('重复的资源路径 ' + name)
            paths.add(name.casefold())
            target = destination / name
            source.seek(row['offset'])
            data = source.read(row['bytes'])
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('资源内容与索引不符 ' + name)
            if target.exists():
                if file_digest(target) != row['sha256']:
                    raise ValueError('本地已有不同内容的文件 ' + str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as out:
                    out.write(data)
            count += 1
    return count


def original_digest(contents):
    # The public ZIP keeps the EXE's original compressed member records as
    # its prefix. Its original central directory and original PE are retained.
    digest = hashlib.sha256()
    with ZipFile(contents) as z, contents.open('rb') as raw:
        index = json.loads(z.read('file-index.json'))
        digest.update(z.read(index['pe_file']))
        left = index['original_zip_member_bytes']
        while left:
            data = raw.read(min(BLOCK, left))
            if not data:
                raise ValueError('内容包中的原始 ZIP 数据不完整')
            digest.update(data)
            left -= len(data)
        digest.update(z.read(index['original_zip_directory_file']))
    actual = digest.hexdigest()
    if actual != index['installer_sha256']:
        raise ValueError('复原字节的 SHA-256 与原安装器不符')
    return actual


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-exe', type=Path, metavar='CONTENTS_ZIP',
                        help='从公开内容核对发行 EXE 的 SHA-256')
    options = parser.parse_args()
    if options.verify_exe:
        print(original_digest(options.verify_exe))
    else:
        print('已展开并核对 %d 项游戏资源。' % expand(Path(__file__).resolve().parent))
