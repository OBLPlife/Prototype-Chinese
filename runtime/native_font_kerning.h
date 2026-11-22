#pragma once
#include <windows.h>
#include <stdint.h>
#include <string.h>

using ZhOriginalCompactKerning=float(__thiscall*)(void*,unsigned,unsigned);
static ZhOriginalCompactKerning ZhCompactOriginalKerning;

static float __fastcall ZhKerningNonLatin(void* object,void*,unsigned first,unsigned second) {
    // Preserve the native 32-bit comparison contract (unlike glyph lookup,
    // kerning does not truncate its arguments to ushort). Latin pairs keep
    // their original path. A sorted table cannot contain a first code beyond
    // its last record; this remains valid for fonts with non-Latin kerning.
    const BYTE* font=static_cast<const BYTE*>(object);
    if(*reinterpret_cast<const unsigned*>(font+0x64)!=0) {
        const unsigned count=*reinterpret_cast<const unsigned*>(font+0x4c);
        if(count && count<0x80000000u) {
            const BYTE* vector=*reinterpret_cast<const BYTE* const*>(font+0x40);
            const BYTE* data=*reinterpret_cast<const BYTE* const*>(vector+8);
            const unsigned offset=*reinterpret_cast<const unsigned*>(font+0x50);
            const BYTE* end=data+offset+(count-1)*6;
            unsigned short last;
            memcpy(&last,end,sizeof(last));
            if(first>last)return 0.0f;
            // The original subtitle font ends with two Latin ligature pairs.
            // Predict that gap, then prove it using adjacent actual records.
            // This cannot skip a pair even when another font has CJK kerning.
            if(count>=3) {
                unsigned short lower,upper;
                memcpy(&lower,end-12,2);memcpy(&upper,end-6,2);
                if(first>lower && first<upper)return 0.0f;
            }
        }
    }
    return ZhCompactOriginalKerning(object,first,second);
}

// Tail dispatch keeps the original Latin path's stack and x87 return ABI.
// Avoid entering a compiler-generated forwarding frame for every Latin pair.
static __declspec(naked) float __fastcall ZhKerningOutsideTable(void*,void*,unsigned,unsigned) {
    __asm { cmp dword ptr [esp+4],0xff }
    __asm { jbe native }
    __asm { jmp ZhKerningNonLatin }
    __asm { native: jmp dword ptr [ZhCompactOriginalKerning] }
}

enum class ZhCompactKerningStatus : DWORD {
    Applied=1, EngineUnavailable=2, ImageMismatch=3, SignatureMismatch=4, ProtectionFailed=5
};
constexpr DWORD ZhKerningSlotRva=0xe8fc58;
constexpr DWORD ZhKerningWrapperRva=0x9ad2d0;
constexpr DWORD ZhKerningSearchRva=0x9ab770;

static ZhCompactKerningStatus ApplyNativeCompactKerning(BYTE* engine) {
    if(!engine)return ZhCompactKerningStatus::EngineUnavailable;
    auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(engine);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<0||dos->e_lfanew>0x1000)
        return ZhCompactKerningStatus::ImageMismatch;
    auto pe=reinterpret_cast<const IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if(pe->Signature!=IMAGE_NT_SIGNATURE||pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC||pe->OptionalHeader.SizeOfImage<ZhKerningSlotRva+4)
        return ZhCompactKerningStatus::ImageMismatch;
    BYTE wrapper[]={0x8b,0x44,0x24,0x08,0x56,0x8b,0xf1,0x8b,0x4c,0x24,0x08,0x50,0x51,0x8d,0x4e,0x30,
        0xe8,0x8b,0xe4,0xff,0xff,0xd8,0x0d,0xf8,0xfd,0xe1,0x10,0x8b,0x56,0x64,0xdb,0x46,
        0x64,0x85,0xd2,0x7d,0x06,0xd8,0x05,0xf0,0x09,0xde,0x10,0xde,0xf9,0x5e,0xc2,0x08,0x00};
    const DWORD scale=reinterpret_cast<DWORD>(engine+0xe1fdf8),unsignedBias=reinterpret_cast<DWORD>(engine+0xde09f0);
    memcpy(wrapper+23,&scale,4);memcpy(wrapper+39,&unsignedBias,4);
    const BYTE search[]={0x83,0xec,0x0c,0x53,0x8b,0x59,0x1c,0x83,0xeb,0x01,0x55,0x56,0xb8,0x00,0x00,0x00,
        0x00,0x57,0x89,0x4c,0x24,0x14,0x89,0x44,0x24,0x10,0x78,0x72,0x8b,0x51,0x20,0x89,
        0x54,0x24,0x18,0x8b,0x51,0x10,0x8b,0x6a,0x08,0xeb,0x09,0xeb,0x03,0x8d,0x49,0x00,
        0x8b,0x4c,0x24,0x14,0x8b,0x49,0x10,0x8b,0x49,0x08,0x8b,0x74,0x24,0x18,0x03,0xc3,
        0x99,0x2b,0xc2,0xd1,0xf8,0x8d,0x14,0x40,0x8d,0x14,0x56,0x8d,0x34,0x11,0x33,0xc9,
        0x8a,0x6e,0x01,0x8a,0x0e,0x8b,0xf1,0x33,0xc9,0x8a,0x6c,0x2a,0x03,0x8a,0x4c,0x2a,
        0x02,0x8b,0xf9,0x8b,0x4c,0x24,0x20,0x3b,0xce,0x75,0x08,0x8b,0x4c,0x24,0x24,0x3b,
        0xcf,0x74,0x27,0x0f,0x92,0xc1,0x84,0xc9,0x74,0x09,0x8d,0x58,0xff,0x8b,0x44,0x24,
        0x10,0xeb,0x07,0x83,0xc0,0x01,0x89,0x44,0x24,0x10,0x3b,0xc3,0x7e,0xa2,0xd9,0xee,
        0x5f,0x5e,0x5d,0x5b,0x83,0xc4,0x0c,0xc2,0x08,0x00,0x8b,0x44,0x24,0x14,0x8b,0x48,
        0x10,0x8b,0x41,0x08,0x8d,0x44,0x10,0x04,0x33,0xc9,0x8a,0x68,0x01,0x5f,0x5e,0x5d,
        0x5b,0x8a,0x08,0x0f,0xbf,0xd1,0x89,0x54,0x24,0x10,0xdb,0x44,0x24,0x10,0x83,0xc4,
        0x0c,0xc2,0x08,0x00};
    if(memcmp(engine+ZhKerningWrapperRva,wrapper,sizeof(wrapper))||
       memcmp(engine+ZhKerningSearchRva,search,sizeof(search))||
       *reinterpret_cast<void**>(engine+ZhKerningSlotRva)!=engine+ZhKerningWrapperRva)
        return ZhCompactKerningStatus::SignatureMismatch;
    DWORD protection;
    if(!VirtualProtect(engine+ZhKerningSlotRva,4,PAGE_READWRITE,&protection))
        return ZhCompactKerningStatus::ProtectionFailed;
    ZhCompactOriginalKerning=reinterpret_cast<ZhOriginalCompactKerning>(engine+ZhKerningWrapperRva);
    *reinterpret_cast<void**>(engine+ZhKerningSlotRva)=reinterpret_cast<void*>(&ZhKerningOutsideTable);
    DWORD ignored;VirtualProtect(engine+ZhKerningSlotRva,4,protection,&ignored);
    return ZhCompactKerningStatus::Applied;
}
