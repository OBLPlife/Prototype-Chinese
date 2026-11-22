"""Exercise the published EXE against disposable game resources without launching the game."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from time import monotonic
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'tools')]
from audio_dialogue import object_type, patch_audio_subtitles, read_audio_subtitles
from build_release import digest
from check_release import add_archive
from full_resources import patch_rows, tag_bytes
from inventory_all import holders
from release_install import WARNING
import setup
from resources import chunk, make_rcf, name_hash, rcf_index, rcf_read, repack_rz, sha, swf_tags, unpack_rz, walk_chunks


def add_metadata(movie):
    header, tags = swf_tags(movie)
    raw = [item[2] for item in tags]
    raw.insert(1, tag_bytes(77, b'<test>HD local metadata</test>\0'))
    result = bytearray(header + b''.join(raw))
    result[4:8] = struct.pack('<I', len(result))
    swf_tags(result)
    return bytes(result)


def audio_blocks(data, replacement=None):
    files = []
    def visit(block):
        output = bytearray()
        for kind, head, children, raw in walk_chunks(block):
            if kind == 0xfe000000 and object_type(head) == 'AudioFile':
                files.append(raw)
                if replacement is not None:
                    raw = replacement
            elif children:
                raw = chunk(kind, head[12:], visit(children))
            output.extend(raw)
        return bytes(output)
    output = visit(data)
    if len(files) != 1:
        raise ValueError('Fixture needs one audio payload')
    return files[0], output


def custom_overlay(game, rows):
    def local(row):
        return unpack_rz(rcf_read(game / row['archive'], row['asset']))
    def stored(row, raw):
        return repack_rz(rcf_read(game / row['archive'], row['asset']), raw)
    audio = [r for r in rows if r['kind'] == 'audio-subtitles' and len(r['changes']) == 1][:2]
    a, alternate = audio
    line = a['changes'][0]
    old = local(a)
    original_sound, _ = audio_blocks(old)
    other_sound, _ = audio_blocks(local(alternate))
    assert original_sound != other_sound
    _, new = audio_blocks(old, other_sound)
    new, _ = patch_audio_subtitles(new, {line['id']: (line['source'], 'Revised recording')})
    translated, _ = patch_audio_subtitles(new, {line['id']: ('Revised recording', line['zh'])})
    assert audio_blocks(translated)[0] == other_sound and read_audio_subtitles(translated)[0]['text'] == line['zh']
    changes = {a['asset']: stored(a, new)}
    expected = {a['asset']: stored(a, translated)}

    for r in [next(r for r in rows if r['asset'].lower().endswith('protohud.gfx')),
              next(r for r in rows if r['kind'] == 'font')]:
        changes[r['asset']] = stored(r, add_metadata(local(r)))
        expected[r['asset']] = stored(r, add_metadata(unpack_rz(rcf_read(game / setup.OWN, r['asset']))))
    credit = next(r for r in rows if r['kind'] == 'credits')
    extra = b'Local Studios\r\n  Local Artist\r\n'
    changes[credit['asset']] = stored(credit, extra + local(credit))
    expected[credit['asset']] = stored(credit, extra + unpack_rz(rcf_read(game / setup.OWN, credit['asset'])))

    row = next(r for r in rows if r['kind'] == 'text' and not r['appended_ids'] and len(r['changes']) == 1)
    english = local(row)
    line = holders(english)[0]
    unknown = {'hd_added_line': 'A line added by the HD mod'}
    modified = patch_rows(english, [dict(id=line['id'], text=line['text'], zh=line['text'] + ' Again.')], unknown)[0]
    changes[row['asset']] = stored(row, modified)
    translated = unpack_rz(rcf_read(game / setup.OWN, row['asset']))
    zh = holders(translated)[0]
    expected[row['asset']] = stored(row, patch_rows(translated, [dict(id=zh['id'], text=zh['text'], zh=zh['text'])], unknown)[0])
    # An opaque third-party record cannot be safely translated. Other assets should still install.
    unavailable = alternate['asset']
    changes[unavailable] = b'fixture: unrecognized local format'
    return make_rcf(changes), expected, unavailable, row['asset']


def verify(exe, source, workspace, report, rebuilt=None):
    with ZipFile(exe) as archive:
        manifest = json.loads(archive.read('package/manifest.json'))
        assert all(not name.lower().endswith('.rcf') for name in archive.namelist())
    rows = manifest['resources']
    passed = []
    started = monotonic()
    def success(label):
        passed.append(label)
        print('PASS', label, flush=True)
    def copy_fixture_file(name, src=None):
        shutil.copyfile(src if src is not None else source / name, game / name)
    with tempfile.TemporaryDirectory(prefix='游戏副本 ', dir=workspace) as temp:
        root = Path(temp)
        game = root / '任意游戏来源'
        game.mkdir()
        packaged = game / exe.name
        shutil.copyfile(exe, packaged)
        def run(*args, code=0, warn=False):
            p = subprocess.run([str(packaged), '/quiet', *args], cwd=root,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
            log = packaged.with_suffix('.log').read_text('utf-8-sig').splitlines()
            assert p.returncode == code and len(log) == 1 + int(warn) and (WARNING in log) == warn, (p.returncode, args, log)
            return log[-1]
        assert '游戏目录' in run(code=1)
        success('wrong directory rejected with placement instructions')
        archives = sorted({r['archive'] for r in rows})
        for name in archives:
            copy_fixture_file(name)
        english = setup.cement_edit((source / 'cementfiles.p3d').read_bytes(), False)[0]
        cement = game / 'cementfiles.p3d'
        cement.write_bytes(english)
        engine = 'prototypeenginef.dll'
        original = source / 'PrototypeModern.Backup/prototypeenginef.dll.original'
        copy_fixture_file(engine, original if original.is_file() else source / engine)
        engine_hash = digest(game / engine)
        player = game / 'prototypef.exe'
        player.write_bytes(b'unrelated executable test marker, never launched')
        save = game / 'local-player.sav'
        save.write_bytes(b'unchanged saved progress')
        rcf, dll, state = game / setup.OWN, game / setup.RUNTIME, game / 'PrototypeZh/state.json'
        def receipt():
            return json.loads(state.read_bytes())
        def assert_first():
            groups = dict(setup.cement_edit(cement.read_bytes(), False)[1])
            assert groups['default'][0] == setup.OWN and groups['default'].count(setup.OWN) == 1
        def absent(cement_bytes):
            assert not any(p.exists() for p in (rcf, dll, state)) and cement.read_bytes() == cement_bytes
        print('Copied the nine original archives; starting the published installer.', flush=True)
        assert '已安装' in run()
        assert_first()
        assert digest(rcf) == manifest['archive_sha256'] and digest(dll) == manifest['runtime_support']['sha256']
        by_key = {r['key']: r for r in rcf_index(rcf)}
        assert len(by_key) == len(rows)
        with rcf.open('rb') as stream:
            for row in rows:
                pos = by_key[name_hash(row['asset'])]
                stream.seek(pos['offset'])
                assert sha(stream.read(pos['size'])) == row['sha256'], row['asset']
        assert receipt()['delta_result'] == dict(generated=len(rows), omitted=[], partial=[])
        assert engine_hash == digest(game / engine)
        success(f'original engine and unrelated main EXE accepted; {len(rows)} per-resource hashes, full overlay and runtime match')
        stamp, record = rcf.stat().st_mtime_ns, state.read_bytes()
        assert '已安装' in run() and state.read_bytes() == record and rcf.stat().st_mtime_ns == stamp
        success('repeat install leaves the verified overlay and receipt untouched')
        hd_custom, expected, unavailable, partial = custom_overlay(game, rows)
        hd = game / 'TexturePack.rcf'
        hd.write_bytes(make_rcf({'unrelated/texture.dds': b'HD only'}))
        cement.write_bytes(add_archive(cement.read_bytes(), hd.name))
        registered_hd = add_archive(english, hd.name)
        copy_fixture_file(engine)
        modern_hash = digest(game / engine)
        assert '已还原' in run('/restore')
        absent(registered_hd)
        assert hd.is_file() and digest(game / engine) == modern_hash
        success('localization first, independent Modern engine and HD registration installed later survive restoration')

        # Repack one stock archive while keeping all translated resource bytes unchanged.
        scripts = game / 'scripts.rcf'
        script_entries = {r['name']: rcf_read(scripts, r['name']) for r in reversed(rcf_index(scripts))}
        script_entries['unrelated/release-note.txt'] = b'different local provenance'
        scripts.write_bytes(make_rcf(script_entries))
        if rebuilt is not None:
            shutil.copyfile(rebuilt, packaged)
        assert '已安装' in run()
        assert_first()
        assert digest(rcf) == manifest['archive_sha256'] and digest(dll) == manifest['runtime_support']['sha256']
        assert receipt()['delta_result']['generated'] == len(rows)
        success('Modern/HD first and repacked stock archive accepted without warning; same complete result'
                + (' from the independently recompiled EXE' if rebuilt is not None else ''))
        # A later HD release changes shared assets and re-registers itself above the localization.
        hd.write_bytes(hd_custom)
        cement.write_bytes(add_archive(cement.read_bytes(), hd.name))
        external_cement, previous = cement.read_bytes(), state.read_bytes()
        assert '取消' in run(code=2, warn=True)
        assert cement.read_bytes() == external_cement and state.read_bytes() == previous
        assert '2 项' in run('/accept-risk', warn=True)
        assert_first()
        for name, data in expected.items():
            assert rcf_read(rcf, name) == data, name
        success('HD updated after an existing install: decline preserves it, reapplying merges the new assets and restores localization priority')
        assert '已还原' in run('/restore')
        absent(registered_hd)
        shutil.copyfile(exe, packaged)
        scripts_hash = digest(scripts)
        hd.write_bytes(hd_custom)
        assert '取消' in run(code=2, warn=True)
        absent(registered_hd)
        assert hd.read_bytes() == hd_custom
        success('changed targeted resources give exactly the requested warning; decline makes no game changes')
        assert '2 项' in run('/accept-risk', warn=True)
        assert_first()
        rec = receipt()
        assert rec['delta_result'] == dict(generated=len(rows)-1, omitted=[unavailable], partial=[partial])
        assert digest(rcf) == rec['archive_sha256'] != manifest['archive_sha256']
        assert rec['reference_archive_sha256'] == manifest['archive_sha256']
        keys = {e['key'] for e in rcf_index(rcf)}
        assert len(keys) == len(rows)-1 and name_hash(unavailable) not in keys
        for name, data in expected.items():
            assert rcf_read(rcf, name) == data, name
        success('consent merges changed audio, UI, font, credits and text; opaque record and extra unrecognized English line retained and reported')
        stamp, record = rcf.stat().st_mtime_ns, state.read_bytes()
        assert '2 项' in run('/accept-risk', warn=True)
        assert state.read_bytes() == record and rcf.stat().st_mtime_ns == stamp
        success('custom installation fingerprint prevents unnecessary regeneration')
        assert '已还原' in run('/restore')
        absent(registered_hd)
        assert hd.read_bytes() == hd_custom and digest(scripts) == scripts_hash and digest(game / engine) == modern_hash
        assert save.read_bytes() == b'unchanged saved progress' and player.read_bytes() == b'unrelated executable test marker, never launched'
        success('custom restoration preserves locally changed audio/UI, registration, saves and engine')
        assert '没有可还原' in run('/restore')
        foreign_rcf = make_rcf({'other/file': b'pre-existing file of the same name'})
        foreign_dll = b'pre-existing independent same-name DLL'
        rcf.write_bytes(foreign_rcf)
        dll.write_bytes(foreign_dll)
        old_cement = add_archive(add_archive(english, setup.OWN), hd.name)
        cement.write_bytes(old_cement)
        assert '取消' in run(code=2, warn=True)
        assert rcf.read_bytes() == foreign_rcf and dll.read_bytes() == foreign_dll
        assert '2 项' in run('/accept-risk', warn=True)
        assert '已还原' in run('/restore')
        assert rcf.read_bytes() == foreign_rcf and dll.read_bytes() == foreign_dll
        assert cement.read_bytes() == old_cement and not state.exists() and hd.read_bytes() == hd_custom
        success('pre-existing same-name archive and DLL recovered byte-for-byte, including the original registration order')
        assert not list(game.glob('.PrototypeZh-setup-*')) and not (game / 'PrototypeZh/setup.pending').exists()
    result = dict(exe_sha256=digest(exe), baseline_rcf_sha256=manifest['archive_sha256'],
                  baseline_dll_sha256=manifest['runtime_support']['sha256'], individual_entries=len(rows),
                  rebuilt_sha256=digest(rebuilt) if rebuilt else None, tests=passed,
                  elapsed_seconds=round(monotonic()-started, 2), game_launched=False)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ('exe', 'source', 'workspace', 'report'):
        cli.add_argument(name, type=Path)
    cli.add_argument('--rebuilt', type=Path)
    args = cli.parse_args()
    verify(args.exe.resolve(), args.source.resolve(), args.workspace.resolve(), args.report.resolve(),
           args.rebuilt.resolve() if args.rebuilt else None)
