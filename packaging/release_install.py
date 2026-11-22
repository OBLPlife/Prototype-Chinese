"""Install the packaged, complete localization and selectively restore prior files."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zipfile import ZipFile

if (Path(__file__).resolve().parent.parent / 'tools' / 'setup.py').is_file():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import setup

ARCHIVE = setup.OWN
RUNTIME = setup.RUNTIME
STATE = 'PrototypeZh/state.json'
CEMENT = 'cementfiles.p3d'
FILES = (ARCHIVE, RUNTIME, STATE, CEMENT)
BACKUP_FILE = {ARCHIVE: ARCHIVE, RUNTIME: RUNTIME, STATE: 'state.json', CEMENT: CEMENT}
WARNING = '所需资源存在变化，可能无法达到预期效果，是否继续安装？'
PREVIOUS = 'release_setup_backup'
STAMP = re.compile(r'BeforeSetup-\d{8}T\d{12}Z')


def file_hash(path):
    if not path.exists():
        return None
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_bytes(data):
    return json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def copy_verified(stream, target, expected):
    digest = hashlib.sha256()
    with target.open('xb') as out:
        while block := stream.read(4 << 20):
            digest.update(block)
            out.write(block)
        out.flush()
        os.fsync(out.fileno())
    if digest.hexdigest() != expected:
        raise ValueError('汉化文件校验失败，请重新取得安装包或备份。')


@contextmanager
def open_package(path):
    if path.is_dir():
        yield lambda name: (path / name).open('rb')
    else:
        with ZipFile(path) as z:
            yield lambda name: z.open('package/' + name)


def read_registration(game):
    if (game / CEMENT).is_file():
        return (game / CEMENT).read_bytes()
    if (game / 'art.rcf').is_file() and (game / 'scripts.rcf').is_file():
        return None
    raise ValueError('请把安装器放进《虐杀原形》的游戏目录，与 cementfiles.p3d 放在一起。')


def parse_registration(data):
    if data is None:
        return None
    try:
        return setup.cement_edit(data, True)
    except (ValueError, UnicodeError, IndexError, KeyError, OverflowError, setup.struct.error):
        return None


def read_state(game):
    try:
        obj = json.loads((game / STATE).read_bytes())
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, ValueError, UnicodeError):
        return {}


def backup_path(game, state):
    name = state.get(PREVIOUS)
    if isinstance(name, str) and STAMP.fullmatch(name):
        directory = game / 'PrototypeZh' / name
        if (directory / 'before.json').is_file():
            return directory
    return None


def keep_snapshot(game, stage, before):
    directory = stage / 'before'
    directory.mkdir()
    for name in FILES:
        if before[name] is not None:
            with (game / name).open('rb') as src:
                copy_verified(src, directory / BACKUP_FILE[name], before[name])
    (directory / 'before.json').write_bytes(json_bytes(before))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = game / 'PrototypeZh' / ('BeforeSetup-' + stamp)
    directory.rename(target)
    return target


def undo_pending(game):
    marker = game / 'PrototypeZh/setup.pending'
    if not marker.is_file():
        return
    directory = marker.read_text('ascii')
    if not re.fullmatch(r'\.PrototypeZh-setup-[a-z0-9_]+', directory):
        raise ValueError('安装恢复记录无法读取，请保留现场和备份。')
    stage = game / directory
    operations = json.loads((stage / 'plan.json').read_bytes())
    for index, op in reversed(list(enumerate(operations))):
        name, before, after = op
        if name not in FILES:
            raise ValueError('安装恢复记录包含未知文件。')
        if not (stage / ('attempt-' + str(index))).is_file():
            continue
        original, target = stage / ('old-' + str(index)), game / name
        if original.is_file():
            current = file_hash(target)
            if current is not None and current != after:
                raise ValueError('安装中断后文件又被更改，已保留恢复副本。' + name)
            original.replace(target)
        elif before is None and target.exists():
            if file_hash(target) != after:
                raise ValueError('安装中断后出现了其他文件，已保留恢复副本。' + name)
            target.unlink()
    marker.unlink()
    shutil.rmtree(stage)


def commit(game, stage, changes, before):
    # Sources are fully staged on the game volume. Record the original files by
    # rename; even an interrupted process can roll back on the next invocation.
    operations = [(name, before[name], after) for name, (_, after) in changes.items()
                  if before[name] != after]
    if not operations:
        return
    (stage / 'plan.json').write_bytes(json_bytes(operations))
    marker = game / 'PrototypeZh/setup.pending'
    with marker.open('x', encoding='ascii') as stream:
        stream.write(stage.name)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for index, (name, old, new) in enumerate(operations):
            target = game / name
            if file_hash(target) != old:
                raise ValueError('安装过程中目标文件又被更改，请关闭其他正在写入游戏目录的程序后重试。' + name)
            (stage / ('attempt-' + str(index))).touch(exist_ok=False)
            if old is not None:
                target.rename(stage / ('old-' + str(index)))
            if new is not None:
                changes[name][0].rename(target)
        marker.unlink()
    except BaseException:
        undo_pending(game)
        raise


@contextmanager
def staging(game):
    stage = Path(tempfile.mkdtemp(prefix='.PrototypeZh-setup-', dir=game))
    try:
        yield stage
    finally:
        # Keep all displaced bytes if automatic recovery itself was interrupted.
        marker = game / 'PrototypeZh/setup.pending'
        if not marker.exists() or marker.read_text('ascii') != stage.name:
            if stage.exists():
                shutil.rmtree(stage)


def small_file(stage, name, data):
    target = stage / name
    target.write_bytes(data)
    return target, hashlib.sha256(data).hexdigest()


def install(game, package, confirm, progress):
    undo_pending(game)
    original = read_registration(game)
    registration = parse_registration(original)
    if registration is None:
        template = Path(__file__).with_name('registration.p3d').read_bytes()
        registered, groups = setup.cement_edit(template, True)
    else:
        registered, groups = registration
    with open_package(package) as source:
        with source('manifest.json') as stream:
            manifest = json.load(stream)
        support = setup.runtime_spec(manifest)
        if not support:
            raise ValueError('安装包缺少汉化运行库清单。')
        progress('正在核对汉化涉及的资源…')
        state = read_state(game)
        before = {name: file_hash(game / name) for name in FILES}
        archive_hash = manifest['archive_sha256']
        runtime_hash = support['sha256']
        prior_runtime = state.get('runtime_support') or {}
        current_own = state.get('archive_sha256')
        current_dll = prior_runtime.get('sha256') if isinstance(prior_runtime, dict) else None
        external = ((before[ARCHIVE] is not None and before[ARCHIVE] != current_own)
                    or (before[RUNTIME] is not None and before[RUNTIME] != current_dll)
                    or (before[STATE] is not None and not state))
        engine = setup.engine_runtime_status(game, bool(support.get('font_buffers')),
                                             bool(support.get('font_lookup')),
                                             bool(support.get('font_kerning')),
                                             bool(support.get('subtitles')))
        changed = next(setup.resource_differences(game, manifest, groups), None) is not None
        if changed or external or registration is None or not engine['compatible']:
            if not confirm():
                return '已取消安装。', 2
        if (not external and before[ARCHIVE] == archive_hash and before[RUNTIME] == runtime_hash
                and state.get('version') == manifest['version'] and registered == original):
            return '当前版本已安装。', 0

        progress('正在解压并校验完整汉化…')
        with staging(game) as stage:
            changes = {}
            for name, expected in [(ARCHIVE, archive_hash), (RUNTIME, runtime_hash)]:
                if before[name] != expected:
                    with source(name) as stream:
                        copy_verified(stream, stage / name, expected)
                    changes[name] = (stage / name, expected)
            progress('正在保存备份并注册汉化…')
            (game / 'PrototypeZh').mkdir(exist_ok=True)
            baseline = backup_path(game, state)
            if baseline is None or external:
                baseline = keep_snapshot(game, stage, before)
            stamp = datetime.now(timezone.utc).isoformat()
            installed = dict(manifest, installed_utc=stamp, cement_backup=baseline.name + '/' + CEMENT,
                             cement_before_sha256=before[CEMENT], cement_after_sha256=setup.sha(registered))
            installed[PREVIOUS] = baseline.name
            changes[STATE] = small_file(stage, 'new-state.json', json_bytes(installed))
            changes[CEMENT] = small_file(stage, 'new-cement.p3d', registered)
            if read_registration(game) != original:
                raise ValueError('安装期间资源注册表被其他程序更改，请重试。')
            commit(game, stage, changes, before)
    return '简体中文补丁已安装。', 0


def restore(game, progress):
    if not game.is_dir():
        raise ValueError('找不到游戏目录。')
    undo_pending(game)
    original = read_registration(game)
    state = read_state(game)
    if not state:
        if (game / STATE).exists():
            raise ValueError('当前汉化安装记录无法读取，请保留备份。')
        return '当前没有可还原的汉化安装。', 0
    baseline = backup_path(game, state)
    if PREVIOUS in state and baseline is None:
        raise ValueError('缺少本次安装的还原备份，请恢复 PrototypeZh 备份目录后重试。')
    if not baseline and not state.get('archive_sha256'):
        raise ValueError('当前记录无法识别为汉化安装。')
    progress('正在还原汉化文件…')
    before = {name: file_hash(game / name) for name in FILES}
    if not baseline:
        # A restored legacy installation keeps its own original state.json.
        for path in (game / 'PrototypeZh').glob('BeforeSetup-*/restored-state.txt'):
            if path.read_text('ascii') == before[STATE]:
                return '本次安装已还原。', 0
    prior = {name: None for name in FILES}
    previous = None
    previous_groups = None
    if baseline:
        prior = json.loads((baseline / 'before.json').read_bytes())
        if set(prior) != set(FILES) or file_hash(baseline / CEMENT) != prior[CEMENT]:
            raise ValueError('安装前的注册表备份校验失败。')
        if prior[CEMENT] is not None:
            previous = (baseline / CEMENT).read_bytes()
            parsed = parse_registration(previous)
            previous_groups = parsed[1] if parsed else None
    retained = False
    if baseline and original is None:
        registered = previous
    elif parse_registration(original) is not None:
        registered, _ = setup.cement_edit(original, False, previous_groups)
        if baseline and previous_groups is None:
            template = Path(__file__).with_name('registration.p3d').read_bytes()
            if registered == template:
                registered = previous
    else:
        registered = original
        retained = True
    with staging(game) as stage:
        changes = {CEMENT: small_file(stage, 'new-cement.p3d', registered) if registered is not None else (None, None)}
        support = state.get('runtime_support') or {}
        for name, owned in [(ARCHIVE, state['archive_sha256']), (RUNTIME, support.get('sha256')), (STATE, before[STATE])]:
            if before[name] is not None and before[name] != owned:
                retained = True
                continue
            target = None
            if prior[name] is not None and prior[name] != before[name]:
                target = stage / ('restore-' + BACKUP_FILE[name])
                with (baseline / BACKUP_FILE[name]).open('rb') as src:
                    copy_verified(src, target, prior[name])
            changes[name] = (target, prior[name])
        if baseline and prior[STATE] is not None:
            (baseline / 'restored-state.txt').write_text(prior[STATE], encoding='ascii')
        commit(game, stage, changes, before)
    return ('已还原汉化。安装后被其他补丁替换的文件已保留。' if retained else '已还原汉化。'), 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('install', 'restore'))
    p.add_argument('--game', required=True, type=Path)
    p.add_argument('--package', type=Path)
    p.add_argument('--ipc', action='store_true')
    p.add_argument('--accept-risk', action='store_true')
    args = p.parse_args(argv)
    def emit(kind, message):
        print((kind + '\t' if args.ipc else '') + message, flush=True)
    def confirm():
        if args.accept_risk:
            return True
        emit('warning', WARNING)
        answer = sys.stdin.readline().strip().casefold()
        return answer in ('yes', 'y', '是')
    def progress(message):
        emit('progress', message)
    try:
        if not args.ipc:
            setup.ensure_game_closed()
        if args.action == 'install':
            if not args.package:
                p.error('--package is required')
            message, code = install(args.game.resolve(), args.package.resolve(), confirm, progress)
        else:
            message, code = restore(args.game.resolve(), progress)
    except Exception as error:
        message, code = str(error), 1
    emit('result', message.replace('\r', ' ').replace('\n', ' '))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
