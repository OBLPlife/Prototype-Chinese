#pragma once
#include <windows.h>
#include <stdint.h>
#include <string.h>

// Keep the game's GFx allocation, reallocation, cache and free implementations.
// Their allocator-ID field selects the engine's existing CRT-backed system heap
// instead of its fixed 7.25 MiB Front End subheap. No new allocator is introduced.
// Evidence: work/PrototypeZh/pause-recurrence-20261113-2146/native-audit.
enum class ZhHeapStatus : DWORD {
    NotLoaded=0, Applied=1, EngineUnavailable=2, ImageMismatch=3,
    ConstructorMismatch=4, ProtectionFailed=5
};
constexpr DWORD ZhConstructorRva=0x9615c0;
constexpr DWORD ZhHeapIdRva=0x9615d7;

static ZhHeapStatus ApplyNativeTextHeap(BYTE* engine) {
    if (!engine) return ZhHeapStatus::EngineUnavailable;
    auto dos=reinterpret_cast<IMAGE_DOS_HEADER*>(engine);
    if (dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<0 || dos->e_lfanew>0x1000)
        return ZhHeapStatus::ImageMismatch;
    auto pe=reinterpret_cast<IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if (pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386 ||
        pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC || pe->OptionalHeader.SizeOfImage<0xe8d918)
        return ZhHeapStatus::ImageMismatch;
    const BYTE original[]={0x8b,0xc1,0x8d,0x48,0x0c,0xc7,0x00,0x14,0xd9,0xe8,0x10,
        0x89,0x49,0x20,0x8d,0x48,0x30,0x89,0x49,0x20,0xc7,0x40,0x04,0x72,0x00,
        0x00,0x00,0xc6,0x40,0x08,0x00,0xc3};
    BYTE expected[sizeof(original)]; memcpy(expected,original,sizeof(expected));
    const uintptr_t vtable=reinterpret_cast<uintptr_t>(engine)+0xe8d914;
    memcpy(expected+7,&vtable,sizeof(vtable));
    BYTE* constructor=engine+ZhConstructorRva;
    if (memcmp(constructor,expected,sizeof(expected))) return ZhHeapStatus::ConstructorMismatch;
    DWORD previous;
    if (!VirtualProtect(engine+ZhHeapIdRva,1,PAGE_EXECUTE_READWRITE,&previous))
        return ZhHeapStatus::ProtectionFailed;
    engine[ZhHeapIdRva]=0;
    FlushInstructionCache(GetCurrentProcess(),engine+ZhHeapIdRva,1);
    DWORD ignored;
    VirtualProtect(engine+ZhHeapIdRva,1,previous,&ignored);
    return ZhHeapStatus::Applied;
}
