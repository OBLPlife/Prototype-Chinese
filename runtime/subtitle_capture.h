#pragma once
// Optional subtitle diagnostics. No D3D queries, render-state changes or
// dependency on another patch. Only selected UI events read the QPC clock.
#include <windows.h>
#include <stdint.h>
#include <string.h>
#include "subtitle_capture_store.h"

namespace zhcapture {
enum Kind : uint32_t { Submit=1,SetText=2,Position=3,Objective=4,Visibility=5,Append=6,AutoSize=7,Trigger=8 };
// Extended fields occupy existing reserved bytes; the file remains 64 KiB.
enum Context : uint32_t { Ordinary=0,SubmittedMember=1,ExpiredMember=2,ShowArgument=3,TextPresence=4 };
static thread_local uint32_t sampleSequence[8]={};
static uint64_t Begin(uint32_t kind,bool force=false) {
    if(!zhdiag::Enabled())return 0;
    // First and then every sixteenth ordinary event. Task events are rare and
    // always retained. There is no new check in the unchanged idle update loop.
    if(!force && (++sampleSequence[kind-1]&(zhdiag::SamplingStride-1u))!=1u)return 0;
    DWORD error=GetLastError();LARGE_INTEGER now={};
    QueryPerformanceCounter(&now);SetLastError(error);
    return static_cast<uint64_t>(now.QuadPart);
}
static void End(uint32_t kind,uint64_t begin,uint32_t aux0=0,uint32_t aux1=0,uint32_t context=Ordinary) {
    if(!begin)return;
    DWORD error=GetLastError();LARGE_INTEGER now={};QueryPerformanceCounter(&now);
    zhdiag::Publish(kind,begin,static_cast<uint64_t>(now.QuadPart),aux0,aux1,context);
    SetLastError(error);
}
static void ObjectiveTrigger(uint32_t count) {
    if(!zhdiag::Enabled())return;
    uint64_t now=Begin(Trigger,true);
    if(now)zhdiag::Publish(Trigger,now,now,count,0); // Marker, not a duration measurement.
}
static void Member(Context context,uint32_t id,uint32_t gameNow,uint32_t started,uint32_t duration) {
    // Called only on a text submission or a native node expiration. No new
    // checks or clock reads are added to the unchanged idle-update path.
    uint64_t stamp=Begin(Trigger,true);
    if(stamp)zhdiag::Publish(Trigger,stamp,stamp,id,gameNow,context,(uint64_t(duration)<<32)|started);
}

struct Value {
    uint32_t type,reserved;
    union {double number;const char* text;uint64_t bits;} data;
};
static_assert(sizeof(Value)==16,"native GFx argument layout");
using Invoke=void(__thiscall*)(void*,const char*,const Value*,unsigned);
static Invoke originalInvoke;

static unsigned Classify(const char* method,const Value* values,unsigned count) {
    if(!method)return 0;
    if(method[0]=='A' && method[1]=='S' && method[2]=='_') {
        if(!strcmp(method,"AS_SetSubtitles"))return SetText;
        if(!strcmp(method,"AS_SetSubtitlePosition"))return Position;
        if(!strcmp(method,"AS_SubtitleShow"))return Visibility;
        if(!strcmp(method,"AS_CallASFunction") && values && count>=2 &&
           values[1].type==4 && values[1].data.text) {
            if(!strcmp(values[1].data.text,"ShowObjectivePopup"))return Objective;
            if(values[0].type==4 && values[0].data.text &&
               !strcmp(values[1].data.text,"appendHtml") &&
               !strcmp(values[0].data.text,"_global.gSubtitles.subtitleText"))return Append;
        }
    } else if(!strcmp(method,"SetVar") && values && count>=2 && values[0].type==4 &&
              values[0].data.text && !strcmp(values[0].data.text,"_global.gSubtitles.subtitleText.autoSize"))return AutoSize;
    return 0;
}
static void __fastcall InvokeMeasured(void* movie,void*,const char* method,const Value* values,unsigned count) {
    if(!zhdiag::Enabled()){originalInvoke(movie,method,values,count);return;}
    unsigned kind=Classify(method,values,count);
    if(!kind){originalInvoke(movie,method,values,count);return;}
    // Visibility and text must not be sampled away when diagnosing a vanished
    // line. Other ordinary measurements retain their existing sampling policy.
    bool forced=kind==Objective || kind==Position || kind==Append || kind==Visibility || kind==SetText;
    uint32_t context=Ordinary,detail=forced?1u:0u;
    if(kind==Visibility && values && count && values[0].type==2) {
        context=ShowArgument;detail=(values[0].data.bits&255u)?1u:0u;
    } else if(kind==SetText && values && count && values[0].data.text) {
        if(values[0].type==4) {context=TextPresence;detail=values[0].data.text[0]?1u:0u;}
        else if(values[0].type==5) {context=TextPresence;detail=reinterpret_cast<const wchar_t*>(values[0].data.text)[0]?1u:0u;}
    }
    uint64_t begin=Begin(kind,forced);
    originalInvoke(movie,method,values,count);
    End(kind,begin,count,detail,context);
}

enum class Status : DWORD {Applied=1,EngineUnavailable=2,ImageMismatch=3,SignatureMismatch=4,ProtectionFailed=5};
static bool Matches(const BYTE* engine,DWORD rva,DWORD size,DWORD expected,const WORD* reloc,unsigned count) {
    DWORD delta=static_cast<DWORD>(reinterpret_cast<uintptr_t>(engine))-0x10000000u;
    DWORD hash=2166136261u;unsigned fix=0;
    for(DWORD i=0;i<size;) {
        if(fix<count && i==reloc[fix]) {
            DWORD value;memcpy(&value,engine+rva+i,4);value-=delta;
            for(unsigned b=0;b<4;++b){hash=(hash^(value&255u))*16777619u;value>>=8;}
            i+=4;++fix;
        }else{hash=(hash^engine[rva+i])*16777619u;++i;}
    }
    return hash==expected;
}
static Status Apply(BYTE* engine) {
    if(!engine)return Status::EngineUnavailable;
    auto dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(engine);
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE || dos->e_lfanew<0 || dos->e_lfanew>0x1000)return Status::ImageMismatch;
    auto pe=reinterpret_cast<const IMAGE_NT_HEADERS32*>(engine+dos->e_lfanew);
    if(pe->Signature!=IMAGE_NT_SIGNATURE || pe->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386 ||
       pe->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC || pe->OptionalHeader.SizeOfImage<0x1332000)
        return Status::ImageMismatch;
    static constexpr WORD relocations[]={2,0x52};
    if(!Matches(engine,0x8857b0,0x69,0x19c34954,relocations,2) ||
       !Matches(engine,0x964140,0x64,0x5c9f1019,nullptr,0))return Status::SignatureMismatch;
    BYTE* call=engine+0x8857f4;DWORD previous,ignored;
    if(!VirtualProtect(call,5,PAGE_EXECUTE_READWRITE,&previous))return Status::ProtectionFailed;
    originalInvoke=reinterpret_cast<Invoke>(engine+0x964140);
    DWORD delta=reinterpret_cast<DWORD>(&InvokeMeasured)-reinterpret_cast<DWORD>(call+5);
    memcpy(call+1,&delta,4);FlushInstructionCache(GetCurrentProcess(),call,5);
    VirtualProtect(call,5,previous,&ignored);
    return Status::Applied;
}
}
