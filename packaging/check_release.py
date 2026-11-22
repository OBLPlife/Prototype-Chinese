"""Exercise the actual single-file EXE on a disposable copy, without running the game."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import setup
from release_install import WARNING


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def add_archive(data, name):
    old = setup.OWN
    try:
        setup.OWN = name
        return setup.cement_edit(data, True)[0]
    finally:
        setup.OWN = old


def verify(exe, source, workspace, report):
    with ZipFile(exe) as z:
        manifest = json.loads(z.read('package/manifest.json'))
    completed = []
    def passed(message):
        completed.append(message)
        print('PASS', message, flush=True)
    with tempfile.TemporaryDirectory(prefix='PrototypeZh 成品验证 ', dir=workspace) as tmp:
        root = Path(tmp)
        game = root / '任意发行目录 Game'
        game.mkdir()
        packaged = game / exe.name
        try:
            os.link(exe, packaged)
        except OSError:
            shutil.copyfile(exe, packaged)
        def run(args, code=0, warning=False):
            child = subprocess.run([str(packaged), '/quiet', *args], cwd=root,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=480)
            log = packaged.with_suffix('.log').read_text('utf-8-sig').splitlines()
            assert child.returncode == code, (args, child.returncode, log)
            expected_lines = 2 if warning else 1
            assert len(log) == expected_lines and (WARNING in log) == warning, log
            return log[-1]
        assert '游戏目录' in run([], 1)
        passed('wrong directory returns an actionable error')
        archives = sorted({row['archive'] for row in manifest['resources']})
        for name in archives:
            shutil.copyfile(source / name, game / name)
        english, _ = setup.cement_edit((source / 'cementfiles.p3d').read_bytes(), False)
        cement = game / 'cementfiles.p3d'
        cement.write_bytes(english)
        engine_name = 'prototypeenginef.dll'
        original_engine = source / 'PrototypeModern.Backup/prototypeenginef.dll.original'
        if not original_engine.is_file():
            original_engine = source / engine_name
        shutil.copyfile(original_engine, game / engine_name)
        (game / 'prototypef.exe').write_bytes(b'inert unrelated executable marker - never run')
        saves = game / 'user-test.sav'
        saves.write_bytes(b'preserve the player save')
        rcf, dll, state = game / setup.OWN, game / setup.RUNTIME, game / 'PrototypeZh/state.json'
        def installed():
            assert digest(rcf) == manifest['archive_sha256']
            assert digest(dll) == manifest['runtime_support']['sha256']
            receipt = json.loads(state.read_bytes())
            assert receipt['version'] == manifest['version']
            assert len(setup.rcf_index(rcf)) == len(manifest['resources'])
            groups = dict(setup.cement_edit(cement.read_bytes(), False)[1])
            assert groups['default'].count(setup.OWN) == 1 and groups['default'][0] == setup.OWN
            return state.read_bytes()

        print('Full original resource fixture ready', flush=True)
        run([])
        first = installed()
        passed('original resource installation: unrelated executable bytes accepted, all resources and runtime byte-identical')
        assert '已安装' in run([]) and installed() == first
        passed('repeated installation retains the first receipt')

        shutil.copyfile(source / engine_name, game / engine_name)
        (game / 'PrototypeModern.owned').write_bytes(b'independent modern data')
        (game / 'TexturePack.rcf').write_bytes(setup.make_rcf({'unrelated/texture': b'unchanged HD file'}))
        cement.write_bytes(add_archive(cement.read_bytes(), 'TexturePack.rcf'))
        with_hd = add_archive(english, 'TexturePack.rcf')
        run(['/restore'])
        assert not any(p.exists() for p in (rcf, dll, state))
        assert cement.read_bytes() == with_hd
        assert (game / 'TexturePack.rcf').is_file() and (game / 'PrototypeModern.owned').is_file()
        passed('install localization first, then Modern and a separate HD registration, selective restore')
        assert '没有可还原' in run(['/restore'])

        # Same translated entries in a differently serialized game archive.
        scripts = game / 'scripts.rcf'
        rows = setup.rcf_index(scripts)
        entries = {row['name']: setup.rcf_read(scripts, row['name']) for row in reversed(rows)}
        entries['unrelated/provenance.txt'] = b'another source, same translated resources'
        scripts.write_bytes(setup.make_rcf(entries))
        run([])
        installed()
        run(['/restore'])
        assert cement.read_bytes() == with_hd
        passed('Modern/HD first, changed whole RCF and unrelated entry, full install without compatibility warning')

        affected = next(r['asset'] for r in manifest['resources'] if r['archive'] == 'scripts.rcf')
        key = next(k for k in entries if setup.name_hash(k) == setup.name_hash(affected))
        entries[key] = b'another edition\r\n' + entries[key]
        scripts.write_bytes(setup.make_rcf(entries))
        changed_scripts = digest(scripts)
        assert '取消' in run([], 2, True)
        assert not any(p.exists() for p in (rcf, dll, state)) and cement.read_bytes() == with_hd
        passed('changed target resource: single requested warning, refusal leaves game data untouched')
        run(['/accept-risk'], warning=True)
        installed()
        assert digest(scripts) == changed_scripts
        run(['/restore'])
        assert cement.read_bytes() == with_hd and digest(scripts) == changed_scripts
        passed('changed target resource: consent installs the complete reference archive and restores independently')

        entries[key] = setup.rcf_read(source / 'scripts.rcf', key)
        scripts.write_bytes(setup.make_rcf(entries))
        (game / engine_name).write_bytes(b'other source with unknown localization interface')
        assert '取消' in run([], 2, True)
        run(['/accept-risk'], warning=True)
        installed()
        run(['/restore'])
        assert (game / engine_name).read_bytes().startswith(b'other source')
        passed('changed engine interface warns but allows complete install, without modifying the engine')
        shutil.copyfile(original_engine, game / engine_name)

        cement.write_bytes(b'other edition resource registration format')
        run([], 2, True)
        assert cement.read_bytes() == b'other edition resource registration format'
        run(['/accept-risk'], warning=True)
        installed()
        run(['/restore'])
        assert cement.read_bytes() == b'other edition resource registration format'
        cement.unlink()
        run([], 2, True)
        assert not cement.exists()
        run(['/accept-risk'], warning=True)
        installed()
        run(['/restore'])
        assert not cement.exists()
        cement.write_bytes(with_hd)
        passed('unknown or missing registration in a recognizable game: consent installs, restore recovers exact previous bytes or absence')

        overlap = game / 'TexturePack.rcf'
        previous_hd = overlap.read_bytes()
        overlap.write_bytes(setup.make_rcf({affected: b'other override of credits'}))
        run([], 2, True)
        run(['/accept-risk'], warning=True)
        installed()
        run(['/restore'])
        assert cement.read_bytes() == with_hd
        overlap.write_bytes(previous_hd)
        passed('another registered archive overlapping a translated resource gives only the single warning')

        dll.write_bytes(b'pre-existing independent same-name DLL')
        rcf.write_bytes(setup.make_rcf({'other/path': b'foreign data'}))
        foreign = (rcf.read_bytes(), dll.read_bytes())
        old_registration = add_archive(add_archive(english, setup.OWN), 'TexturePack.rcf')
        cement.write_bytes(old_registration)
        run([], 2, True)
        assert (rcf.read_bytes(), dll.read_bytes()) == foreign and not state.exists()
        run(['/accept-risk'], warning=True)
        installed()
        run(['/restore'])
        assert (rcf.read_bytes(), dll.read_bytes()) == foreign and cement.read_bytes() == old_registration
        assert not state.exists()
        passed('foreign archive and DLL: cancel preserves both, consent backs up both and restores their exact bytes and priority')
        old = {'version': 'earlier-localization', 'archive_sha256': digest(rcf),
               'runtime_support': {'sha256': digest(dll)}}
        old_state = json.dumps(old).encode('utf-8')
        state.write_bytes(old_state)
        run([])
        installed()
        run(['/restore'])
        assert (rcf.read_bytes(), dll.read_bytes()) == foreign and state.read_bytes() == old_state
        run(['/restore'])
        assert state.read_bytes() == old_state and cement.read_bytes() == old_registration
        passed('upgrade from an owned previous version restores its files and receipt, repeated restore is idempotent')
        state.unlink()
        dll.unlink()
        rcf.unlink()
        cement.write_bytes(with_hd)
        run([])
        dll.write_bytes(b'later independent replacement')
        result = run(['/restore'])
        assert '保留' in result and dll.read_bytes() == b'later independent replacement'
        assert not state.exists() and not rcf.exists() and cement.read_bytes() == with_hd
        assert saves.read_bytes() == b'preserve the player save'
        assert not list(game.glob('.PrototypeZh-setup-*')) and not (game / 'PrototypeZh/setup.pending').exists()
        passed('restore retains a later foreign DLL, unrelated registrations and save bytes; no temporary transaction remains')
    result = dict(version=manifest['version'], exe_sha256=digest(exe), resources=len(manifest['resources']),
                  archive_sha256=manifest['archive_sha256'], runtime_sha256=manifest['runtime_support']['sha256'],
                  checks=completed, game_started=False, gui_operated=False)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('exe', 'read_only_game', 'test_workspace', 'report'):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    verify(a.exe.resolve(), a.read_only_game.resolve(), a.test_workspace.resolve(), a.report.resolve())
