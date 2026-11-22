"""Append removable, event-driven subtitle placement actions to owned movies.

Original DoAction payloads, graphics, transforms and timeline frames remain
byte-identical. In particular, Modern's original-root action signature still
matches; this module does not hook or replace its native action loader.
"""
import json
import struct
import subprocess
from pathlib import Path

from avm1_literals import inline_constants
from full_resources import tag_bytes
from resources import p32, sha, swf_tags

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {name: ROOT / 'runtime' / ('subtitle_layout_' + name + '.as')
           for name in ('main', 'hud', 'objective', 'hidden')}
LOCATIONS = {
    'protomain.gfx': [('main', 0, 1)],
    'protohud.gfx': [('hud', 0, 1), ('objective', 393, 1), ('hidden', 393, 250)],
}


def make_actions(work, ffdec):
    """Compile only our four AS2 files; return (payload_by_name, source_audit)."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    actions, audit = {}, {}
    for name, source in SOURCES.items():
        folder = work / name
        scripts = folder / 'scripts/frame_1'
        scripts.mkdir(parents=True, exist_ok=True)
        original = source.read_bytes()
        (scripts / 'DoAction.as').write_bytes(original)
        body = (b'\x08\x00' + struct.pack('<HH', 24 * 256, 1) +
                tag_bytes(12, b'\0') + tag_bytes(1, b'') + tag_bytes(0, b''))
        blank, compiled = folder / 'blank.swf', folder / 'compiled.swf'
        blank.write_bytes(b'FWS\x08' + p32(len(body) + 8) + body)
        result = subprocess.run(['java', '-Djava.awt.headless=true', '-jar', str(ffdec),
                                 '-importScript', str(blank), str(compiled), str(folder / 'scripts')],
                                capture_output=True)
        (folder / 'compile.log').write_bytes(result.stdout + result.stderr)
        result.check_returncode()
        blocks = [p for c, p, _ in swf_tags(compiled.read_bytes())[1] if c == 12]
        assert len(blocks) == 1
        code = inline_constants(blocks[0])
        (work / (name + '.avm1')).write_bytes(code)
        actions[name] = code
        audit[name] = dict(source_file=str(source), source_sha256=sha(original),
                           actions_sha256=sha(code), action_bytes=len(code))
    (work / 'actions.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return actions, audit


def read_actions(work):
    work = Path(work)
    audit = json.loads((work / 'actions.json').read_text('utf-8'))
    actions = {name: (work / (name + '.avm1')).read_bytes() for name in SOURCES}
    for name, code in actions.items():
        assert sha(code) == audit[name]['actions_sha256'] and len(code) == audit[name]['action_bytes']
    return actions, audit


def _sprite_tags(payload):
    # A DefineSprite starts with uint16 symbol ID and frame count.
    body = b'\x08\x00\x00\x00\x01\x00' + payload[4:]
    return swf_tags(b'FWS\x08' + p32(len(body) + 8) + body)[1]


def _rebuild(prefix, data):
    result = bytearray(prefix + data)
    result[4:8] = p32(len(result))
    return bytes(result)


def patch_movie(movie, asset, actions, source_audit=None):
    """Append actions at exact sprite/frame ends, returning (movie, audit)."""
    basename = asset.replace('/', '\\').split('\\')[-1].lower()
    locations = LOCATIONS[basename]
    inserts = {(sprite, frame): name for name, sprite, frame in locations}
    prefix, tags = swf_tags(movie)
    found, records = set(), []

    def visit(items, sprite):
        frame, output = 1, []
        for code, payload, raw in items:
            if code == 39:
                symbol, frames = struct.unpack_from('<HH', payload)
                if symbol == 393 and basename == 'protohud.gfx':
                    assert frames == 250
                    changed = payload[:4] + visit(_sprite_tags(payload), symbol)
                    raw = tag_bytes(39, changed)
            if code == 1:
                key = (sprite, frame)
                if key in inserts:
                    assert key not in found
                    name = inserts[key]
                    block = actions[name]
                    assert block and block[-1] == 0
                    output.append(tag_bytes(12, block))
                    found.add(key)
                    records.append(dict(name=name, sprite_id=sprite, frame=frame,
                                        action_bytes=len(block), actions_sha256=sha(block)))
                frame += 1
            output.append(raw)
        return b''.join(output)

    changed = _rebuild(prefix, visit(tags, 0))
    assert found == set(inserts)
    audit = dict(schema=1, source_sha256=sha(movie), patched_sha256=sha(changed),
                 insertions=records, original_actions_unchanged=True,
                 original_geometry_and_timelines_unchanged=True,
                 event_driven=True, per_frame_polling=False)
    if source_audit:
        audit['sources'] = {name: source_audit[name] for name, _, _ in locations}
    verify_movie(movie, changed, audit)
    return changed, audit


def strip_actions(movie, audit):
    """Remove only audited actions, reconstructing the exact pre-layout movie."""
    assert audit['schema'] == 1 and sha(movie) == audit['patched_sha256']
    expected = {(r['sprite_id'], r['frame']): r for r in audit['insertions']}
    prefix, tags = swf_tags(movie)
    found = set()

    def visit(items, sprite):
        frame, output = 1, []
        for index, (code, payload, raw) in enumerate(items):
            if code == 39:
                symbol = struct.unpack_from('<H', payload)[0]
                if any(key[0] == symbol for key in expected):
                    restored = payload[:4] + visit(_sprite_tags(payload), symbol)
                    raw = tag_bytes(39, restored)
            key = (sprite, frame)
            record = expected.get(key)
            if code == 12 and record and sha(payload) == record['actions_sha256']:
                assert key not in found and len(payload) == record['action_bytes']
                assert index + 1 < len(items) and items[index + 1][0] == 1
                found.add(key)
                continue
            if code == 1:
                frame += 1
            output.append(raw)
        return b''.join(output)

    restored = _rebuild(prefix, visit(tags, 0))
    assert found == set(expected) and sha(restored) == audit['source_sha256']
    return restored


def verify_movie(before, after, audit):
    assert sha(before) == audit['source_sha256']
    assert strip_actions(after, audit) == before
    return True
