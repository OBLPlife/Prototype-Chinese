"""Review subtitle CPU capture and optional existing engine.log after game exit.

No game/process access, background collector, GPU queries or automatic log search.
Only --output writes a report. GPU context is whole-frame sampled command time,
never subtitle-exclusive time; temporal association does not establish causality.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys

# Importing the decoder must not create a default __pycache__ output either.
sys.dont_write_bytecode = True
from read_subtitle_capture import read_capture

MAX_LOG_BYTES = 1_000_000
SESSION_MARKERS = {'session_start', 'checkpoint', 'session_checkpoint',
                   'resume', 'session_resume', 'session_end'}
GPU_STATUSES = {1: 'valid', 2: 'unsupported', 3: 'query_error',
                4: 'disjoint', 5: 'expired_or_aborted'}


def uint(value, positive=False):
    return type(value) is int and value >= (1 if positive else 0)


def identity(row):
    pid, creation = row.get('pid'), row.get('creation_filetime')
    return (pid, creation) if uint(pid, True) and uint(creation, True) else None


def read_engine_rows(path):
    """Read at most the decimal-MB ceiling; never repair or rewrite the log."""
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_LOG_BYTES:
            raise ValueError(f'Engine log exceeds {MAX_LOG_BYTES} bytes')
        data = stream.read(before.st_size)
        after = os.fstat(stream.fileno())
        if (after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns
                or len(data) != before.st_size):
            raise ValueError('Engine log changed during offline review; retry after game exit')
    rows, malformed_trailing = [], 0
    lines = data.splitlines()
    for index, raw in enumerate(lines):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode('utf-8-sig' if index == 0 else 'utf-8'))
            if not isinstance(row, dict):
                raise ValueError('Record is not an object')
        except (UnicodeDecodeError, ValueError) as error:
            if index != len(lines) - 1:
                raise ValueError(f'Malformed engine log line {index + 1}') from error
            malformed_trailing = 1
            continue
        rows.append((index + 1, row))
    return rows, dict(bytes_read=len(data), byte_limit=MAX_LOG_BYTES,
                      parsed_records=len(rows), malformed_trailing_lines_ignored=malformed_trailing)


def normalize_gpu(raw):
    """Missing, expired and invalid observations stay null, never timing zero."""
    status, flags = raw.get('status'), raw.get('flags')
    status = status if uint(status) else None
    flags = flags if uint(flags) else 0
    begin, end = raw.get('qpc_begin'), raw.get('qpc_end')
    frame = raw.get('frame_id')
    gpu_frequency, start, finish = (raw.get(key) for key in ('gpu_frequency', 'gpu_start', 'gpu_end'))
    duration = raw.get('command_span_ms')
    reason = None
    if status != 1:
        reason = GPU_STATUSES.get(status, 'unknown_or_unpublished_status')
    elif not flags & 1:
        reason = 'gpu_timestamps_not_valid'
    elif not (uint(gpu_frequency, True) and uint(start) and uint(finish) and finish >= start):
        reason = 'invalid_gpu_clock_interval'
    elif not (type(duration) in (int, float) and math.isfinite(duration) and duration >= 0):
        reason = 'invalid_gpu_duration'
    interval_valid = (uint(frame, True) and uint(begin, True) and uint(end, True)
                      and end >= begin and bool(flags & 2))
    result = dict(frame_id=frame if uint(frame) else None,
                  qpc_begin=begin if uint(begin) else None, qpc_end=end if uint(end) else None,
                  status=status, status_name=GPU_STATUSES.get(status, 'unknown_or_unpublished_status'),
                  flags=flags, command_span_ms=duration if reason is None else None,
                  gpu_timing_valid=reason is None, correlation_interval_valid=bool(interval_valid),
                  unavailable_reason=reason or (None if interval_valid else 'invalid_cpu_submission_interval'))
    ready = raw.get('query_ready_qpc')
    result['query_ready_qpc'] = ready if uint(ready, True) else None
    return result


def engine_context(path, capture):
    result = dict(availability='not_requested', path=str(path) if path else None,
                  samples=[], candidates_seen=0, duplicate_records=0, rejected_records={},
                  evicted_detail_lines_reported=0, usable_gpu_samples=0,
                  subtitle_exclusive_gpu_ms=None,
                  scope='sampled BeginScene-to-before-Present GPU command span for the whole frame; not continuous GPU busy',
                  qpc_scope='CPU command-submission interval, not a timestamped GPU execution interval',
                  frame_id_scope='producer diagnostic sample ID; not a native Present frame identity',
                  association_scope='timestamp proximity only; no causality or subtitle-exclusive cost',
                  detail_scope='retained log records only; rolled-away GPU details are not reconstructed')
    if path is None:
        return result
    try:
        rows, metadata = read_engine_rows(path)
    except FileNotFoundError:
        result['availability'] = 'file_missing'
        return result
    result.update(metadata)
    expected = identity(capture)
    expected_frequency = capture['qpc_frequency']
    current_identity, current_frequency = None, None
    rejects, unique, conflicts = Counter(), {}, set()
    for line, row in rows:
        kind = row.get('kind')
        if kind in SESSION_MARKERS:
            next_identity = identity(row)
            if next_identity != current_identity or kind == 'session_start':
                current_frequency = None
            current_identity = next_identity
            row_identity = next_identity
            evicted = row.get('evicted_detail_lines', row.get('detail_lines_evicted', 0))
            if uint(evicted) and row_identity == expected:
                result['evicted_detail_lines_reported'] = max(result['evicted_detail_lines_reported'], evicted)
        elif 'creation_filetime' in row:
            row_identity = identity(row)
        else:
            row_identity = (current_identity if current_identity and
                            uint(row.get('pid'), True) and row['pid'] == current_identity[0] else None)
        measured = row.get('measured')
        measured = measured if isinstance(measured, dict) else {}
        measured_frequency = measured.get('qpc_frequency') if measured.get('status') == 'observed' else None
        explicit_frequency = row.get('qpc_frequency')
        frequency_conflict = (explicit_frequency is not None and measured_frequency is not None
                              and explicit_frequency != measured_frequency)
        frequency = (measured_frequency if measured_frequency is not None else
                     explicit_frequency if explicit_frequency is not None else
                     current_frequency if row_identity == current_identity and current_identity else None)
        if not uint(frequency, True) or frequency_conflict:
            frequency = None
        if row_identity and row_identity == current_identity:
            # Identity markers do not acquire the subtitle capture's clock by inference.
            # A checkpoint may preserve only a frequency already observed in this session.
            if measured_frequency is not None or explicit_frequency is not None:
                current_frequency = frequency
        candidates = []
        if isinstance(measured.get('gpu_timing'), dict):
            candidates.append(('measured.gpu_timing', measured['gpu_timing'], measured.get('status') == 'observed'))
        if kind in SESSION_MARKERS and isinstance(row.get('last_gpu_timing'), dict):
            candidates.append(('last_gpu_timing', row['last_gpu_timing'], True))
        for source, raw, observed in candidates:
            result['candidates_seen'] += 1
            reason = ('unknown_identity' if not row_identity or not expected else
                      'process_identity_mismatch' if row_identity != expected else
                      'instrumentation_unavailable' if not observed else
                      'unknown_qpc_frequency' if frequency is None else
                      'qpc_frequency_mismatch' if frequency != expected_frequency else None)
            if reason:
                rejects[reason] += 1
                continue
            sample = normalize_gpu(raw)
            key = tuple(sample[field] for field in ('frame_id', 'qpc_begin', 'qpc_end'))
            if key in unique:
                result['duplicate_records'] += 1
                if unique[key]['timing'] != sample:
                    conflicts.add(key)
                continue
            unique[key] = dict(timing=sample, source_line=line, source_kind=kind, source_field=source)
        if kind == 'session_end':
            current_identity, current_frequency = None, None
    for key, saved in unique.items():
        sample = saved.pop('timing')
        sample.update(saved)
        if key in conflicts:
            sample.update(command_span_ms=None, gpu_timing_valid=False,
                          unavailable_reason='conflicting_duplicate_records')
        result['samples'].append(sample)
    result['rejected_records'] = dict(rejects)
    result['usable_gpu_samples'] = sum(sample['gpu_timing_valid'] and sample['correlation_interval_valid']
                                       for sample in result['samples'])
    if result['usable_gpu_samples']:
        result['availability'] = 'available'
    elif not result['candidates_seen']:
        result['availability'] = 'no_gpu_records'
    elif result['samples']:
        result['availability'] = 'no_valid_timing'
    else:
        result['availability'] = 'no_verified_matching_samples'
    return result


def associate_events(capture, context):
    """Use QPC interval distance only; never interpret it as GPU attribution."""
    frequency = capture['qpc_frequency']
    usable = [(index, sample) for index, sample in enumerate(context['samples'])
              if sample['gpu_timing_valid'] and sample['correlation_interval_valid']]
    result = []
    for event in capture['events']:
        row = dict(event, association='unavailable', sample_index=None, interval_gap_ms=None,
                   overlap_wall_us=None, overlapping_sample_count=0, zero_length_overlap=None,
                   subtitle_exclusive_gpu_ms=None, same_native_frame_proven=False)
        if capture['coherent_snapshot'] and usable:
            begin, end = event['begin_qpc'], event['end_qpc']
            ranked = []
            overlapping = 0
            for index, sample in usable:
                left, right = sample['qpc_begin'], sample['qpc_end']
                gap = max(0, left - end, begin - right)
                overlap = max(0, min(end, right) - max(begin, left))
                overlapping += int(gap == 0)
                ranked.append((gap, -overlap, left, index))
            gap, negative_overlap, _, index = min(ranked)
            sample = context['samples'][index]
            row.update(association='overlap' if gap == 0 else
                       'nearest_before' if sample['qpc_end'] < begin else 'nearest_after',
                       sample_index=index, interval_gap_ms=round(gap * 1000 / frequency, 6),
                       overlap_wall_us=round(-negative_overlap * 1_000_000 / frequency, 6),
                       overlapping_sample_count=overlapping,
                       zero_length_overlap=gap == 0 and negative_overlap == 0)
        result.append(row)
    return result


def review(path, engine_log=None):
    capture = read_capture(path, include_events=True)
    context = engine_context(engine_log, capture)
    events = associate_events(capture, context)
    metadata = {key: value for key, value in capture.items() if key not in ('events', 'buckets')}
    return dict(review_format_version=1, mode='offline_existing_files_only', capture=metadata,
                subtitle_exclusive_gpu_ms=None, live_collection_work_added=False,
                cpu=dict(buckets=capture['buckets'],
                         scope='observed calling-thread QPC wall spans; not exclusive CPU execution',
                         sampling=('r2 records text, visibility and member lifecycle events without ordinary sampling; other ordinary spans use stride 16' if int(capture['capture_build_tag'],16) >= 0x00020a02 else 'ordinary events sampled first and every 16th per kind/thread; objective-triggered and selected layout events forced') + '; aggregates cover successfully published observations only',
                         ordinary_sampling_stride=capture['ordinary_sampling_stride'],
                         extrapolated_to_all_events=False,
                         overlap='render_submit can contain actual UI execution; do not sum category totals',
                         layout='gfx_set_text includes text assignment and its layout; gfx_position is the explicit layout invocation, not every internal layout step',
                         marker='objective and member lifecycle records are zero-duration occurrence markers, not timed work',
                         detail='ring retains recent detail; lifetime buckets also retain overwritten observations; contention drops and invalid events are absent from bucket totals'),
                existing_gpu=context, retained_event_context=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, help='Existing PrototypeZh.Performance.bin')
    parser.add_argument('--engine-log', type=Path, help='Explicit optional existing Modern engine.log')
    parser.add_argument('--output', type=Path, help='Explicit optional JSON report destination')
    args = parser.parse_args()
    try:
        if args.output:
            for source in (args.path, args.engine_log):
                if source is not None and (args.output.resolve() == source.resolve() or
                                           (args.output.exists() and source.exists() and args.output.samefile(source))):
                    raise ValueError('Output must not replace either input file')
        text = json.dumps(review(args.path, args.engine_log), ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(text, encoding='utf-8')
        else:
            print(text, end='')
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
