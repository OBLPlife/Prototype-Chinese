"""Recover English catalog inputs from the player's original game for the source build.

The subtitle block and timing readers are from the project's original text audit.
The RCF/P3D format attribution and notice are in resources.py.
"""
import argparse
import json
from pathlib import Path
import struct

from audio_dialogue import read_audio_subtitles
from resources import rcf_index, rcf_read, sha, u32, unpack_rz

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / 'work/PrototypeZh/english-catalog'
SUBTITLE_ARCHIVES = ('00woi.rcf', '01woi.rcf', '02woi.rcf', '03woi.rcf', 'movies.rcf', 'art.rcf')


def text_holder(data, start):
    position = start + 12
    def read_name():
        nonlocal position
        size = data[position]
        value = data[position+1:position+1+size].rstrip(b'\0').decode('ascii')
        position += size + 1
        return value
    language = read_name()
    version, count = struct.unpack_from('<II', data, position)
    position += 8
    keys = [read_name() for _ in range(count)]
    starts = struct.unpack_from('<' + str(count) + 'I', data, position)
    position += count * 4
    stops = struct.unpack_from('<' + str(count) + 'I', data, position)
    position += count * 4
    assert position == start + u32(data, start + 4)
    assert u32(data, position) == 0x18201
    storage_start = position
    position += 12
    read_name()
    storage_version, size = struct.unpack_from('<II', data, position)
    position += 8
    blob = data[position:position+size]
    assert position + size == storage_start + u32(data, storage_start + 8)
    if not count:
        return language, []
    assert starts[0] == 0 and stops[-1] == size + 1
    assert all(a == b + 1 for a, b in zip(stops[:-1], starts[1:]))
    rows = [dict(id=k, text=blob[a:b-1].decode('utf-8'), start=a, stop=b,
                 holder_offset=start) for k, a, b in zip(keys, starts, stops)]
    assert b''.join(r['text'].encode('utf-8') for r in rows) == blob
    return language, rows

def read_p3d(data):
    assert u32(data, 0) == 0xff443350 and u32(data, 8) == len(data)
    rows, timings = [], {}
    def walk(start, end):
        while start < end:
            kind, header, total = struct.unpack_from('<III', data, start)
            assert 12 <= header <= total and start + total <= end
            if kind == 0x18202:
                language, found = text_holder(data, start)
                if language == 'english':
                    rows.extend(found)
            if kind == 0x7f00001 and data[start+16:start+20] == b'META':
                position = start + 24
                count = u32(data, start + 20)
                temp = {}
                for _ in range(count):
                    size = u32(data, position)
                    position += 4
                    key = data[position:position+size].decode('ascii')
                    position += size
                    begin, finish = struct.unpack_from('<ff', data, position)
                    position += 8
                    assert 0 <= begin <= finish
                    temp[key] = [round(begin, 5), round(finish, 5)]
                assert position == start + header
                timings.update(temp)
            if header < total:
                walk(start + header, start + total)
            start += total
        assert start == end
    walk(0, len(data))
    for row in rows:
        if row['id'] in timings:
            row['time_seconds'] = timings[row['id']]
    return rows

def english_rows(game):
    ui = read_p3d(unpack_rz(rcf_read(game / 'art.rcf', r'\art\hud\textbible_english.p3d.rz')))
    ui = [{k: r[k] for k in ('id', 'start', 'stop', 'text')} for r in ui]
    subtitles = []
    for archive in SUBTITLE_ARCHIVES:
        path = game / archive
        with path.open('rb') as stream:
            for entry in rcf_index(path):
                name = entry['name']
                if archive == 'art.rcf':
                    matches = name.startswith('\\art\\nis\\') and name.endswith('.p3d.rz')
                else:
                    matches = name.endswith('.p3d')
                if matches:
                    stream.seek(entry['offset'])
                    rows = read_p3d(unpack_rz(stream.read(entry['size'])))
                    subtitles.extend(dict(r, archive=archive, asset=name) for r in rows)
    audio = []
    for archive in ('00audio.rcf', '01audio.rcf'):
        path = game / archive
        with path.open('rb') as stream:
            for entry in rcf_index(path):
                name = entry['name']
                if not name.lower().startswith('audio\\english\\audiofile\\') or not name.lower().endswith('.p3d'):
                    continue
                stream.seek(entry['offset'])
                packed = stream.read(entry['size'])
                rows = read_audio_subtitles(unpack_rz(packed))
                if rows:
                    source_hash = sha(packed)
                    audio.extend(dict(archive=archive, asset=name, source_sha256=source_hash, **r) for r in rows)
    return {'english_text_inventory.json': ui, 'english_subtitles.json': subtitles, 'audio-subtitles.json': audio}


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--game', required=True, type=Path)
    cli.add_argument('--out', type=Path, default=DEFAULT_OUTPUT)
    args = cli.parse_args()
    tables = english_rows(args.game)
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, rows in tables.items():
        (args.out / filename).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(filename, len(rows))
