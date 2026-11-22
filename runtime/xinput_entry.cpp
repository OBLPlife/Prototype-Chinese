// A game-local load entry for Chinese UI memory support. All XInput exports
// tail-call the unmodified Windows XInput 1.3 DLL from the absolute system path.
// No controller state, arguments, return values, timing or audio are transformed.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "native_heap.h"
#include "native_font_buffers.h"
#include "native_font_lookup.h"
#include "native_font_kerning.h"
#include "native_subtitles.h"

static HMODULE ownModule;
static ZhHeapStatus heapStatus=ZhHeapStatus::NotLoaded;
static ZhFontBufferStatus fontBufferStatus=ZhFontBufferStatus::EngineUnavailable;
static ZhCompactLookupStatus compactLookupStatus=ZhCompactLookupStatus::EngineUnavailable;
static ZhCompactKerningStatus compactKerningStatus=ZhCompactKerningStatus::EngineUnavailable;
static ZhSubtitleStatus subtitleStatus=ZhSubtitleStatus::EngineUnavailable;
static zhcapture::Status captureStatus=zhcapture::Status::EngineUnavailable;
static INIT_ONCE systemOnce=INIT_ONCE_STATIC_INIT;
static FARPROC systemExports[12];
static const WORD ordinals[]={1,2,3,4,5,6,7,8,100,101,102,103};

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetHeapStatus() {
    return static_cast<DWORD>(heapStatus);
}

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetFontBufferStatus() {
    return static_cast<DWORD>(fontBufferStatus);
}

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetCompactLookupStatus() {
    return static_cast<DWORD>(compactLookupStatus);
}

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetCompactKerningStatus() {
    return static_cast<DWORD>(compactKerningStatus);
}

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetSubtitleStatus() {
    return static_cast<DWORD>(subtitleStatus);
}

extern "C" __declspec(dllexport) DWORD __cdecl PrototypeZh_GetSubtitleCaptureStatus() {
    return static_cast<DWORD>(captureStatus);
}

static void WriteSupportLog(DWORD error) {
    wchar_t path[MAX_PATH];
    DWORD n=GetModuleFileNameW(ownModule,path,_countof(path));
    if (!n || n>=_countof(path)) return;
    wchar_t* leaf=wcsrchr(path,L'\\'); if(!leaf) return;
    *++leaf=0;
    if (wcscat_s(path,L"PrototypeZh.Runtime.log")) return;
    HANDLE file=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if (file==INVALID_HANDLE_VALUE) return;
    char line[1536];
    int length=sprintf_s(line,"PrototypeZh native text support 0.2.10-capture-r2\r\n"
        "pid=%lu heap_status=%lu (1=applied) ctor_rva=009615c0 heap_id_rva=009615d7 old=114 new=0\r\n"
        "font_buffer_status=%lu (1=applied) alloc_call=0095c6d4 free_call=0095c799 old=1 new=0\r\n"
        "compact_lookup_status=%lu (1=applied) vtable_slot=00e8fc40 original=009ad260\r\n"
        "compact_kerning_status=%lu (1=applied) vtable_slot=00e8fc58 original=009ad2d0\r\n"
        "subtitle_status=%lu (1=applied) update_call=008649df objective_call=004d1954 independent_expiry=1 objective_refresh=1\r\n"
        "subtitle_capture_status=%lu (1=applied) enabled=%u storage_status=%lu storage_error=%lu gfx_call=008857f4 file=PrototypeZh.Performance.bin ordinary_sample=1/16 text_visibility=all lifecycle=on gpu_exclusive=unavailable\r\n"
        "Native GFx heap selector, paired font buffers and verified glyph/kerning probes. Engine files and Modern module are unchanged.\r\n"
        "XInput forwarded to the absolute system DLL; resolver_error=%lu\r\n",
        GetCurrentProcessId(),static_cast<DWORD>(heapStatus),static_cast<DWORD>(fontBufferStatus),
        static_cast<DWORD>(compactLookupStatus),static_cast<DWORD>(compactKerningStatus),static_cast<DWORD>(subtitleStatus),
        static_cast<DWORD>(captureStatus),zhdiag::Enabled()?1u:0u,static_cast<DWORD>(zhdiag::Status()),zhdiag::Error(),error);
    DWORD written;
    if(length>0) WriteFile(file,line,static_cast<DWORD>(length),&written,nullptr);
    CloseHandle(file);
}

static BOOL CALLBACK ResolveSystem(PINIT_ONCE,PVOID,PVOID*) {
    // The normal first XInput call is outside the loader lock. Diagnostics file
    // setup occurs here once; optional failure must not disable localization.
    if(captureStatus==zhcapture::Status::Applied)zhdiag::Initialize(ownModule);
    wchar_t path[MAX_PATH];
    UINT n=GetSystemDirectoryW(path,_countof(path));
    if (!n || n>=_countof(path)-15) {WriteSupportLog(ERROR_BAD_PATHNAME);return FALSE;}
    if (wcscat_s(path,L"\\XInput1_3.dll")) {WriteSupportLog(ERROR_BAD_PATHNAME);return FALSE;}
    HMODULE system=LoadLibraryExW(path,nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!system || system==ownModule) {WriteSupportLog(system?ERROR_BAD_EXE_FORMAT:GetLastError());return FALSE;}
    FARPROC resolved[12];
    for (unsigned i=0;i<_countof(ordinals);++i) {
        resolved[i]=GetProcAddress(system,MAKEINTRESOURCEA(ordinals[i]));
        if (!resolved[i]) {WriteSupportLog(GetLastError());FreeLibrary(system);return FALSE;}
    }
    // Keep the native DLL loaded for the process lifetime, matching a static import.
    memcpy(systemExports,resolved,sizeof(resolved));
    WriteSupportLog(ERROR_SUCCESS);
    return TRUE;
}

extern "C" void __cdecl ZhResolveSystem() {
    if (!InitOnceExecuteOnce(&systemOnce,ResolveSystem,nullptr,nullptr)) {
        // Equivalent to an unresolved static dependency; do not fabricate input
        // success or silently call an incompatible function signature.
        RaiseException(0xc0000139,EXCEPTION_NONCONTINUABLE,0,nullptr);
    }
}

// Preserve the complete original argument stack and volatile/nonvolatile integer
// registers. Even ordinal-only exports retain their actual Windows ABI.
#define ZH_FORWARD(index) extern "C" __declspec(naked) void ZhForward##index() { \
    __asm { pushfd } \
    __asm { cmp dword ptr [systemExports+index*4],0 } \
    __asm { jne ready } \
    __asm { pushad } \
    __asm { call ZhResolveSystem } \
    __asm { popad } \
    __asm { ready: popfd } \
    __asm { jmp dword ptr [systemExports+index*4] } \
}
ZH_FORWARD(0) ZH_FORWARD(1) ZH_FORWARD(2) ZH_FORWARD(3)
ZH_FORWARD(4) ZH_FORWARD(5) ZH_FORWARD(6) ZH_FORWARD(7)
ZH_FORWARD(8) ZH_FORWARD(9) ZH_FORWARD(10) ZH_FORWARD(11)

BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_DETACH){zhdiag::MarkDetach();return TRUE;}
    if (reason!=DLL_PROCESS_ATTACH) return TRUE;
    ownModule=instance;
    // XInput is an engine import: the parent image is already mapped, before
    // any GFx allocator is constructed. No library load, file I/O or worker
    // thread is started while the Windows loader lock is held.
    BYTE* engine=reinterpret_cast<BYTE*>(GetModuleHandleW(L"prototypeenginef.dll"));
    heapStatus=ApplyNativeTextHeap(engine);
    fontBufferStatus=ApplyNativeFontBuffers(engine);
    compactLookupStatus=ApplyNativeCompactLookup(engine);
    compactKerningStatus=ApplyNativeCompactKerning(engine);
    subtitleStatus=ApplyNativeSubtitles(engine);
    captureStatus=zhcapture::Apply(engine);
    return TRUE;
}
