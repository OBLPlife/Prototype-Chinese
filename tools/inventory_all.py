"""Inventory native text holders across every original archive, without launching."""
import argparse,json,collections
from pathlib import Path
from resources import *

def holders(data):
    rows=[]
    def walk(d,base=0):
        offset=0
        for kind,head,children,raw in walk_chunks(d):
            if kind==0x18202:
                lang,p,_=short_name(head,12);ver,count=struct.unpack_from('<II',head,p);p+=8;keys=[]
                for _ in range(count):key,p,_=short_name(head,p);keys.append(key)
                starts=struct.unpack_from('<'+'I'*count,head,p);p+=count*4
                stops=struct.unpack_from('<'+'I'*count,head,p);p+=count*4
                stores=list(walk_chunks(children));assert len(stores)==1 and stores[0][0]==0x18201
                sh=stores[0][1];_,q,_=short_name(sh,12);sv,n=struct.unpack_from('<II',sh,q);q+=8;blob=sh[q:];assert len(blob)==n
                if lang=='english':
                    for ordinal,(key,a,b) in enumerate(zip(keys,starts,stops)):
                        rows.append(dict(id=key,text=blob[a:b-1].decode('utf-8'),holder_offset=base+offset,holder_ordinal=ordinal))
            elif children:walk(children,base+offset+len(head))
            offset+=len(raw)
    walk(data);return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--game',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    found=[];gfx=[];other=[];errors=[]
    for path in sorted(a.game.glob('*.rcf')):
        if path.name=='PrototypeZh.rcf':continue
        index=rcf_index(path);count=0
        with path.open('rb') as f:
            for r in index:
                name=r['name'].lower()
                if not name.endswith(('.p3d','.p3d.rz','.gfx','.txt','.lua','.xml')):continue
                f.seek(r['offset']);packed=f.read(r['size'])
                try:data=unpack_rz(packed)
                except Exception as e:errors.append(dict(archive=path.name,asset=r['name'],error=str(e)));continue
                if data[:4]==b'P3D\xff':
                    rows=holders(data)
                    if rows:found.append(dict(archive=path.name,asset=r['name'],source_sha256=sha(packed),rows=rows));count+=len(rows)
                    if b'credits' in data[:512].lower():other.append(dict(archive=path.name,asset=r['name'],kind='credits_candidate',bytes=len(data)))
                elif data[:3] in (b'GFX',b'FWS'):
                    imports=[p.split(b'\0')[0].decode('ascii',errors='replace') for c,p,_ in swf_tags(data)[1] if c in (57,71)]
                    gfx.append(dict(archive=path.name,asset=r['name'],bytes=len(data),imports=imports))
                else:other.append(dict(archive=path.name,asset=r['name'],kind='non_holder_text_candidate',bytes=len(data)))
        print(path.name,'entries',len(index),'English holder rows',count,flush=True)
    for name,data in [('all-text-holders.json',found),('all-gfx.json',gfx),('other-text-candidates.json',other),('inventory-errors.json',errors)]:
        (a.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('assets',len(found),'rows',sum(len(x['rows']) for x in found),'errors',len(errors))

if __name__=='__main__':main()
