"""Audit every archive entry and loose resource; distinguish text systems explicitly."""
import argparse, collections, json, re
from pathlib import Path
from resources import *
from inventory_all import holders
from audio_dialogue import read_audio_subtitles,object_type,patch_audio_subtitles


def lua_constants(data,require_exact=True):
    assert data[:12]==b'\x1bLuaQ\0\1\4\4\4\4\0'
    p=12;strings=[]
    def integer():
        nonlocal p
        n=u32(data,p);p+=4;return n
    def string():
        nonlocal p
        n=integer()
        if not n:return ''
        assert data[p+n-1]==0
        s=data[p:p+n-1].decode('utf-8');p+=n;return s
    def function():
        nonlocal p
        string();p+=12
        n=integer();p+=4*n
        for _ in range(integer()):
            kind=data[p];p+=1
            if kind==1:p+=1
            elif kind==3:p+=4
            elif kind==4:strings.append(string())
            else:assert kind==0
        for _ in range(integer()):function()
        n=integer();p+=4*n
        for _ in range(integer()):string();p+=8
        for _ in range(integer()):string()
    function()
    if require_exact:assert p==len(data),(p,len(data))
    return strings


def main():
    p=argparse.ArgumentParser();p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    totals=collections.Counter();classes=collections.Counter();audio=[];text=[];gfx=[];plain=[];errors=[];ignored=[]
    def scan(archive,name,packed):
        totals['files']+=1
        try:
            data=unpack_rz(packed)
            if data[:4]==b'P3D\xff':
                totals['p3d']+=1
                rows=holders(data)
                if rows:text.append(dict(archive=archive,asset=name,source_sha256=sha(packed),rows=rows));totals['holder_rows']+=len(rows)
                subs=read_audio_subtitles(data)
                if subs:
                    roundtrip,_=patch_audio_subtitles(data,{r['id']:(r['text'],r['text']) for r in subs})
                    assert roundtrip==data
                    for row in subs:audio.append(dict(archive=archive,asset=name,source_sha256=sha(packed),**row))
                    totals['audio_subtitle_rows']+=len(subs)
                def objects(block):
                    for kind,h,c,raw in walk_chunks(block):
                        if kind==0xfe000000:classes[object_type(h) or 'unknown']+=1
                        if c:objects(c)
                objects(data)
            elif data[:3] in (b'GFX',b'FWS'):
                totals['gfx']+=1;gfx.append(dict(archive=archive,asset=name,source_sha256=sha(packed)))
            elif data[:4]==b'\x1bLua':
                strings=lua_constants(data);totals['lua_bytecode_files']+=1
                plain.append(dict(archive=archive,asset=name,source_sha256=sha(packed),kind='lua_bytecode',strings=strings))
            elif name.lower().endswith(('.txt','.lua','.xml','.json','.ini','.cfg')):
                totals['plain_text_files']+=1;plain.append(dict(archive=archive,asset=name,source_sha256=sha(packed),text=data.decode('utf-8-sig')))
            else:
                totals['other_files']+=1
                ignored.append(dict(archive=archive,asset=name,bytes=len(data),magic=data[:12].hex()))
        except Exception as e:
            errors.append(dict(archive=archive,asset=name,error=type(e).__name__+': '+str(e)[:250]))
    archive_stats=[]
    for path in sorted(a.game.glob('*.rcf')):
        if path.name.lower()=='prototypezh.rcf':continue
        entries=rcf_index(path);before=dict(totals)
        with path.open('rb') as f:
            for entry in entries:
                f.seek(entry['offset']);scan(path.name,entry['name'],f.read(entry['size']))
        counts={k:totals[k]-before.get(k,0) for k in totals if totals[k]!=before.get(k,0)}
        archive_stats.append(dict(archive=path.name,entries=len(entries),counts=counts))
        print(path.name,counts,flush=True)
    for folder in ('audio','art','scripts'):
        for path in sorted((a.game/folder).rglob('*')):
            if path.is_file():scan(None,str(path.relative_to(a.game)),path.read_bytes())
    report=dict(scan_completed=True,counts=dict(totals),archives=archive_stats,object_classes=dict(classes),errors=errors,
                all_text_translated=False,scope='All subtitles, menus and prompts; environment texture lettering excluded by user. Preserve real company and credit personal names.')
    for name,value in [('scan.json',report),('audio-subtitles.json',audio),('text-holders.json',text),('gfx.json',gfx),('plain-text.json',plain),('other-files.json',ignored)]:
        (a.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
