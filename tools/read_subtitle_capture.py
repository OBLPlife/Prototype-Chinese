"""Decode the optional 64 KiB subtitle capture, without operating the game.

No output file is written unless --output is supplied. Durations are QPC wall
spans on the calling CPU thread, not exclusive CPU execution or GPU duration.
"""
import argparse
import json
import mmap
from pathlib import Path
import struct

MAGIC, VERSION, FILE_BYTES = 0x3150535A, 1, 65536
HEADER_BYTES, BUCKET_BYTES, RECORD_BYTES, KINDS, RECORDS = 128, 48, 64, 8, 1016
NAMES = {
    1: 'render_submit', 2: 'gfx_set_text', 3: 'gfx_position',
    4: 'gfx_objective', 5: 'gfx_visibility', 6: 'gfx_append',
    7: 'gfx_autosize', 8: 'objective_trigger',
}


def decode(data, include_events=False, stable_copy=True):
    if len(data) != FILE_BYTES:
        raise ValueError(f'Capture must be exactly {FILE_BYTES} bytes')
    magic, version, header_bytes, file_bytes, record_bytes, record_count, kind_count, pid = struct.unpack_from('<8I', data)
    if (magic, version, header_bytes, file_bytes, record_bytes, record_count, kind_count) != (
            MAGIC, VERSION, HEADER_BYTES, FILE_BYTES, RECORD_BYTES, RECORDS, KINDS):
        raise ValueError('Unsupported capture header or layout')
    creation, frequency, initialized, utc, published, dropped, invalid, overwritten = struct.unpack_from('<8Q', data, 32)
    gate, sequence, detached, status, next_slot = struct.unpack_from('<5I', data, 96)
    sampling_stride, capture_build_tag = struct.unpack_from('<2I', data, 116)
    if not frequency or next_slot >= RECORDS or gate > 1 or detached > 1 or status != 1:
        raise ValueError('Invalid capture metadata')
    coherent = stable_copy and gate == 0 and sequence % 2 == 0
    names = dict(NAMES)
    if capture_build_tag >= 0x00020a02:
        names[8] = 'subtitle_markers'
    result = dict(format_version=version, file_bytes=file_bytes, limit_bytes=1_000_000,
                  pid=pid, creation_filetime=creation, qpc_frequency=frequency,
                  initialized_qpc=initialized, initialized_utc_filetime=utc,
                  normal_detach_observed=bool(detached), coherent_snapshot=coherent,
                  published=published, contention_dropped=dropped, invalid_events=invalid,
                  overwritten_detail_records=overwritten, lifetime_summary_scope='successfully captured events only',
                  duration_scope='calling-thread QPC wall span; includes scheduling; not exclusive CPU or GPU time',
                  ordinary_sampling_stride=sampling_stride, capture_build_tag=f'0x{capture_build_tag:08x}',
                  sampling_scope='producer sampling policy; storage records every Publish call; standalone storage fixtures publish without sampling',
                  exclusive_gpu_time=None,
                  cpu_spans_overlap=True,
                  cpu_overlap_note='render_submit can include actual UI execution on the immediate path; do not sum nested category totals',
                  event_capacity=record_count, buckets={}, records_retained=0,
                  incomplete_or_invalid_records=0)
    for i in range(KINDS):
        offset = HEADER_BYTES + i * BUCKET_BYTES
        seq, _, count, ticks, maximum, last_begin, last_end = struct.unpack_from('<II5Q', data, offset)
        valid = coherent and seq % 2 == 0 and (not count or (last_end >= last_begin and maximum <= ticks))
        result['buckets'][names[i + 1]] = dict(valid=valid, count=count if valid else None,
            total_wall_us=round(ticks * 1_000_000 / frequency, 6) if valid else None,
            maximum_wall_us=round(maximum * 1_000_000 / frequency, 6) if valid else None,
            average_wall_us=round(ticks * 1_000_000 / frequency / count, 6) if valid and count else None,
            last_begin_qpc=last_begin if valid else None, last_end_qpc=last_end if valid else None)
    events = []
    for i in range(RECORDS):
        offset = HEADER_BYTES + KINDS * BUCKET_BYTES + i * RECORD_BYTES
        seq, kind, serial, begin, end, tid, aux0, aux1, context, detail, commit = struct.unpack_from('<II3Q4I2Q', data, offset)
        if not seq and not serial:
            continue
        if (seq % 2 or not 1 <= kind <= KINDS or serial != commit or not serial or
                serial > published or end < begin or published - serial >= RECORDS):
            result['incomplete_or_invalid_records'] += 1
            continue
        row = dict(serial=serial, kind=NAMES[kind], tid=tid, begin_qpc=begin, end_qpc=end,
                   wall_us=round((end - begin) * 1_000_000 / frequency, 6), aux0=aux0, aux1=aux1)
        if capture_build_tag >= 0x00020a02:
            if kind == 8 and context in (1, 2):
                started, duration = detail & 0xffffffff, detail >> 32
                age = (aux1 - started) & 0xffffffff
                row.update(kind='subtitle_member_submitted' if context == 1 else 'subtitle_member_expired',
                           subtitle_id=aux0, game_now_ms=aux1, started_ms=started,
                           configured_duration_ms=duration, effective_duration_ms=duration or 10000,
                           age_ms=age, age_exceeds_half_clock_range=age >= 0x80000000,
                           note='Submission membership or actual patch expiry; not proof of on-screen visibility or audible completion')
            elif kind == 5 and context == 3:
                row['show_argument'] = bool(aux1)
            elif kind == 2 and context == 4:
                row['text_nonempty'] = bool(aux1)
        events.append(row)
    events.sort(key=lambda row: row['serial'])
    result['records_retained'] = len(events)
    if include_events:
        result['events'] = events
    return result


def read_capture(path, include_events=False):
    # A bounded seqlock copy also permits an explicitly requested live inspection.
    # No polling process is installed or kept running by this decoder.
    with Path(path).open('rb') as stream:
        if stream.seek(0, 2) != FILE_BYTES:
            raise ValueError(f'Capture must be exactly {FILE_BYTES} bytes')
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
            for _ in range(3):
                first = struct.unpack_from('<II', view, 96)
                data = view[:]
                last = struct.unpack_from('<II', view, 96)
                if first == last and first[0] == 0 and first[1] % 2 == 0:
                    return decode(data, include_events, stable_copy=True)
            return decode(data, include_events, stable_copy=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--events', action='store_true', help='Include retained ring detail')
    parser.add_argument('--output', type=Path, help='Explicit optional JSON report destination')
    args = parser.parse_args()
    text = json.dumps(read_capture(args.path, args.events), ensure_ascii=False, indent=2) + '\n'
    if args.output:
        if args.output.resolve() == args.path.resolve():
            parser.error('Output must not replace the binary capture')
        args.output.write_text(text, 'utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
