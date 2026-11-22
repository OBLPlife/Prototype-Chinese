#pragma once
#include <windows.h>
#include <stdint.h>
#include <string.h>

// Candidate for the two localization font assets only. All allocation/free
// implementations, GFX ownership flags, cached resources and other files remain
// in the original engine. Install before the engine starts its loader threads.
enum class ZhFontBufferStatus : DWORD {
    Applied=1, EngineUnavailable=2, ImageMismatch=3,
    SignatureMismatch=4, ProtectionFailed=5
};
constexpr DWORD ZhFontAllocCallRva=0x95c6d4;
constexpr DWORD ZhFontFreeCallRva=0x95c799;
static void* (__cdecl *ZhFontNativeAlloc)(unsigned,unsigned,unsigned);
static void (__cdecl *ZhFontNativeFree)(unsigned,void*);

static bool ZhFontPathEqual(const char* path,const char* target) {
    if(!path)return false;
    if(*path=='\\'||*path=='/')++path;
    for(;;++path,++target) {
        char a=*path,b=*target;
        if(a=='/')a='\\';
        if(a>='A'&&a<='Z')a=static_cast<char>(a-'A'+'a');
        if(a!=b)return false;
        if(!a)return true;
    }
}
static bool ZhOwnFontAdapter(const BYTE* object) {
    const char* path=*reinterpret_cast<const char* const*>(object+0x10);
    return ZhFontPathEqual(path,"art\\hud\\fonts_latin.gfx") ||
           ZhFontPathEqual(path,"art\\hud\\gfxfontlib.gfx");
}
static void* __cdecl ZhFontAllocDispatch(unsigned heap,unsigned bytes,unsigned alignment,const BYTE* object) {
    return ZhFontNativeAlloc(heap==1&&ZhOwnFontAdapter(object)?0:heap,bytes,alignment);
}
static void __cdecl ZhFontFreeDispatch(unsigned heap,void* pointer,const BYTE* object) {
    ZhFontNativeFree(heap==1&&ZhOwnFontAdapter(object)?0:heap,pointer);
}
// The original call sites have ESI = adapter, and cdecl arguments on stack.
// Relay an extra immutable adapter pointer without changing caller stack size.
static __declspec(naked) void ZhFontAllocRelay() {
    __asm {
        push esi
        push dword ptr [esp+16]
        push dword ptr [esp+16]
        push dword ptr [esp+16]
        call ZhFontAllocDispatch
        add esp,16
        ret
    }
}
static __declspec(naked) void ZhFontFreeRelay() {
    __asm {
        push esi
        push dword ptr [esp+12]
        push dword ptr [esp+12]
        call ZhFontFreeDispatch
        add esp,12
        ret
    }
}
static ZhFontBufferStatus ApplyNativeFontBuffers(BYTE* engine) {
    if(!engine)return ZhFontBufferStatus::EngineUnavailable;
    auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(engine);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<0||dos->e_lfanew>0x1000)
        return ZhFontBufferStatus::ImageMismatch;
    auto pe=reinterpret_cast<const IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if(pe->Signature!=IMAGE_NT_SIGNATURE||pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC||pe->OptionalHeader.SizeOfImage<0x95c7b6)
        return ZhFontBufferStatus::ImageMismatch;
    const BYTE allocate[]={0x6a,0x10,0x50,0x6a,0x01,0x89,0x07,0xe8,0xf7,0xe1,0xcd,0xff,
        0x8b,0x3f,0x8b,0x4c,0x24,0x20,0x83,0xc4,0x0c};
    const BYTE expectedRelease[]={0x8b,0x4e,0x18,0x51,0x6a,0x01,0xe8,0x22,0xe2,0xcd,0xff,
        0x83,0xc4,0x08,0x33,0xc0,0x89,0x46,0x18};
    if(memcmp(engine+0x95c6cd,allocate,sizeof(allocate))||memcmp(engine+0x95c793,expectedRelease,sizeof(expectedRelease)))
        return ZhFontBufferStatus::SignatureMismatch;
    DWORD protection;
    if(!VirtualProtect(engine+0x95c6cd,0xdf,PAGE_EXECUTE_READWRITE,&protection))
        return ZhFontBufferStatus::ProtectionFailed;
    ZhFontNativeAlloc=reinterpret_cast<decltype(ZhFontNativeAlloc)>(engine+0x63a8d0);
    ZhFontNativeFree=reinterpret_cast<decltype(ZhFontNativeFree)>(engine+0x63a9c0);
    const uintptr_t targets[]={reinterpret_cast<uintptr_t>(&ZhFontAllocRelay),reinterpret_cast<uintptr_t>(&ZhFontFreeRelay)};
    const DWORD sites[]={ZhFontAllocCallRva,ZhFontFreeCallRva};
    for(unsigned i=0;i<2;++i) {
        const DWORD displacement=static_cast<DWORD>(targets[i]-reinterpret_cast<uintptr_t>(engine+sites[i]+5));
        memcpy(engine+sites[i]+1,&displacement,4);
    }
    FlushInstructionCache(GetCurrentProcess(),engine+0x95c6cd,0xdf);
    DWORD ignored;VirtualProtect(engine+0x95c6cd,0xdf,protection,&ignored);
    return ZhFontBufferStatus::Applied;
}
