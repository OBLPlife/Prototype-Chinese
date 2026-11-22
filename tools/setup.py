"""Owned localization resources/support installation; never rewrites the engine."""
import argparse
import csv
import datetime
import io
import json
import os
import subprocess
from pathlib import Path
from resources import *
from subtitle_support import SUBTITLE_SUPPORT,LEGACY_SUBTITLE_SUPPORT,check_signatures as check_subtitle_signatures
from subtitle_capture_support import CAPTURE_SUPPORT

OWN='PrototypeZh.rcf'
RUNTIME='XInput1_3.dll'
CONSTRUCTOR_RVA=0x9615c0
HEAP_ID_RVA=0x9615d7
CONSTRUCTOR_SIGNATURE=bytes.fromhex('8bc18d480cc70014d9e8108949208d4830894920c7400472000000c6400800c3')
FONT_BUFFER_SIGNATURES={
    0x95c6cd:bytes.fromhex('6a10506a018907e8f7e1cdff8b3f8b4c242083c40c'),
    0x95c793:bytes.fromhex('8b4e18516a01e822e2cdff83c40833c0894618')}
FONT_BUFFER_SUPPORT=dict(alloc_call_rva=0x95c6d4,free_call_rva=0x95c799,original_heap_id=1,native_heap_id=0,
    assets=[r'\art\hud\fonts_latin.gfx',r'\art\hud\gfxfontlib.gfx'],
    paired_release=True,other_resources_unchanged=True)
FONT_LOOKUP_SLOT_RVA=0xe8fc40
FONT_LOOKUP_WRAPPER_RVA=0x9ad260
FONT_LOOKUP_SIGNATURES={
    FONT_LOOKUP_WRAPPER_RVA:bytes.fromhex('83c130e968e4ffff'),
    0x9ab6d0:bytes.fromhex(
        '51535556578b791483ef01bd00000000783e8b41188b49108b71080fb75c2418'
        '894424108d042f992bc28b542410d1f88d0cc233d28a740e018a140e8bca3bd9'
        '741173058d78ffeb038d68013bef7ed483c8ff5f5e5d5b59c20400')}
FONT_LOOKUP_SUPPORT=dict(vtable_slot_rva=FONT_LOOKUP_SLOT_RVA,original_lookup_rva=FONT_LOOKUP_WRAPPER_RVA,
    verified_codepoint_probe=True,original_binary_search_fallback=True,
    allocations=False,persistent_cache=False,other_font_vtables_unchanged=True)
FONT_KERNING_SLOT_RVA=0xe8fc58
FONT_KERNING_WRAPPER_RVA=0x9ad2d0
FONT_KERNING_SIGNATURES={
    FONT_KERNING_WRAPPER_RVA:bytes.fromhex('8b442408568bf18b4c240850518d4e30e88be4ffffd80df8fde1108b5664db466485d27d06d805f009de10def95ec20800'),
    0x9ab770:bytes.fromhex(
        '83ec0c538b591c83eb015556b80000000057894c24148944241078728b512089542418'
        '8b51108b6a08eb09eb038d49008b4c24148b49108b49088b74241803c3992bc2d1f8'
        '8d14408d14568d341133c98a6e018a0e8bf133c98a6c2a038a4c2a028bf98b4c2420'
        '3bce75088b4c24243bcf74270f92c184c974098d58ff8b442410eb0783c00189442410'
        '3bc37ea2d9ee5f5e5d5b83c40cc208008b4424148b48108b41088d44100433c98a68'
        '015f5e5d5b8a080fbfd189542410db44241083c40cc20800')}
FONT_KERNING_SUPPORT=dict(vtable_slot_rva=FONT_KERNING_SLOT_RVA,original_kerning_rva=FONT_KERNING_WRAPPER_RVA,
    verified_adjacent_record_gap=True,original_binary_search_fallback=True,
    latin_tail_dispatch=True,allocations=False,persistent_cache=False,other_font_vtables_unchanged=True)
BASE={'scripts.rcf','00audio.rcf','01audio.rcf','shaders.rcf','art.rcf','cells.rcf',
      'movies.rcf','00woi.rcf','01woi.rcf','02woi.rcf','03woi.rcf'}

def read_groups(body):
    if u32(body)!=len(body)-4 or body[4:8]!=b'META':raise ValueError('Unknown cement metadata')
    count=u32(body,8);p=12;groups=[]
    def string():
        nonlocal p
        n=u32(body,p);p+=4;s=body[p:p+n].decode('ascii');p+=n;return s
    for _ in range(count):
        name=string();n=u32(body,p);p+=4;groups.append((name,[string() for _ in range(n)]))
    if p!=len(body):raise ValueError('Unparsed cement metadata')
    return groups

def cement_edit(data,install,restore_groups=None):
    """Merge only our registration; preserve all other groups and their order."""
    found=[]
    def edit(d):
        out=[]
        for k,h,c,raw in walk_chunks(d):
            if k==0x7f00001:
                groups=read_groups(h[12:]);found.extend(groups)
                if sum(n=='default' for n,_ in groups)!=1:raise ValueError('Expected one default collection')
                content=b'META'+p32(len(groups))
                for name,items in groups:
                    items=[x for x in items if x.lower()!=OWN.lower()]
                    if install and name=='default':items.insert(0,OWN)
                    elif restore_groups is not None:
                        # Restore only our old positions. Archives added by another
                        # patch since installation keep their current ordering.
                        previous=dict(restore_groups).get(name,[])
                        for pos,item in reversed(list(enumerate(previous))):
                            if item.lower()!=OWN.lower():continue
                            names=[entry.lower() for entry in items]
                            following=next((names.index(x.lower()) for x in previous[pos+1:]
                                            if x.lower() in names),None)
                            if following is None:
                                preceding=next((names.index(x.lower())+1 for x in reversed(previous[:pos])
                                                if x.lower() in names),min(pos,len(items)))
                                following=preceding
                            items.insert(following,item)
                    content+=p32(len(name))+name.encode('ascii')+p32(len(items))
                    for item in items:content+=p32(len(item))+item.encode('ascii')
                out.append(chunk(k,p32(len(content))+content,c))
            else:out.append(chunk(k,h[12:],edit(c) if c else b''))
        return b''.join(out)
    result=edit(data)
    if not found:raise ValueError('No cement collection')
    return result,found

def atomic_write(path,data):
    # Adjacent replacement keeps a manifest fully formed at every visible state.
    temp=path.with_name(path.name+'.PrototypeZh.tmp')
    # A stale or concurrent staging file is not ours to overwrite.
    with temp.open('xb') as f:
        try:f.write(data);f.flush();os.fsync(f.fileno())
        except BaseException:
            f.close();temp.unlink();raise
    try:temp.replace(path)
    except BaseException:
        temp.unlink();raise

def json_bytes(d):return (json.dumps(d,ensure_ascii=False,indent=2)+'\n').encode('utf-8')

def runtime_spec(manifest):
    spec=manifest.get('runtime_support')
    full_gbk=manifest.get('character_set',{}).get('name')=='GBK / Windows CP936'
    if spec is None:
        if full_gbk:raise ValueError('Full GBK fonts require paired native font buffer support')
        return None
    expected=dict(file=RUNTIME,constructor_rva=CONSTRUCTOR_RVA,heap_id_rva=HEAP_ID_RVA,
                  original_heap_id=0x72,native_heap_id=0)
    if not isinstance(spec,dict) or any(spec.get(k)!=v for k,v in expected.items()):
        raise ValueError('Unsupported localization runtime support manifest')
    digest=spec.get('sha256')
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
        raise ValueError('Invalid localization runtime support checksum')
    if full_gbk or 'font_buffers' in spec:
        if spec.get('font_buffers')!=FONT_BUFFER_SUPPORT:
            raise ValueError('Unsupported or missing paired font buffer support')
    if 'font_lookup' in spec and spec['font_lookup']!=FONT_LOOKUP_SUPPORT:
        raise ValueError('Unsupported compact font lookup support')
    if 'font_kerning' in spec and spec['font_kerning']!=FONT_KERNING_SUPPORT:
        raise ValueError('Unsupported compact font kerning support')
    if 'subtitles' in spec and spec['subtitles'] not in (SUBTITLE_SUPPORT,LEGACY_SUBTITLE_SUPPORT):
        raise ValueError('Unsupported concurrent subtitle support')
    if 'subtitle_capture' in spec and spec['subtitle_capture']!=CAPTURE_SUPPORT:
        raise ValueError('Unsupported optional subtitle diagnostics')
    return spec

def engine_runtime_status(game,font_buffers=False,font_lookup=False,font_kerning=False,subtitles=False):
    """Read the disk PE only; the runtime changes its own process memory later."""
    try:
        data=(Path(game)/'prototypeenginef.dll').read_bytes()
        if len(data)<64 or data[:2]!=b'MZ':raise ValueError('Invalid engine DOS header')
        pe=u32(data,0x3c)
        if pe+24>len(data) or data[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid engine PE header')
        machine,sections=struct.unpack_from('<HH',data,pe+4)
        optional_size=struct.unpack_from('<H',data,pe+20)[0];optional=pe+24
        if machine!=0x14c or optional_size<32 or optional+optional_size>len(data):
            raise ValueError('Unsupported engine machine or optional header')
        if struct.unpack_from('<H',data,optional)[0]!=0x10b:raise ValueError('Engine must be PE32')
        image_base=u32(data,optional+28)
        table=optional+optional_size
        if table+sections*40>len(data):raise ValueError('Truncated engine section table')
        offset=None
        for i in range(sections):
            section=table+i*40
            virtual_size,rva,raw_size,raw_offset=struct.unpack_from('<IIII',data,section+8)
            delta=CONSTRUCTOR_RVA-rva
            if 0<=delta and delta+len(CONSTRUCTOR_SIGNATURE)<=raw_size:
                if offset is not None:raise ValueError('Ambiguous engine constructor mapping')
                offset=raw_offset+delta
        if offset is None or offset+len(CONSTRUCTOR_SIGNATURE)>len(data):
            raise ValueError('Engine constructor has no complete disk section mapping')
        expected=bytearray(CONSTRUCTOR_SIGNATURE)
        struct.pack_into('<I',expected,7,image_base+0xe8d914)
        if data[offset:offset+len(expected)]!=expected:
            raise ValueError('Engine GFx allocator constructor signature mismatch')
        if font_buffers:
            for target,signature in FONT_BUFFER_SIGNATURES.items():
                matches=[]
                for i in range(sections):
                    section=table+i*40
                    _,rva,raw_size,raw_offset=struct.unpack_from('<IIII',data,section+8)
                    delta=target-rva
                    if 0<=delta and delta+len(signature)<=raw_size:matches.append(raw_offset+delta)
                if len(matches)!=1 or data[matches[0]:matches[0]+len(signature)]!=signature:
                    raise ValueError(f'Engine font buffer callsite signature mismatch at RVA {target:08x}')
        if font_lookup:
            signatures={**FONT_LOOKUP_SIGNATURES,
                FONT_LOOKUP_SLOT_RVA:struct.pack('<I',image_base+FONT_LOOKUP_WRAPPER_RVA)}
            for target,signature in signatures.items():
                matches=[]
                for i in range(sections):
                    section=table+i*40
                    _,rva,raw_size,raw_offset=struct.unpack_from('<IIII',data,section+8)
                    delta=target-rva
                    if 0<=delta and delta+len(signature)<=raw_size:matches.append(raw_offset+delta)
                if len(matches)!=1 or data[matches[0]:matches[0]+len(signature)]!=signature:
                    raise ValueError(f'Engine compact font lookup signature mismatch at RVA {target:08x}')
        if font_kerning:
            wrapper=bytearray(FONT_KERNING_SIGNATURES[FONT_KERNING_WRAPPER_RVA])
            struct.pack_into('<I',wrapper,23,image_base+0xe1fdf8)
            struct.pack_into('<I',wrapper,39,image_base+0xde09f0)
            signatures={**FONT_KERNING_SIGNATURES,FONT_KERNING_WRAPPER_RVA:wrapper,
                FONT_KERNING_SLOT_RVA:struct.pack('<I',image_base+FONT_KERNING_WRAPPER_RVA)}
            for target,signature in signatures.items():
                matches=[]
                for i in range(sections):
                    section=table+i*40
                    _,rva,raw_size,raw_offset=struct.unpack_from('<IIII',data,section+8)
                    delta=target-rva
                    if 0<=delta and delta+len(signature)<=raw_size:matches.append(raw_offset+delta)
                if len(matches)!=1 or data[matches[0]:matches[0]+len(signature)]!=signature:
                    raise ValueError(f'Engine compact font kerning signature mismatch at RVA {target:08x}')
        if subtitles:check_subtitle_signatures(data,image_base,table,sections)
        return dict(compatible=True,image_base=image_base,constructor_rva=CONSTRUCTOR_RVA,
                    heap_id_rva=HEAP_ID_RVA,original_heap_id=0x72,native_heap_id=0,
                    font_buffer_calls_checked=bool(font_buffers),font_lookup_checked=bool(font_lookup),
                    font_kerning_checked=bool(font_kerning),subtitles_checked=bool(subtitles))
    except (OSError,ValueError,struct.error,OverflowError) as e:
        return dict(compatible=False,error=str(e))

def apply_transaction(changes):
    """Rollback only our published bytes when a file write/delete fails."""
    before={path:path.read_bytes() if path.exists() else None for path,_ in changes}
    attempted=[]
    try:
        for path,data in changes:
            current=path.read_bytes() if path.exists() else None
            if current!=before[path]:raise ValueError('File changed during localization transaction: '+str(path))
            attempted.append((path,data))
            if data is None:
                if path.exists():path.unlink()
            else:atomic_write(path,data)
    except BaseException:
        for path,written in reversed(attempted):
            current=path.read_bytes() if path.exists() else None
            if current!=written:continue # Preserve a concurrent third-party replacement.
            original=before[path]
            if original is None:
                if path.exists():path.unlink()
            else:atomic_write(path,original)
        raise

def resource_differences(game,manifest,groups):
    """Compare only translated entries, and the names in additional archive indices."""
    from collections import defaultdict
    game=Path(game)
    owned={name_hash(r['asset']) for r in manifest['resources']}
    archives=defaultdict(list)
    for r in manifest['resources']:
        archives[r['archive']].append(r)
    for name,rows in archives.items():
        try:
            path=game/name
            entries={r['key']:r for r in rcf_index(path)}
            with path.open('rb') as stream:
                for row in rows:
                    entry=entries.get(name_hash(row['asset']))
                    if entry is None:
                        yield name+' | '+row['asset']+'（缺少条目）'
                        continue
                    stream.seek(entry['offset'])
                    if sha(stream.read(entry['size']))!=row['source_sha256']:
                        yield name+' | '+row['asset']
        except (OSError,ValueError,struct.error,KeyError,IndexError) as error:
            yield name+'（无法核对该包中的汉化条目） '+str(error)
    # Added texture archives are compatible unless they replace the same resource.
    for _,items in groups:
        for name in items:
            if name.lower() in BASE or name.lower()==OWN.lower():continue
            target=(game/name).resolve()
            if not target.is_relative_to(game.resolve()):
                yield name+'（游戏目录以外的资源包，未读取）'
                continue
            try:
                for row in rcf_index(target):
                    if row['key'] in owned:
                        yield name+' | '+row['name']+'（另一资源包也提供此条目）'
            except (OSError,ValueError,struct.error,KeyError,IndexError) as error:
                yield name+'（无法核对额外资源包的目录） '+str(error)

def check_resources(game,manifest,groups):
    first=next(resource_differences(game,manifest,groups),None)
    if first:raise ValueError('Shared resource changed or unavailable: '+first)

def install(game,package):
    game=Path(game);package=Path(package)
    manifest=json.loads((package/'manifest.json').read_text('utf-8'))
    archive=(package/OWN).read_bytes()
    if sha(archive)!=manifest['archive_sha256']:raise ValueError('Package archive checksum mismatch')
    for r in manifest['resources']:
        if sha(rcf_read(package/OWN,r['asset']))!=r['sha256']:raise ValueError('Package resource checksum mismatch')
    support=runtime_spec(manifest);runtime_data=None
    if support:
        runtime_data=(package/RUNTIME).read_bytes()
        if sha(runtime_data)!=support['sha256']:raise ValueError('Package runtime support checksum mismatch')
        compatible=engine_runtime_status(game,bool(support.get('font_buffers')),bool(support.get('font_lookup')),bool(support.get('font_kerning')),bool(support.get('subtitles')))
        if not compatible['compatible']:raise ValueError(compatible['error'])
    before=(game/'cementfiles.p3d').read_bytes();after,groups=cement_edit(before,True)
    check_resources(game,manifest,groups)
    folder=game/'PrototypeZh';statefile=folder/'state.json'
    old=json.loads(statefile.read_text('utf-8')) if statefile.exists() else {}
    if (game/OWN).exists():
        if not statefile.exists():raise ValueError('Unowned PrototypeZh.rcf already exists')
        if sha((game/OWN).read_bytes())!=old['archive_sha256']:raise ValueError('Installed localization archive has been changed')
    previous_support=runtime_spec(old)
    runtime=game/RUNTIME
    if runtime.exists() and (support or previous_support):
        if not previous_support or sha(runtime.read_bytes())!=previous_support['sha256']:
            raise ValueError('Unowned or changed '+RUNTIME+'; preserve the other loader and resolve the file conflict first')
    folder.mkdir(exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=folder/('cementfiles.before-'+stamp+'.p3d');backup.write_bytes(before)
    state=dict(manifest,installed_utc=stamp,cement_backup=backup.name,cement_before_sha256=sha(before),cement_after_sha256=sha(after))
    changes=[(game/OWN,archive)]
    if support or previous_support:changes.append((runtime,runtime_data))
    # Payload/support first, ownership before registration; all are rolled back on failure.
    changes.extend([(statefile,json_bytes(state)),(game/'cementfiles.p3d',after)])
    apply_transaction(changes)
    return dict(installed=True,version=manifest['version'],archive_bytes=len(archive),cement_changed=before!=after,
                original_archives_modified=False,engine_file_modified=False,
                runtime_support_installed=support is not None,runtime_verified=False)

def uninstall(game):
    game=Path(game);folder=game/'PrototypeZh';statefile=folder/'state.json'
    state=json.loads(statefile.read_text('utf-8'))
    archive=game/OWN
    if archive.exists() and sha(archive.read_bytes())!=state['archive_sha256']:
        raise ValueError('Localization archive changed; preserve it for inspection before uninstalling')
    support=runtime_spec(state);runtime=game/RUNTIME
    runtime_owned=bool(support and runtime.is_file() and sha(runtime.read_bytes())==support['sha256'])
    runtime_preserved=runtime.exists() and not runtime_owned
    before=(game/'cementfiles.p3d').read_bytes();after,_=cement_edit(before,False)
    changes=[(game/'cementfiles.p3d',after),(archive,None)]
    if runtime_owned:changes.append((runtime,None))
    changes.append((statefile,None))
    apply_transaction(changes)
    return dict(installed=False,other_registrations_preserved=True,backups_retained=str(folder),
                runtime_support_removed=runtime_owned,foreign_or_changed_runtime_preserved=runtime_preserved)

def status(game):
    game=Path(game);_,groups=cement_edit((game/'cementfiles.p3d').read_bytes(),False)
    entries=[x for n,items in groups for x in items if x.lower()==OWN.lower()]
    file=game/'PrototypeZh/state.json'
    result=dict(registered=len(entries),archive_present=(game/OWN).is_file(),state_present=file.is_file())
    support=None
    if file.exists():
        manifest=json.loads(file.read_text('utf-8'))
        result['resources_changed']=next(resource_differences(game,manifest,groups),None) is not None
        support=runtime_spec(manifest)
        result.update(version=manifest['version'],checksum_ok=(game/OWN).is_file() and sha((game/OWN).read_bytes())==manifest['archive_sha256'])
    runtime=game/RUNTIME
    result.update(runtime_required=support is not None,runtime_file=RUNTIME,runtime_present=runtime.is_file(),
                  runtime_checksum_ok=bool(support and runtime.is_file() and sha(runtime.read_bytes())==support['sha256']),
                  runtime_engine=engine_runtime_status(game,bool(support and support.get('font_buffers')),
                      bool(support and support.get('font_lookup')),bool(support and support.get('font_kerning')),bool(support and support.get('subtitles'))))
    return result

def ensure_game_closed():
    if os.name=='nt':
        result=subprocess.run(['tasklist','/FI','IMAGENAME eq prototypef.exe','/FO','CSV','/NH'],capture_output=True,check=True)
        if any(row and row[0].lower()=='prototypef.exe' for row in csv.reader(io.StringIO(result.stdout.decode('utf-8',errors='replace')))):
            raise ValueError('请先退出正在运行的《虐杀原形》。')

def main():
    import sys
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','uninstall','status']);p.add_argument('--game',required=True,type=Path);p.add_argument('--package',type=Path)
    p.add_argument('--accept-risk',action='store_true')
    a=p.parse_args()
    if a.action=='status':
        print(json.dumps(status(a.game),ensure_ascii=False,indent=2))
        return 0
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'packaging'))
    import release_install
    options=[('restore' if a.action=='uninstall' else 'install'),'--game',str(a.game)]
    if a.package:options.extend(['--package',str(a.package)])
    if a.accept_risk:options.append('--accept-risk')
    return release_install.main(options)

if __name__=='__main__':raise SystemExit(main())
