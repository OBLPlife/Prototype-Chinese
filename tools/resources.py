"""PrototypeZh binary resources, without game/runtime hooks.

RCF/P3D reading is adapted from the prior local independent English research
reader, whose format reference is gibbed/Gibbed.Prototype commit
026da397342c4f8a43af575232dccf4b104df2e5. Altered implementation, not Rick's tool.

Copyright (c) 2012 Rick (rick 'at' gibbed 'dot' us)
This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from
the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:
1. The origin of this software must not be misrepresented; you must not
claim that you wrote the original software. If you use this software in
a product, an acknowledgment in the product documentation would be
appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not
be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
"""
from pathlib import Path
import struct
import zlib
import hashlib
import re
from functools import lru_cache

def u32(d, p=0):
    return struct.unpack_from('<I', d, p)[0]

def p32(n):
    return struct.pack('<I', n)

def sha(d):
    return hashlib.sha256(d).hexdigest()

def name_hash(name):
    h = 0
    for c in name.lstrip('\\').encode('ascii'):
        h = (31*h+(c+32 if c<97 else c)) & 0xffffffff
    return h

def rcf_index(path):
    with Path(path).open('rb') as f:
        h = f.read(60)
        if h[:32] != b'ATG CORE CEMENT LIBRARY'.ljust(32, b'\0') or h[32:36] != b'\2\1\0\1':
            raise ValueError('Unsupported RCF header')
        io, size, no, ns, reserved, count = struct.unpack_from('<6I', h, 36)
        if size != count*12 or reserved:
            raise ValueError('Unsupported RCF index')
        f.seek(io)
        table = {}
        for i in range(count):
            key, off, length = struct.unpack('<III', f.read(12))
            if key in table: raise ValueError('Duplicate archive hash')
            table[key] = (off, length, io+i*12)
        f.seek(no); names = f.read(ns)
        file_size = f.seek(0, 2)
    p = 8; result = []
    for _ in range(count):
        stamp, align, flag, length = struct.unpack_from('<4I', names, p)
        p += 16
        name = names[p:p+length]
        if not name.endswith(b'\0'): raise ValueError('Missing name terminator')
        name = name[:-1].decode('ascii'); p += length
        if names[p:p+3] != b'\0'*3: raise ValueError('Unexpected name padding')
        p += 3
        key = name_hash(name); off, length, slot = table[key]
        if off+length > file_size: raise ValueError('Archive entry outside file')
        result.append(dict(name=name, offset=off, size=length, key=key, index_slot=slot,
                           stamp=stamp, alignment=align, flag=flag))
    if p != len(names): raise ValueError('Unparsed name metadata')
    return result

@lru_cache(maxsize=16)
def _read_index(path, size, modified, changed):
    # The full dialogue inventory has 14,318 assets. Reuse the index while the
    # file identity metadata is unchanged, instead of reparsing it for each row.
    return {r['key']:r for r in rcf_index(path)}


def rcf_read(path, name):
    path=Path(path).resolve();info=path.stat()
    r=_read_index(str(path),info.st_size,info.st_mtime_ns,info.st_ctime_ns).get(name_hash(name))
    if r is None:raise ValueError('Missing resource: '+name)
    with Path(path).open('rb') as f:
        f.seek(r['offset']); return f.read(r['size'])

def make_rcf(resources):
    """Create a standalone native archive; no original archive is rewritten."""
    keys = [name_hash(n) for n in resources]
    if len(keys) != len(set(keys)): raise ValueError('Resource hash collision')
    n = len(resources); io = 60
    no = (io+n*12+2047)//2048*2048
    meta = p32(2048)+p32(0)
    for name in resources:
        raw = name.encode('ascii')+b'\0'
        meta += struct.pack('<4I', 0, 2048, 0, len(raw))+raw+b'\0'*3
    start = (no+len(meta)+2047)//2048*2048
    data = bytearray(start)
    entries = []
    for name, payload in resources.items():
        off = (len(data)+2047)//2048*2048
        data.extend(b'\0'*(off-len(data))); data.extend(payload)
        entries.append((name_hash(name), off, len(payload)))
    data[:60] = b'ATG CORE CEMENT LIBRARY'.ljust(32,b'\0')+b'\2\1\0\1'+struct.pack('<6I',io,n*12,no,len(meta),0,n)
    data[io:io+n*12] = b''.join(struct.pack('<III',*x) for x in sorted(entries))
    data[no:no+len(meta)] = meta
    return bytes(data)

def unpack_rz(data):
    if data[:4] != b'RZ\0\0': return data
    out = zlib.decompress(data[16:])
    if len(out)!=u32(data,8): raise ValueError('RZ size mismatch')
    return out

def repack_rz(original, raw):
    if original[:4] != b'RZ\0\0': return raw
    header = bytearray(original[:16])
    # Observed original RZ has zero reserved words at +4/+12, plain size +8.
    if u32(original,4) != 0 or u32(original,12) != 0:
        raise ValueError('Unsupported RZ reserved fields')
    body = zlib.compress(raw)
    header[8:12] = p32(len(raw))
    return bytes(header)+body

def short_name(d, p):
    n=d[p]; raw=d[p:p+n+1]
    return raw[1:].rstrip(b'\0').decode('ascii'), p+n+1, raw

def chunk(kind, header_body, children=b''):
    return struct.pack('<III',kind,12+len(header_body),12+len(header_body)+len(children))+header_body+children

def walk_chunks(data):
    p=0
    while p<len(data):
        kind,h,t=struct.unpack_from('<III',data,p)
        if h<12 or t<h or p+t>len(data): raise ValueError('Invalid P3D chunk')
        yield kind,data[p:p+h],data[p+h:p+t],data[p:p+t]
        p+=t
    if p!=len(data): raise ValueError('P3D trailing data')

def patch_text(data, translations, changes):
    """Rebuild only English text storage and its byte offsets; keep IDs/timing."""
    result=[]
    for kind,head,children,raw in walk_chunks(data):
        if kind==0x18202:
            lang,p,lang_raw=short_name(head,12)
            ver,count=struct.unpack_from('<II',head,p);p+=8
            keys=[];keys_raw=b''
            for _ in range(count):
                key,p,kraw=short_name(head,p);keys.append(key);keys_raw+=kraw
            starts=struct.unpack_from('<'+'I'*count,head,p);p+=count*4
            stops=struct.unpack_from('<'+'I'*count,head,p);p+=count*4
            if p!=len(head): raise ValueError('Unknown holder header')
            stores=list(walk_chunks(children))
            if len(stores)!=1 or stores[0][0]!=0x18201: raise ValueError('Unknown holder children')
            _,sh,sc,sraw=stores[0]
            if sc: raise ValueError('Unexpected nested string storage')
            _,q,sname=short_name(sh,12)
            sv,blen=struct.unpack_from('<II',sh,q);q+=8
            blob=sh[q:]
            if len(blob)!=blen:raise ValueError('String storage length')
            new=[];new_starts=[];new_stops=[];position=0
            for key,a,b in zip(keys,starts,stops):
                text=blob[a:b-1].decode('utf-8')
                replacement=translations.get(key) if lang=='english' else None
                if replacement is not None:
                    if sorted(re.findall(r'%\d+:[A-Z][A-Z0-9_]*',text))!=sorted(re.findall(r'%\d+:[A-Z][A-Z0-9_]*',replacement)):
                        raise ValueError('Placeholder mismatch: '+key)
                    changes.append({'id':key,'source':text,'zh':replacement})
                    text=replacement
                encoded=text.encode('utf-8')
                new_starts.append(position);position+=len(encoded);new_stops.append(position+1);new.append(encoded)
            storage=chunk(0x18201,sname+struct.pack('<II',sv,position)+b''.join(new))
            hb=lang_raw+struct.pack('<II',ver,count)+keys_raw+struct.pack('<'+'I'*count,*new_starts)+struct.pack('<'+'I'*count,*new_stops)
            result.append(chunk(kind,hb,storage))
        else:
            result.append(chunk(kind,head[12:],patch_text(children,translations,changes) if children else b''))
    return b''.join(result)

def swf_tags(data):
    if data[:3] not in (b'GFX',b'FWS'): raise ValueError('Expected uncompressed font movie')
    if u32(data,4)!=len(data):raise ValueError('SWF length mismatch')
    p=8+(5+(data[8]>>3)*4+7)//8+4
    prefix=data[:p];tags=[]
    while p<len(data):
        begin=p;v=struct.unpack_from('<H',data,p)[0];p+=2;code=v>>6;n=v&63
        if n==63:n=u32(data,p);p+=4
        if p+n>len(data):raise ValueError('Bad SWF tag length')
        tags.append((code,data[p:p+n],data[begin:p+n]));p+=n
        if code==0:break
    if p!=len(data):raise ValueError('SWF trailing bytes')
    return prefix,tags

def rect_end(d,p):
    return p+(5+4*(d[p]>>3)+7)//8

def font3(p):
    fid,flags,lang,n=struct.unpack_from('<HBBB',p)
    name=p[5:5+n].rstrip(b'\0').decode('ascii');cpos=5+n;count=struct.unpack_from('<H',p,cpos)[0];q=cpos+2
    width=4 if flags&8 else 2
    offsets=struct.unpack_from('<'+('I' if width==4 else 'H')*(count+1),p,q)
    codepos=q+offsets[-1]
    if not flags&4:raise ValueError('Font must use UTF-16 code table')
    codes=list(struct.unpack_from('<'+'H'*count,p,codepos));r=codepos+2*count
    if not flags&128:raise ValueError('Expected original font metrics')
    metrics=p[r:r+6];r+=6
    advances=list(struct.unpack_from('<'+'h'*count,p,r));r+=2*count
    bounds=[]
    for _ in codes:
        e=rect_end(p,r);bounds.append(p[r:e]);r=e
    kern=p[r:]
    if len(kern)!=2+struct.unpack_from('<H',kern)[0]*6:raise ValueError('Bad kerning layout')
    glyphs=[p[q+offsets[i]:q+offsets[i+1]] for i in range(count)]
    return dict(id=fid,flags=flags,name=name,prefix=p[:cpos],codes=codes,glyphs=glyphs,metrics=metrics,advances=advances,bounds=bounds,kern=kern)

def merge_font3(original,generated,allow_reindex=False,advance_reference=None):
    a,b=font3(original),font3(generated)
    if a['name']!=b['name'] or a['metrics']!=b['metrics']:raise ValueError('Font identity/metrics changed')
    widths=b
    if advance_reference is not None:
        widths=font3(advance_reference)
        if widths['name']!=b['name'] or widths['codes']!=b['codes'] or widths['metrics']!=b['metrics']:
            raise ValueError('Reference advances do not match the generated face and character set')
    original_index={c:i for i,c in enumerate(a['codes'])}
    generated_index={c:i for i,c in enumerate(b['codes'])}
    added=[c for c in b['codes'] if c not in original_index]
    renumber=any(c<=max(a['codes']) for c in added)
    if renumber and not allow_reindex:raise ValueError('Would renumber existing glyphs')
    new_codes=sorted(a['codes']+added);glyphs=[];adv=[];bounds=[]
    for c in new_codes:
        if c in original_index:
            source=a;i=original_index[c];advance=a['advances'][i]
        else:
            source=b;i=generated_index[c];advance=widths['advances'][i]
        glyphs.append(source['glyphs'][i]);adv.append(advance);bounds.append(source['bounds'][i])
    prefix=bytearray(a['prefix']);prefix[2]|=8 # 32-bit offsets; existing name/flags otherwise unchanged.
    offset=(len(new_codes)+1)*4;offs=[]
    for g in glyphs:offs.append(offset);offset+=len(g)
    offs.append(offset)
    payload=bytes(prefix)+struct.pack('<H',len(new_codes))+b''.join(p32(o) for o in offs)+b''.join(glyphs)+struct.pack('<'+'H'*len(new_codes),*new_codes)+a['metrics']+struct.pack('<'+'h'*len(new_codes),*adv)+b''.join(bounds)+a['kern']
    check=font3(payload)
    count=len(a['codes'])
    for i,c in enumerate(a['codes']):
        j=check['codes'].index(c)
        assert check['glyphs'][j]==a['glyphs'][i]
        assert check['advances'][j]==a['advances'][i] and check['bounds'][j]==a['bounds'][i]
    assert check['metrics']==a['metrics'] and check['kern']==a['kern']
    return payload,dict(font=a['name'],original_glyphs=count,added_glyphs=len(added),original_shapes_exact=True,original_metrics_exact=True,
                        indices_changed=renumber,old_to_new={i:new_codes.index(c) for i,c in enumerate(a['codes'])})

def merge_fonts(original,generated,allow_reindex=False,advance_reference=None):
    prefix,tags=swf_tags(original);_,gt=swf_tags(generated)
    generated_fonts={struct.unpack_from('<H',p)[0]:p for c,p,_ in gt if c==75}
    reference_fonts={} if advance_reference is None else {
        struct.unpack_from('<H',p)[0]:p for c,p,_ in swf_tags(advance_reference)[1] if c==75}
    out=[];audit=[]
    for code,p,raw in tags:
        if code==75 and font_name(p) in {'PrototypeBodyPC','PrototypeSubtitle','PrototypeTitlePC'}:
            fid=struct.unpack_from('<H',p)[0]
            widths=reference_fonts[fid] if advance_reference is not None else None
            payload,info=merge_font3(p,generated_fonts[fid],allow_reindex,widths)
            out.append(struct.pack('<HI',(75<<6)|63,len(payload))+payload);audit.append(info)
        else:out.append(raw)
    result=bytearray(prefix+b''.join(out));result[4:8]=p32(len(result))
    swf_tags(result)
    return bytes(result),audit

def font_name(p):
    return p[5:5+p[4]].rstrip(b'\0').decode('ascii')

