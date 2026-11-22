#pragma once
// Optional, bounded diagnostic storage. Initialize outside the loader lock.
// Publishers only write an existing mapped view: no file calls, clocks, heap,
// formatting, worker, sleep, or spin wait. Windows owns process-exit cleanup.
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <intrin.h>

namespace zhdiag {
constexpr uint32_t Magic = 0x3150535a; // ZSP1
constexpr uint32_t Version = 1;
constexpr uint32_t FileBytes = 65536;
constexpr uint32_t KindCount = 8;
constexpr uint32_t RecordBytes = 64;
constexpr uint32_t RecordCount = 1016;
constexpr uint32_t SamplingStride = 16; // Producer policy; Publish itself does not sample.
constexpr uint32_t CaptureBuildTag = 0x00020a02;

enum class InitStatus : DWORD {
    NotAttempted = 0, Active = 1, Disabled = 2, ModulePath = 3,
    ProcessIdentity = 4, Clock = 5, FileOpen = 6, ForeignFile = 7,
    FileSize = 8, FileMapping = 9, MappingView = 10
};

#pragma pack(push, 8)
struct EventCounter {
    volatile LONG low, high;
};
struct Header {
    uint32_t magic, version, header_bytes, file_bytes;
    uint32_t record_bytes, record_count, kind_count, pid;
    uint64_t creation_filetime, qpc_frequency, initialized_qpc, initialized_utc_filetime;
    uint64_t published;
    EventCounter dropped, invalid;
    uint64_t overwritten;
    volatile LONG gate;
    volatile uint32_t sequence;
    volatile LONG detached;
    uint32_t status, next_slot, reserved[3];
};
struct Bucket {
    volatile uint32_t sequence;
    uint32_t reserved;
    uint64_t count, total_ticks, max_ticks, last_begin, last_end;
};
struct Record {
    volatile uint32_t sequence;
    uint32_t kind;
    uint64_t serial, begin, end;
    uint32_t tid, aux0, aux1, reserved;
    uint64_t reserved2, commit_serial;
};
struct Storage {
    Header header;
    Bucket buckets[KindCount];
    Record records[RecordCount];
};
#pragma pack(pop)
static_assert(sizeof(Header) == 128 && offsetof(Header, dropped) == 72, "capture header ABI");
static_assert(sizeof(Bucket) == 48, "capture bucket ABI");
static_assert(sizeof(Record) == RecordBytes && offsetof(Record, commit_serial) == 56, "capture event ABI");
static_assert(offsetof(Storage, records) == 512 && sizeof(Storage) == FileBytes, "capture file ABI");

inline Storage* volatile channel = nullptr;
inline HANDLE mapping = nullptr, file = INVALID_HANDLE_VALUE;
inline InitStatus initStatus = InitStatus::NotAttempted;
inline DWORD initError = ERROR_SUCCESS;

inline bool Enabled() { return channel != nullptr; }
inline uint64_t Frequency() { auto* s = channel; return s ? s->header.qpc_frequency : 0; }
inline InitStatus Status() { return initStatus; }
inline DWORD Error() { return initError; }

// x86 64-bit fetch-add can retry under contention. Each operation below is a
// single 32-bit atomic; the high word changes only once per 2^32 increments.
// On-disk little-endian layout remains a uint64. Final post-exit reads are exact.
inline void IncrementCounter(EventCounter& counter) {
    if (static_cast<uint32_t>(InterlockedIncrement(&counter.low)) == 0)
        InterlockedIncrement(&counter.high);
}
inline uint64_t CounterValue(const EventCounter& counter) {
    return (uint64_t(static_cast<uint32_t>(counter.high)) << 32) |
           static_cast<uint32_t>(counter.low);
}

inline bool Fail(InitStatus status, DWORD error) {
    initStatus = status; initError = error;
    if (mapping) { CloseHandle(mapping); mapping = nullptr; }
    if (file != INVALID_HANDLE_VALUE) { CloseHandle(file); file = INVALID_HANDLE_VALUE; }
    return false;
}

// The caller invokes this once, outside DllMain/loader lock. Disabled by default.
inline bool Initialize(HMODULE module) {
    if (channel) return true;
    wchar_t path[MAX_PATH] = {};
    DWORD length = GetModuleFileNameW(module, path, _countof(path));
    if (!length || length >= _countof(path)) return Fail(InitStatus::ModulePath, ERROR_BAD_PATHNAME);
    wchar_t* leaf = wcsrchr(path, L'\\');
    if (!leaf) return Fail(InitStatus::ModulePath, ERROR_BAD_PATHNAME);
    ++leaf;
    const size_t room = _countof(path) - static_cast<size_t>(leaf - path);
    if (wcscpy_s(leaf, room, L"PrototypeZh.Performance.ini"))
        return Fail(InitStatus::ModulePath, ERROR_BUFFER_OVERFLOW);
    if (GetPrivateProfileIntW(L"Capture", L"Enabled", 0, path) != 1) {
        initStatus = InitStatus::Disabled; initError = ERROR_SUCCESS; return false;
    }
    FILETIME born = {}, exited = {}, kernel = {}, user = {}, utc = {};
    LARGE_INTEGER frequency = {}, now = {};
    if (!GetProcessTimes(GetCurrentProcess(), &born, &exited, &kernel, &user))
        return Fail(InitStatus::ProcessIdentity, GetLastError());
    if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0 || !QueryPerformanceCounter(&now))
        return Fail(InitStatus::Clock, ERROR_INVALID_DATA);
    GetSystemTimeAsFileTime(&utc);
    if (wcscpy_s(leaf, room, L"PrototypeZh.Performance.bin"))
        return Fail(InitStatus::ModulePath, ERROR_BUFFER_OVERFLOW);
    file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                       OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return Fail(InitStatus::FileOpen, GetLastError());
    const bool existing = GetLastError() == ERROR_ALREADY_EXISTS;
    if (existing) {
        DWORD prior[4] = {}, read = 0;
        if (!ReadFile(file, prior, sizeof(prior), &read, nullptr) ||
            read != sizeof(prior) || prior[0] != Magic || prior[1] != Version ||
            prior[2] != sizeof(Header) || prior[3] != FileBytes)
            return Fail(InitStatus::ForeignFile, ERROR_FILE_EXISTS);
    }
    LARGE_INTEGER size = {}; size.QuadPart = FileBytes;
    if (!SetFilePointerEx(file, size, nullptr, FILE_BEGIN) || !SetEndOfFile(file))
        return Fail(InitStatus::FileSize, GetLastError());
    mapping = CreateFileMappingW(file, nullptr, PAGE_READWRITE, 0, FileBytes, nullptr);
    if (!mapping) return Fail(InitStatus::FileMapping, GetLastError());
    auto* view = static_cast<Storage*>(MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, FileBytes));
    if (!view) return Fail(InitStatus::MappingView, GetLastError());
    memset(view, 0, FileBytes);
    auto& h = view->header;
    h.version = Version; h.header_bytes = sizeof(Header); h.file_bytes = FileBytes;
    h.record_bytes = RecordBytes; h.record_count = RecordCount; h.kind_count = KindCount;
    h.pid = GetCurrentProcessId();
    h.creation_filetime = (uint64_t(born.dwHighDateTime) << 32) | born.dwLowDateTime;
    h.qpc_frequency = static_cast<uint64_t>(frequency.QuadPart);
    h.initialized_qpc = static_cast<uint64_t>(now.QuadPart);
    h.initialized_utc_filetime = (uint64_t(utc.dwHighDateTime) << 32) | utc.dwLowDateTime;
    h.status = static_cast<uint32_t>(InitStatus::Active);
    h.reserved[0] = SamplingStride; h.reserved[1] = CaptureBuildTag;
    InterlockedExchange(reinterpret_cast<volatile LONG*>(&h.magic), static_cast<LONG>(Magic));
    InterlockedExchangePointer(reinterpret_cast<PVOID volatile*>(&channel), view);
    initStatus = InitStatus::Active; initError = ERROR_SUCCESS;
    return true;
}

inline void Publish(uint32_t kind, uint64_t begin, uint64_t end, uint32_t aux0, uint32_t aux1,
                    uint32_t context = 0, uint64_t detail = 0) {
    auto* s = channel;
    if (!s) return;
    auto& h = s->header;
    if (!kind || kind > KindCount || end < begin) { IncrementCounter(h.invalid); return; }
    // Never wait on a gameplay/render thread. Report contention loss explicitly.
    if (InterlockedCompareExchange(&h.gate, 1, 0) != 0) { IncrementCounter(h.dropped); return; }
    ++h.sequence;
    _ReadWriteBarrier();
    auto& b = s->buckets[kind - 1];
    ++b.sequence;
    _ReadWriteBarrier();
    const uint64_t elapsed = end - begin;
    ++b.count; b.total_ticks += elapsed;
    if (elapsed > b.max_ticks) b.max_ticks = elapsed;
    b.last_begin = begin; b.last_end = end;
    _ReadWriteBarrier();
    ++b.sequence;

    auto& r = s->records[h.next_slot];
    ++r.sequence;
    _ReadWriteBarrier();
    r.kind = kind; r.serial = h.published + 1;
    r.begin = begin; r.end = end; r.tid = GetCurrentThreadId();
    r.aux0 = aux0; r.aux1 = aux1; r.reserved = context; r.reserved2 = detail;
    r.commit_serial = r.serial;
    _ReadWriteBarrier();
    ++r.sequence;
    ++h.published;
    if (h.published > RecordCount) ++h.overwritten;
    if (++h.next_slot == RecordCount) h.next_slot = 0;
    _ReadWriteBarrier();
    ++h.sequence;
    InterlockedExchange(&h.gate, 0);
}

// Allowed during process detach: one memory write, no file flush, lock or wait.
// A forced termination can omit this marker; the decoder must not invent it.
inline void MarkDetach() {
    auto* s = channel;
    if (s) InterlockedExchange(&s->header.detached, 1);
}

#ifdef ZH_CAPTURE_TESTING
// Offline harness only, after its publisher threads have joined.
inline void CloseForTest() {
    auto* s = channel; channel = nullptr;
    if (s) { FlushViewOfFile(s, FileBytes); UnmapViewOfFile(s); }
    if (mapping) { CloseHandle(mapping); mapping = nullptr; }
    if (file != INVALID_HANDLE_VALUE) { CloseHandle(file); file = INVALID_HANDLE_VALUE; }
    initStatus = InitStatus::NotAttempted; initError = ERROR_SUCCESS;
}
#endif
}
