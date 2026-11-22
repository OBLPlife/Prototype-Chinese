#pragma once
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "subtitle_capture.h"

// The original FESubtitle owns these nodes. Keep its allocation, stop-by-id,
// option handling and scene/load/destructor cleanup; change only scheduling.
struct ZhSubtitleNode {
    char text[0x118];
    const char* format;
    uint32_t started, duration, id;
    ZhSubtitleNode* next;
};
struct ZhSubtitleOwner {
    void* vtable;
    void* formats;
    uint32_t formatCount;
    ZhSubtitleNode* head;
    uint32_t count, nextId;
    uint32_t renderedGeneration; // Original update's start-time field, now unused.
    BYTE visible, disabled, suppressed, optionDisabled;
};
static_assert(sizeof(ZhSubtitleNode)==0x12c && offsetof(ZhSubtitleNode,next)==0x128,"native subtitle node");
static_assert(sizeof(ZhSubtitleOwner)==0x20 && offsetof(ZhSubtitleOwner,visible)==0x1c,"native subtitle owner");
struct ZhSubtitleValue {
    uint32_t type, reserved;
    union { double number; const void* string; uint64_t boolean; } data;
};
static_assert(sizeof(ZhSubtitleValue)==16 && offsetof(ZhSubtitleValue,data)==8,"native FE value");

using ZhSubtitleClock=uint32_t(__cdecl*)();
using ZhSubtitleFree=void(__cdecl*)(void*);
using ZhSubtitleFormat=int(__cdecl*)(char*,unsigned,const char*,...);
using ZhSubtitleConvert=int(__cdecl*)(void*,int,const void*,int,int,unsigned,int,void*,void*);
using ZhSubtitleFrontend=void*(__cdecl*)();
using ZhSubtitleInvoke=void(__thiscall*)(void*,const char*,const ZhSubtitleValue*,unsigned);
static ZhSubtitleClock ZhSubtitleNow;
static ZhSubtitleFree ZhSubtitleRelease;
static ZhSubtitleFormat ZhSubtitlePrintf;
static ZhSubtitleConvert ZhSubtitleToWide;
static ZhSubtitleFrontend ZhSubtitleGetFrontend;
static ZhSubtitleInvoke ZhSubtitleInvokeNative;

static ZhSubtitleValue ZhSubtitleString(const void* text,bool wide=false) {
    ZhSubtitleValue v={};v.type=wide?5:4;v.data.string=text;return v;
}
static void ZhSubtitleCall(const char* method,const ZhSubtitleValue* values,unsigned count) {
    // This copies strings into the ORIGINAL FE dispatch queue. Do not access
    // GFx objects from the caller thread or retain pointers into stack buffers.
    ZhSubtitleInvokeNative(ZhSubtitleGetFrontend(),method,values,count);
}
static void ZhSubtitleShow(bool show) {
    ZhSubtitleValue v={};v.type=2;v.data.boolean=show?1:0;
    ZhSubtitleCall("AS_SubtitleShow",&v,1);
}
static void ZhSubtitleSendText(const wchar_t* text,bool append) {
    if(!append) {
        const auto value=ZhSubtitleString(text,true);
        ZhSubtitleCall("AS_SetSubtitles",&value,1);
    } else {
        // Verified GFx extension; keep markup and native dispatch ownership.
        const ZhSubtitleValue values[]={ZhSubtitleString("_global.gSubtitles.subtitleText"),
            ZhSubtitleString("appendHtml"),ZhSubtitleString(text,true)};
        ZhSubtitleCall("AS_CallASFunction",values,3);
    }
}

// Keep conversion buffers off the every-frame stack/probe path.
static __declspec(noinline) void ZhSubtitleRender(ZhSubtitleOwner* owner,bool refreshVisibility,uint32_t now) {
    uint64_t captureBegin=zhcapture::Begin(zhcapture::Submit,refreshVisibility);
    // Since 0.2.10, the owned AS_SetSubtitlePosition always sets autoSize="left".
    // AS_SetSubtitles calls it after updating the text. Avoid the former extra
    // SetVar dispatch for overlapping lines; the original field still grows.
    if(!owner->visible || refreshVisibility){owner->visible=1;ZhSubtitleShow(true);}
    // 2000 UTF-16 units + terminator + appendHtml's two path/name strings
    // fit the ORIGINAL dispatcher's 4092-byte immediate scratch buffer.
    // Normally all active lines use one dispatch. Very large overlaps use
    // bounded append packets; neither truncate text nor grow a persistent cache.
    constexpr unsigned capacity=2000;
    wchar_t packet[capacity+1];unsigned used=0;bool appended=false;
    for(ZhSubtitleNode* node=owner->head;node;node=node->next) {
        zhcapture::Member(zhcapture::SubmittedMember,node->id,now,node->started,node->duration);
        char formatted[1024];
        const char* input=node->text;
        if(node->format) {
            formatted[0]=0;
            ZhSubtitlePrintf(formatted,sizeof(formatted),node->format,node->text);
            formatted[sizeof(formatted)-1]=0;input=formatted;
        }
        const unsigned separator=node==owner->head?0:4;
        // UTF-8 byte count bounds UTF-16 code units. Every original node (or
        // its 1024-byte formatting buffer) individually fits one packet.
        if(used && used+separator+strlen(input)>capacity) {
            ZhSubtitleSendText(packet,appended);appended=true;used=0;
        }
        if(separator){memcpy(packet+used,L"<br>",separator*sizeof(wchar_t));used+=separator;}
        wchar_t* payload=packet+used;payload[0]=0;packet[capacity]=0;
        ZhSubtitleToWide(payload,2,input,1,0,(capacity+1-used)*sizeof(wchar_t),0,nullptr,nullptr);
        if(node->next)while(packet[used])++used;
    }
    ZhSubtitleSendText(packet,appended);
    if(appended)ZhSubtitleCall("AS_SetSubtitlePosition",nullptr,0);
    zhcapture::End(zhcapture::Submit,captureBegin,owner->count,refreshVisibility?1u:0u);
}

static void __fastcall ZhSubtitleUpdate(ZhSubtitleOwner* owner,void*,DWORD,DWORD,DWORD) {
    if(!owner->head)return;
    // An objective changes the HUD asynchronously through the same FE queue.
    // Reassert the active subtitle after that update, without altering its
    // lifetime or pretending that the original owner has hidden it already.
    const bool refreshVisibility=owner->renderedGeneration==0;
    bool changed=!owner->visible || owner->renderedGeneration!=owner->nextId;
    const uint32_t now=ZhSubtitleNow();
    ZhSubtitleNode** link=&owner->head;
    while(*link) {
        ZhSubtitleNode* node=*link;
        const uint32_t duration=node->duration?node->duration:10000;
        // Unsigned subtraction preserves the original engine clock wrap rule.
        // Stop-by-id already writes elapsed time to node->duration (min 1 s).
        if(now-node->started>=duration) {
            zhcapture::Member(zhcapture::ExpiredMember,node->id,now,node->started,node->duration);
            *link=node->next;--owner->count;ZhSubtitleRelease(node);changed=true;
        } else link=&node->next;
    }
    owner->renderedGeneration=owner->nextId;
    if(!owner->head) {
        if(owner->visible){owner->visible=0;ZhSubtitleShow(false);}
        return;
    }
    if(changed)ZhSubtitleRender(owner,refreshVisibility,now);
}

// Only ShowObjectivePopup's call is redirected here. Loading, menu/scene
// transitions and the user's subtitle option retain native disable/clear.
static void __fastcall ZhSubtitleKeepDuringObjective(ZhSubtitleOwner* owner,void*,DWORD) {
    zhcapture::ObjectiveTrigger(owner->count);
    // nextId is always nonzero (the native enqueue skips zero on wrap).
    // Zero marks one pending refresh. Do not clear visible here: a load/scene
    // cleanup before the next update must still hide the original text field.
    if(owner->head)owner->renderedGeneration=0;
}

enum class ZhSubtitleStatus : DWORD {
    Applied=1,EngineUnavailable=2,ImageMismatch=3,SignatureMismatch=4,ProtectionFailed=5
};
struct ZhSubtitleSignature {
    DWORD rva,size,hash;
    WORD relocations[20]; // offsets within this span; 0xffff terminates
};
// FNV-1a of original Steam English engine code, absolute operands normalized
// to ImageBase 0x10000000. Generated evidence: subtitle-coexistence-20261114.
static constexpr ZhSubtitleSignature ZhSubtitleSignatures[]={
    {0x876b60,0x5e2,0x6afa7a2a,{0xb0,0x14d,0x167,0x1e4,0x24d,0x2b4,0x2dc,0x2e2,0x301,0x30a,0x34c,0x352,0x357,0x376,0x3b9,0x413,0x483,0x4a4,0x561,0xffff}},
    {0x8649c8,0x1c,0xff9721ed,{2,0xffff}},
    {0x4d1940,0x61,0x452a3a51,{0xe,0x2d,0x34,0x3a,0x3f,0xffff}},
    {0x864330,6,0x110b30ff,{1,0xffff}},
    {0x872830,8,0xae12e592,{0xffff}},
    {0x885820,0x229,0x76cf0bd6,{0x9c,0xe0,0x122,0x204,0xffff}},
    {0x63ced0,0x42,0x0411114d,{9,0xf,0x15,0xffff}},
    {0x63b990,0x1c,0x467cfab1,{0xffff}},
    {0x641130,0x166,0xd827c966,{0x79,0xffff}},
    {0x7defd0,0xf,0x26ddfa54,{2,0xffff}}
};
static bool ZhSubtitleMatches(const BYTE* engine,const ZhSubtitleSignature& signature) {
    const DWORD delta=static_cast<DWORD>(reinterpret_cast<uintptr_t>(engine))-0x10000000u;
    DWORD hash=2166136261u;unsigned relocation=0;
    for(DWORD i=0;i<signature.size;) {
        if(i==signature.relocations[relocation]) {
            DWORD value;memcpy(&value,engine+signature.rva+i,4);value-=delta;
            for(unsigned b=0;b<4;++b){hash=(hash^(value&255u))*16777619u;value>>=8;}
            i+=4;++relocation;
        } else {hash=(hash^engine[signature.rva+i])*16777619u;++i;}
    }
    return hash==signature.hash;
}
static ZhSubtitleStatus ApplyNativeSubtitles(BYTE* engine) {
    if(!engine)return ZhSubtitleStatus::EngineUnavailable;
    const auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(engine);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<0 || dos->e_lfanew>0x1000)return ZhSubtitleStatus::ImageMismatch;
    const auto pe=reinterpret_cast<const IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if(pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386 ||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC || pe->OptionalHeader.SizeOfImage<0x1332000)
        return ZhSubtitleStatus::ImageMismatch;
    for(const auto& s:ZhSubtitleSignatures)if(!ZhSubtitleMatches(engine,s))return ZhSubtitleStatus::SignatureMismatch;
    BYTE* update=engine+0x8649df;BYTE* objective=engine+0x4d1954;
    DWORD updateProtection,objectiveProtection,ignored;
    if(!VirtualProtect(update,5,PAGE_EXECUTE_READWRITE,&updateProtection))return ZhSubtitleStatus::ProtectionFailed;
    if(!VirtualProtect(objective,5,PAGE_EXECUTE_READWRITE,&objectiveProtection)) {
        VirtualProtect(update,5,updateProtection,&ignored);return ZhSubtitleStatus::ProtectionFailed;
    }
    ZhSubtitleNow=reinterpret_cast<ZhSubtitleClock>(engine+0x63ced0);
    ZhSubtitleRelease=reinterpret_cast<ZhSubtitleFree>(engine+0x7defd0);
    ZhSubtitlePrintf=reinterpret_cast<ZhSubtitleFormat>(engine+0x63b990);
    ZhSubtitleToWide=reinterpret_cast<ZhSubtitleConvert>(engine+0x641130);
    ZhSubtitleGetFrontend=reinterpret_cast<ZhSubtitleFrontend>(engine+0x864330);
    ZhSubtitleInvokeNative=reinterpret_cast<ZhSubtitleInvoke>(engine+0x872830);
    const DWORD updateDelta=reinterpret_cast<DWORD>(&ZhSubtitleUpdate)-reinterpret_cast<DWORD>(update+5);
    const DWORD objectiveDelta=reinterpret_cast<DWORD>(&ZhSubtitleKeepDuringObjective)-reinterpret_cast<DWORD>(objective+5);
    // Called from XInput DllMain before any engine thread/FE object exists.
    memcpy(update+1,&updateDelta,4);memcpy(objective+1,&objectiveDelta,4);
    FlushInstructionCache(GetCurrentProcess(),update,5);FlushInstructionCache(GetCurrentProcess(),objective,5);
    VirtualProtect(update,5,updateProtection,&ignored);VirtualProtect(objective,5,objectiveProtection,&ignored);
    return ZhSubtitleStatus::Applied;
}
