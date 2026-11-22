"""Rebuild the localization overlay using only translations, deltas and the player's files."""
import base64
from collections import Counter, defaultdict
from contextlib import ExitStack
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import zlib

import setup
from audio_dialogue import patch_audio_subtitles, read_audio_subtitles
from full_resources import credits_translate, patch_rows
from inventory_all import holders
from lua_display import patch_display
from resources import name_hash, rcf_index, repack_rz, sha, swf_tags, unpack_rz, write_rcf

FORMAT = 'local-resource-delta-v1'
FONTS = 'font-changes.xz'
UI = 'ui-deltas.json'
FORMAT_ERRORS = (ValueError, AssertionError, IndexError, KeyError, struct.error, OverflowError, zlib.error)


def file_identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class LocalSources:
    """Index only relevant archives. The first registration for a resource has priority."""
    def __init__(self, game, rows, groups):
        self.game = game
        self.rows = rows
        self.groups = groups
        self.handles = ExitStack()
        self.files = {}
        self.locations = {}
        self.hashes = {}
        self.changed = False
        self.baseline = True

    def __enter__(self):
        try:
            self.scan()
        except BaseException:
            self.handles.close()
            raise
        return self

    def __exit__(self, *exc):
        self.handles.close()

    def scan(self):
        wanted = {name_hash(r['asset']): r['archive'].lower() for r in self.rows}
        canonical = set(wanted.values())
        order = {}
        for _, names in self.groups:
            for name in names:
                order.setdefault(name.lower(), name)
        for name in sorted(canonical):
            if name not in order:
                self.changed = True
                order[name] = name
        for key, name in order.items():
            if key == setup.OWN.lower() or (key in setup.BASE and key not in canonical):
                continue
            path = (self.game / name).resolve()
            if not path.is_relative_to(self.game.resolve()):
                self.changed = True
                continue
            try:
                identity = file_identity(path)
                entries = rcf_index(path)
                stream = self.handles.enter_context(path.open('rb'))
            except (OSError, *FORMAT_ERRORS):
                self.changed = True
                continue
            self.files[path] = identity
            for entry in entries:
                asset = entry['key']
                if asset not in wanted or (key in canonical and wanted[asset] != key):
                    continue
                if key not in canonical:
                    self.changed = True
                self.locations.setdefault(asset, (stream, entry['offset'], entry['size']))
        fingerprint = hashlib.sha256()
        for row in self.rows:
            data = self.read(row)
            digest = None if data is None else sha(data)
            self.hashes[row['asset']] = digest
            fingerprint.update(b'\x00' if digest is None else b'\x01' + bytes.fromhex(digest))
            if digest != row['source_sha256']:
                self.baseline = False
        self.changed |= not self.baseline
        self.fingerprint = fingerprint.hexdigest()
        self.check_files()

    def read(self, row):
        location = self.locations.get(name_hash(row['asset']))
        if location is None:
            return None
        stream, offset, length = location
        stream.seek(offset)
        data = stream.read(length)
        if len(data) != length:
            raise OSError('读取本地资源时文件已改变。')
        return data

    def check_files(self):
        if any(file_identity(path) != ident for path, ident in self.files.items()):
            raise OSError('安装期间游戏资源被其他程序更改，请重试。')


def font_name(code, payload):
    if code == 75:
        return payload[5:5+payload[4]].rstrip(b'\0').decode('ascii')
    if code == 1005:
        return payload[2:payload.index(0, 2)].decode('ascii')
    return None


def load_recipes(source, manifest):
    spec = manifest['distribution']
    if spec['format'] != FORMAT:
        raise ValueError('无法识别该差分包。')
    def verified(name):
        with source(name) as stream:
            data = stream.read()
        if sha(data) != spec['files'][name]:
            raise ValueError('安装包内的差分数据校验失败。')
        return data
    fonts = defaultdict(dict)
    data = lzma.decompress(verified(FONTS))
    pos = 0
    while pos < len(data):
        ordinal, size, count = struct.unpack_from('<IIB', data, pos)
        pos += 9
        face = data[pos:pos+count].decode('ascii')
        pos += count
        record = data[pos:pos+size]
        if len(record) != size or face in fonts[ordinal]:
            raise ValueError('字形差分记录无效。')
        fonts[ordinal][face] = record
        pos += size
    return fonts, json.loads(verified(UI))


def patch_font(data, changes):
    prefix, tags = swf_tags(data)
    out = bytearray(prefix)
    seen = set()
    for code, payload, raw in tags:
        face = font_name(code, payload)
        if face in changes:
            if face in seen:
                raise ValueError('Ambiguous local font')
            seen.add(face)
            replacement = changes[face]
            # The two-byte character ID belongs to this local movie.
            if (struct.unpack_from('<H', replacement)[0] != ((1005 << 6) | 63)
                    or font_name(1005, replacement[6:]) != face):
                raise ValueError('Invalid compact font record')
            raw = replacement[:6] + payload[:2] + replacement[8:]
        out.extend(raw)
    if seen != set(changes):
        raise ValueError('Local font roles differ')
    out[4:8] = struct.pack('<I', len(out))
    return bytes(out)


def patch_ui(data, plan, baseline):
    prefix, tags = swf_tags(data)
    parts = [raw for _, _, raw in tags]
    hashes = [sha(raw) for raw in parts]
    edits = []
    for change in plan:
        at = change['at']
        if 'from' in change:
            if not baseline:
                choices = [i for i, h in enumerate(hashes) if h == change['from']]
                if not choices and hashes.count(change['to']) == 1:
                    continue
                if len(choices) != 1:
                    raise ValueError('Local UI record differs')
                at = choices[0]
            if hashes[at] != change['from']:
                raise ValueError('UI delta input mismatch')
            raw = parts[at]
            new = b''.join(raw[p[0]:p[0]+p[1]] if isinstance(p, list) else base64.b64decode(p, validate=True)
                           for p in change['parts'])
            end = at + 1
        else:
            if not baseline:
                if change['to'] in hashes:
                    continue
                left, right = change['left'], change['right']
                choices = [i for i in range(len(parts)+1) if i >= len(left)
                           and hashes[i-len(left):i] == left and hashes[i:i+len(right)] == right]
                if len(choices) != 1:
                    raise ValueError('Local UI insertion point differs')
                at = choices[0]
            new = base64.b64decode(change['data'], validate=True)
            end = at
        if sha(new) != change['to']:
            raise ValueError('UI delta output mismatch')
        edits.append((at, end, new))
    for at, end, new in sorted(edits, key=lambda e:(e[0],e[1]), reverse=True):
        parts[at:end] = [new]
    out = bytearray(prefix)
    out.extend(b''.join(parts))
    out[4:8] = struct.pack('<I', len(out))
    swf_tags(out)
    return bytes(out)


TOKENS = re.compile(r'%\d+:[A-Z][A-Z0-9_]*|\\[a-zA-Z]+')


def text_resource(raw, row, labels, baseline):
    changes = row['changes']
    extra = {key: labels[key] for key in row['appended_ids']}
    if baseline:
        rows = [dict(id=c['id'], text=c['source'], zh=c['zh']) for c in changes]
        return patch_rows(raw, rows, extra)[0], True
    local = holders(raw)
    source_keys = defaultdict(list)
    for c in changes:
        source_keys[c['id']].append(c)
    counts = Counter(r['id'] for r in local)
    used = Counter()
    extra_english = False
    rows = []
    for current in local:
        key, text = current['id'], current['text']
        translation = text
        if key in extra:
            translation = extra[key]
        elif key in source_keys:
            options = source_keys[key]
            exact = {c['zh'] for c in options if text in (c['source'], c['zh'])}
            if len(exact) == 1:
                translation = exact.pop()
            elif len(options) == counts[key] == 1:
                translation = options[0]['zh']
            else:
                rows.append(dict(id=key, text=text, zh=text))
                continue
            if sorted(TOKENS.findall(text)) == sorted(TOKENS.findall(translation)):
                used[key] += 1
            else:
                translation = text
        elif re.search(r'[A-Za-z]', TOKENS.sub('', text)):
            extra_english = True
        rows.append(dict(id=key, text=text, zh=translation))
    additions = {key: value for key, value in extra.items() if key not in counts}
    if not used and not any(key in counts for key in extra):
        raise ValueError('No matching local text IDs')
    complete = not extra_english and all(used[key] == len(items) for key, items in source_keys.items())
    return patch_rows(raw, rows, additions)[0], complete


def localize(data, row, number, fonts, ui, labels, baseline):
    raw = unpack_rz(data)
    kind = row['kind']
    complete = True
    if kind == 'audio-subtitles':
        mapping = {c['id']: (c['source'], c['zh']) for c in row['changes']}
        if not baseline:
            local = read_audio_subtitles(raw)
            matched = {r['id']: (r['text'], mapping[r['id']][1]) for r in local if r['id'] in mapping}
            if not matched:
                raise ValueError('No matching local dialogue IDs')
            complete = len(matched) == len(mapping) and all(
                r['id'] in mapping or not r['text'].strip() for r in local)
            mapping = matched
        new, _ = patch_audio_subtitles(raw, mapping)
    elif kind == 'text':
        new, complete = text_resource(raw, row, labels, baseline)
    elif kind == 'font':
        new = patch_font(raw, fonts[number])
    elif kind in ('initial-ui-labels', 'save-ui-labels'):
        new = patch_ui(raw, ui[row['asset']], baseline)
    elif kind == 'lua-display':
        new, _ = patch_display(raw, row['changes'])
    elif kind == 'credits':
        mapping = {r['source']: r['zh'] for r in row['changes']}
        new, actual, _ = credits_translate(raw, mapping, strict=baseline)
        if not actual:
            raise ValueError('No matching credit headings')
        complete = Counter(x['source'] for x in row['changes']) <= Counter(x['source'] for x in actual)
    else:
        raise ValueError('Unknown localization resource type')
    return repack_rz(data, new), complete


def generate(path, inputs, source, manifest, progress):
    fonts, ui = load_recipes(source, manifest)
    labels = {**manifest['modern_labels'], **manifest['native_display_labels']}
    rows = manifest['resources']
    omitted, partial = [], []
    def assets():
        for number, row in enumerate(rows):
            name = row['asset']
            data = inputs.read(row)
            digest = None if data is None else sha(data)
            if digest != inputs.hashes[name]:
                raise OSError('安装期间游戏资源被其他程序更改，请重试。')
            if data is None:
                omitted.append(name)
                continue
            baseline = digest == row['source_sha256']
            if digest == row['sha256']:
                result, complete = data, True
            else:
                try:
                    result, complete = localize(data, row, number, fonts, ui, labels, baseline)
                except FORMAT_ERRORS:
                    if baseline: raise
                    omitted.append(name)
                    continue
            if baseline and sha(result) != row['sha256']:
                raise ValueError('本地生成的汉化资源与发行清单不符。' + name)
            if not complete:
                partial.append(name)
            if number % 2000 == 0:
                progress('正在生成汉化资源… %d / %d' % (number+1, len(rows)))
            yield name, result
    with path.open('x+b') as out:
        write_rcf(out, (r['asset'] for r in rows), assets())
    if len(omitted) == len(rows):
        raise ValueError('游戏目录中没有可生成汉化的资源。')
    inputs.check_files()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if inputs.baseline and digest != manifest['archive_sha256']:
        raise ValueError('生成的完整汉化包校验失败。')
    return digest, dict(generated=len(rows)-len(omitted), omitted=omitted, partial=partial)
