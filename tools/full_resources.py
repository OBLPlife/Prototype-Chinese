"""Full catalog integration with positional subtitle identity and exact metadata checks."""
from resources import *
from inventory_all import holders

def short_encode(s):
    b=s.encode('ascii')+b'\0';n=(len(b)+3)//4*4
    if n>255:raise ValueError('ID too long')
    return bytes([n])+b.ljust(n,b'\0')

def patch_rows(data,rows,append=None):
    append=append or {};cursor=0;audit=[]
    def walk(d):
        nonlocal cursor
        out=[]
        for kind,h,c,raw in walk_chunks(d):
            if kind!=0x18202:
                out.append(chunk(kind,h[12:],walk(c) if c else b''));continue
            lang,p,langraw=short_name(h,12)
            if lang!='english':out.append(raw);continue
            ver,n=struct.unpack_from('<II',h,p);p+=8;keys=[];keybytes=b''
            for _ in range(n):key,p,kr=short_name(h,p);keys.append(key);keybytes+=kr
            starts=struct.unpack_from('<'+'I'*n,h,p);p+=4*n
            stops=struct.unpack_from('<'+'I'*n,h,p);p+=4*n;assert p==len(h)
            stores=list(walk_chunks(c));assert len(stores)==1 and stores[0][0]==0x18201
            _,sh,sc,_=stores[0];assert not sc
            _,q,sn=short_name(sh,12);sv,blen=struct.unpack_from('<II',sh,q);q+=8;blob=sh[q:];assert len(blob)==blen
            texts=[]
            for k,a,b in zip(keys,starts,stops):
                source=blob[a:b-1].decode('utf-8');row=rows[cursor]
                assert row['id']==k and row['text']==source,(cursor,k,source,row)
                zh=row['zh']
                for pattern in [r'%\d+:[A-Z][A-Z0-9_]*',r'\\[a-zA-Z]+']:
                    assert sorted(re.findall(pattern,source))==sorted(re.findall(pattern,zh)),(k,pattern,source,zh)
                audit.append(dict(ordinal=cursor,id=k,source=source,zh=zh));cursor+=1;texts.append(zh)
            for k,zh in append.items():
                assert k not in keys
                keys.append(k);keybytes+=short_encode(k);texts.append(zh)
            encoded=[t.encode('utf-8') for t in texts];pos=0;starts=[];stops=[]
            for t in encoded:starts.append(pos);pos+=len(t);stops.append(pos+1)
            store=chunk(0x18201,sn+struct.pack('<II',sv,pos)+b''.join(encoded))
            n=len(keys);hb=langraw+struct.pack('<II',ver,n)+keybytes+struct.pack('<'+'I'*n,*starts)+struct.pack('<'+'I'*n,*stops)
            out.append(chunk(kind,hb,store))
        return b''.join(out)
    new=walk(data);assert cursor==len(rows)
    check_structure(data,new,list(append))
    actual=holders(new);expected=[(r['id'],r['zh']) for r in rows]+list(append.items())
    assert [(r['id'],r['text']) for r in actual]==expected
    return new,audit

def check_structure(before,after,extra):
    a=list(walk_chunks(before));b=list(walk_chunks(after));assert len(a)==len(b)
    for (ka,ha,ca,ra),(kb,hb,cb,rb) in zip(a,b):
        assert ka==kb
        if ka==0x18202:
            lang,pa,_=short_name(ha,12);langb,pb,_=short_name(hb,12);assert lang==langb
            if lang!='english':assert ra==rb;continue
            va,na=struct.unpack_from('<II',ha,pa);vb,nb=struct.unpack_from('<II',hb,pb);assert va==vb
            assert nb==na+len(extra);pa+=8;pb+=8
            for _ in range(na):
                _,pa,ar=short_name(ha,pa);_,pb,br=short_name(hb,pb);assert ar==br
            for k in extra:actual,pb,_=short_name(hb,pb);assert actual==k
        else:
            assert ha[12:]==hb[12:]
            if ca or cb:check_structure(ca,cb,extra)

def tag_bytes(code,p):return struct.pack('<HI',(code<<6)|63,len(p))+p

def edit_text_parts(p):
    q=rect_end(p,2);f,g=p[q:q+2];q+=2
    if f&1:q+=2
    if g&128:q=p.index(0,q)+1
    if f&1:q+=2
    if f&4:q+=4
    if f&2:q+=2
    if g&32:q+=9
    q=p.index(0,q)+1
    if not f&128:return None
    end=p.index(0,q);assert end+1==len(p)
    return q,p[q:end].decode('utf-8')

def map_tags(data,fn):
    prefix,tags=swf_tags(data)
    def nested(tags):
        out=[]
        for code,p,raw in tags:
            changed=fn(code,p)
            if code==39:
                # Sprite's nested tag stream has a four-byte ID/frame-count header.
                fake=b'FWS\x08'+p32(len(p)+10)+b'\x08\x00\x00\x00\x01\x00'+p[4:]
                subprefix,sub=swf_tags(fake);new=p[:4]+nested(sub)
                if new!=p:changed=new
            out.append(raw if changed is None or changed==p else tag_bytes(code,changed))
        return b''.join(out)
    result=bytearray(prefix+nested(tags));result[4:8]=p32(len(result));swf_tags(result);return bytes(result)

def patch_gfx_labels(data,mapping):
    audit=[]
    def patch(code,p):
        if code!=37:return None
        parts=edit_text_parts(p)
        if parts is None:return None
        q,t=parts
        # Only text nodes; leave HTML markup, font names, variable names and actions unchanged.
        def translate(m):
            raw=m.group(0)
            if raw.startswith('<'):return raw
            stripped=raw.strip()
            if stripped not in mapping:return raw
            zh=mapping[stripped];audit.append(dict(id=struct.unpack_from('<H',p)[0],source=stripped,zh=zh))
            return raw.replace(stripped,zh)
        new=re.sub(r'<[^>]*>|[^<]+',translate,t)
        return p[:q]+new.encode('utf-8')+b'\0'
    return map_tags(data,patch),audit


def patch_upgrade_cost_bounds(data,restore=False):
    """Give the three upgrade price states room to extend left, without new code."""
    original=(-40,2220,-40,673)
    expanded=(-2980,2220,-40,673)
    expected,replacement=(expanded,original) if restore else (original,expanded)
    audit=[]
    def patch(code,p):
        if code!=37 or struct.unpack_from('<H',p)[0] not in {5,18,37}:return None
        end=rect_end(p,2);bits=''.join(f'{b:08b}' for b in p[2:end])
        n=int(bits[:5],2);values=[]
        for i in range(4):
            value=int(bits[5+i*n:5+(i+1)*n],2)
            values.append(value-(1<<n) if value&(1<<(n-1)) else value)
        assert tuple(values)==expected and n==13,(values,n)
        encoded=bits[:5]+''.join(f'{value&((1<<n)-1):0{n}b}' for value in replacement)+bits[5+4*n:]
        rect=int(encoded,2).to_bytes(end-2,'big')
        audit.append(dict(id=struct.unpack_from('<H',p)[0],before=list(original),after=list(expanded)))
        return p[:2]+rect+p[end:]
    changed=map_tags(data,patch)
    assert sorted(r['id'] for r in audit)==[5,18,37]
    assert len(changed)==len(data)
    return changed,audit
