"""Verify the public sources against the released installer or verify an older full disclosure."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_delta import CONTENTS, EXE, inspect
from build_release import CORE, DELTA_TOOLS, digest


def without_link_timestamps(data):
    """Normalize only the two PE timestamps written by the release's native x86 linker."""
    out = bytearray(data)
    pe = struct.unpack_from('<I', out, 60)[0]
    optional = pe + 24
    if out[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', out, optional)[0] != 0x10b:
        raise ValueError('Expected a native PE32 DLL')
    linked_at = bytes(out[pe+8:pe+12])
    out[pe+8:pe+12] = bytes(4)
    debug, size = struct.unpack_from('<II', out, optional+96+6*8)
    if not size or size % 28:
        raise ValueError('Invalid PE debug directory')
    section_table = optional + struct.unpack_from('<H', out, pe+20)[0]
    for i in range(struct.unpack_from('<H', out, pe+6)[0]):
        at = section_table + i*40
        address, raw_size, raw = struct.unpack_from('<III', out, at+12)
        if address <= debug and debug + size <= address + raw_size:
            table = raw + debug - address
            for row in range(table, table+size, 28):
                if out[row+4:row+8] == linked_at:
                    out[row+4:row+8] = bytes(4)
            return out
    raise ValueError('Missing debug directory')


def verify_bootstrap_sources(project, actual):
    for name in CORE + DELTA_TOOLS:
        assert (project / 'tools' / name).read_bytes() == actual['bootstrap/' + name], name
    for name in ('release_install.py', 'delta_resources.py'):
        assert (project / 'packaging' / name).read_bytes() == actual['bootstrap/' + name], name


def compile_native(project, output, original):
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned',
                    '-File', str(project / 'tools/build_runtime.ps1'), '-Output', str(output)], check=True)
    dll = output / 'XInput1_3.dll'
    assert without_link_timestamps(dll.read_bytes()) == without_link_timestamps(original)
    return dict(sha256=digest(dll), identical_except_link_timestamps=True)


def check(source_zip, exe, workspace, game=None, native=False):
    public, actual = inspect(exe)
    with tempfile.TemporaryDirectory(prefix='source-verification-', dir=workspace) as temp:
        root = Path(temp)
        with ZipFile(source_zip) as archive:
            if archive.testzip() is not None:
                raise ValueError('Source ZIP integrity check failed')
            archive.extractall(root)
        project = root / 'source/PrototypeZh'
        if project.is_dir():
            for file in root.rglob('*'):
                if file.is_file():
                    data = file.read_bytes()
                    data.decode('utf-8-sig')
                    assert b'\0' not in data and file.relative_to(root).as_posix().isascii(), file
            verify_bootstrap_sources(project, actual)
            result = dict(source_zip_sha256=digest(source_zip), release_exe_sha256=digest(exe),
                          format='source-only', bootstrap_sources_identical=True)
            if native:
                result['native_cpp'] = compile_native(project, root / 'native', actual['package/XInput1_3.dll'])
            (workspace / 'source-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print('PASS text-only source ZIP and embedded installer source files', flush=True)
            if game:
                subprocess.run([sys.executable, '-B', '-X', 'utf8', str(project / 'packaging/check_delta.py'),
                                str(exe), str(game), str(workspace), str(workspace / 'installed-exe-verification.json')],
                               cwd=root, check=True)
            return
        contents = root / CONTENTS
        assert public == json.loads((contents / 'file-index.json').read_bytes())
        for name, raw in actual.items():
            assert (contents / name).read_bytes() == raw, name
        project = root / 'PrototypeZh'
        pack = project / 'packaging'
        verify_bootstrap_sources(project, actual)
        assert (pack / 'registration.p3d').read_bytes() == actual['bootstrap/registration.p3d']
        command = [str(contents / 'bootstrap/python.exe'), '-I', '-B', '-X', 'utf8']
        def execute(args):
            subprocess.run([*command, *map(str, args)], cwd=root, check=True)
        exact = root / 'exact' / EXE
        rebuilt = root / 'recompiled' / EXE
        execute([pack / 'build_delta.py', 'exact', root, exact])
        execute([pack / 'build_delta.py', 'recompile', root, rebuilt.parent])
        assert digest(exact) == public['installer']['sha256']
        _, decoded = inspect(rebuilt)
        assert actual.keys() == decoded.keys()
        loose = [p for p in actual if p.startswith(('package/', 'licenses/', 'bootstrap/'))]
        assert all(actual[p] == decoded[p] for p in loose)
        cpp = None
        if native:
            cpp = compile_native(project, root / 'native', actual['package/XInput1_3.dll'])
        result = dict(source_zip_sha256=digest(source_zip), exact_exe_sha256=digest(exact),
                      recompiled_sha256=digest(rebuilt), individual_members=len(loose),
                      disclosed_items=len(actual), all_individual_members_identical=True,
                      raw_payload_identical=actual['payload.zip'] == decoded['payload.zip'], native_cpp=cpp)
        (workspace / 'source-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('PASS source ZIP, exact EXE and independently compiled components', flush=True)
        if game:
            execute([pack / 'check_delta.py', exe, game, workspace, workspace / 'installed-exe-verification.json',
                     '--rebuilt', rebuilt])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source_zip', 'exe', 'workspace'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--game', type=Path)
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args()
    check(args.source_zip.resolve(), args.exe.resolve(), args.workspace.resolve(),
          args.game.resolve() if args.game else None, args.native)
