"""Optional subtitle diagnostics contract; unrelated patch files are not owned."""
CAPTURE_SUPPORT = dict(call_rva=0x8857f4, original_invoke_rva=0x964140,
    config='PrototypeZh.Performance.ini', file='PrototypeZh.Performance.bin',
    file_bytes=65536, user_limit_bytes=1000000, ordinary_sample_stride=16,
    objective_events_always_sampled=True, background_threads=0, per_event_file_calls=0,
    gpu_queries_added=0, gpu_exclusive_time_available=False, modern_dependency=False,
    code_guard_failure_disables_diagnostics_only=True)
SIGNATURES = [(0x8857b0,0x69,0x19c34954,[2,0x52]),
              (0x964140,0x64,0x5c9f1019,[])]
