#pragma once
#include <windows.h>
#include <stdint.h>
#include <string.h>

// Predict an index in the existing compact-font table, then verify the code.
// Failed predictions use the untouched native binary search. No allocation,
// cache, lock or change to the font object's ownership/lifetime is needed.
using ZhOriginalCompactLookup=int(__thiscall*)(void*,unsigned);
static ZhOriginalCompactLookup ZhCompactOriginalLookup;
constexpr unsigned ZhHanFirst=0x4e00, ZhHanCount=0x9fa6-0x4e00, ZhGbkTail=173;

static const BYTE* ZhCompactEntries(const BYTE* font) {
    const BYTE* vector=*reinterpret_cast<const BYTE* const*>(font+0x40);
    return *reinterpret_cast<const BYTE* const*>(vector+8)+*reinterpret_cast<const unsigned*>(font+0x48);
}
static bool ZhCompactCodeEquals(const BYTE* entries,unsigned index,unsigned code) {
    unsigned short have;
    memcpy(&have,entries+index*8,sizeof(have));
    return have==code;
}
static int __fastcall ZhLookupGbkAscii(void* object,void*,unsigned input) {
    // The original function reads a ushort, including for nonzero upper bits.
    const unsigned code=static_cast<unsigned short>(input);
    const BYTE* font=static_cast<const BYTE*>(object);
    const unsigned hanOffset=code-ZhHanFirst;
    if(hanOffset<ZhHanCount) {
        const unsigned count=*reinterpret_cast<const unsigned*>(font+0x44);
        // The current GBK fonts have 173 codes after U+9FA5. This is only a
        // prediction: even a different font must pass the bounds/code checks.
        const unsigned index=count-(ZhHanCount+ZhGbkTail)+hanOffset;
        if(count<=65536u && index<count && ZhCompactCodeEquals(ZhCompactEntries(font),index,code))
            return static_cast<int>(index);
    }else if(code-0x20u<0x5fu) {
        const unsigned count=*reinterpret_cast<const unsigned*>(font+0x44);
        if(count && count<=65536u) {
            const BYTE* entries=ZhCompactEntries(font);
            unsigned short first;memcpy(&first,entries,sizeof(first));
            const unsigned index=code-first;
            if(index<count && ZhCompactCodeEquals(entries,index,code))
                return static_cast<int>(index);
        }
    }
    return ZhCompactOriginalLookup(object,input);
}

enum class ZhCompactLookupStatus : DWORD {
    Applied=1, EngineUnavailable=2, ImageMismatch=3, SignatureMismatch=4, ProtectionFailed=5
};
constexpr DWORD ZhCompactVtableSlotRva=0xe8fc40;
constexpr DWORD ZhCompactWrapperRva=0x9ad260;
constexpr DWORD ZhCompactSearchRva=0x9ab6d0;

static ZhCompactLookupStatus ApplyNativeCompactLookup(BYTE* engine) {
    if(!engine)return ZhCompactLookupStatus::EngineUnavailable;
    auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(engine);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<0||dos->e_lfanew>0x1000)
        return ZhCompactLookupStatus::ImageMismatch;
    auto pe=reinterpret_cast<const IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if(pe->Signature!=IMAGE_NT_SIGNATURE||pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC||pe->OptionalHeader.SizeOfImage<ZhCompactVtableSlotRva+4)
        return ZhCompactLookupStatus::ImageMismatch;
    const BYTE wrapper[]={0x83,0xc1,0x30,0xe9,0x68,0xe4,0xff,0xff};
    const BYTE search[]={0x51,0x53,0x55,0x56,0x57,0x8b,0x79,0x14,0x83,0xef,0x01,0xbd,0x00,0x00,0x00,0x00,
        0x78,0x3e,0x8b,0x41,0x18,0x8b,0x49,0x10,0x8b,0x71,0x08,0x0f,0xb7,0x5c,0x24,0x18,
        0x89,0x44,0x24,0x10,0x8d,0x04,0x2f,0x99,0x2b,0xc2,0x8b,0x54,0x24,0x10,0xd1,0xf8,
        0x8d,0x0c,0xc2,0x33,0xd2,0x8a,0x74,0x0e,0x01,0x8a,0x14,0x0e,0x8b,0xca,0x3b,0xd9,
        0x74,0x11,0x73,0x05,0x8d,0x78,0xff,0xeb,0x03,0x8d,0x68,0x01,0x3b,0xef,0x7e,0xd4,
        0x83,0xc8,0xff,0x5f,0x5e,0x5d,0x5b,0x59,0xc2,0x04,0x00};
    if(memcmp(engine+ZhCompactWrapperRva,wrapper,sizeof(wrapper))||
       memcmp(engine+ZhCompactSearchRva,search,sizeof(search))||
       *reinterpret_cast<void**>(engine+ZhCompactVtableSlotRva)!=engine+ZhCompactWrapperRva)
        return ZhCompactLookupStatus::SignatureMismatch;
    DWORD protection;
    if(!VirtualProtect(engine+ZhCompactVtableSlotRva,4,PAGE_READWRITE,&protection))
        return ZhCompactLookupStatus::ProtectionFailed;
    ZhCompactOriginalLookup=reinterpret_cast<ZhOriginalCompactLookup>(engine+ZhCompactWrapperRva);
    *reinterpret_cast<void**>(engine+ZhCompactVtableSlotRva)=reinterpret_cast<void*>(&ZhLookupGbkAscii);
    DWORD ignored;VirtualProtect(engine+ZhCompactVtableSlotRva,4,protection,&ignored);
    return ZhCompactLookupStatus::Applied;
}
