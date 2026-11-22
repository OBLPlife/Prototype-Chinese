"""Read-only Lua 5.1 constant-use audit; never executes game scripts."""
import json,struct
from pathlib import Path
from resources import rcf_read,unpack_rz
OPS='MOVE LOADK LOADBOOL LOADNIL GETUPVAL GETGLOBAL GETTABLE SETGLOBAL SETUPVAL SETTABLE NEWTABLE SELF ADD SUB MUL DIV MOD POW UNM NOT LEN CONCAT JMP EQ LT LE TEST TESTSET CALL TAILCALL RETURN FORLOOP FORPREP TFORLOOP SETLIST CLOSE CLOSURE VARARG'.split()

def parse(data):
    assert data[:12]==b'\x1bLuaQ\0\1\4\4\4\4\0'
    p=12;functions=[]
    def num():
        nonlocal p
        n=struct.unpack_from('<I',data,p)[0];p+=4;return n
    def string():
        nonlocal p
        n=num()
        if not n:return ''
        assert data[p+n-1]==0
        s=data[p:p+n-1].decode('utf8');p+=n;return s
    def fn(parent):
        nonlocal p
        src=string() or parent;start,end=num(),num();p+=4
        ins=[num() for _ in range(num())];ks=[];spans=[]
        for _ in range(num()):
            kind=data[p];p+=1
            if kind==0:ks.append(None)
            elif kind==1:ks.append(bool(data[p]));p+=1
            elif kind==3:ks.append(struct.unpack_from('<f',data,p)[0]);p+=4
            elif kind==4:
                begin=p+4;ks.append(string());spans.append((len(ks)-1,begin,p-1))
            else:raise ValueError(kind)
        rec=dict(source=src,start=start,end=end,constants=ks,instructions=ins,string_spans=spans);functions.append(rec)
        for _ in range(num()):fn(src)
        nlines=num();p+=4*nlines
        for _ in range(num()):string();p+=8
        for _ in range(num()):string()
    fn('');return functions,p

def disasm(rec):
    ks=rec['constants'];out=[]
    def k(i):return repr(ks[i]) if i<len(ks) else 'BAD_K'+str(i)
    def rk(i):return k(i-256) if i>=256 else 'R'+str(i)
    for i,w in enumerate(rec['instructions']):
        op=w&63;a=(w>>6)&255;c=(w>>14)&511;b=(w>>23)&511;bx=w>>14
        desc=f'{i:04} {OPS[op] if op<len(OPS) else "OP"+str(op)} R{a} '
        refs=[]
        if op in [1,5,7]:desc+=k(bx);refs=[bx]
        elif op in [6,9,11,12,13,14,15,16,17,23,24,25]:
            desc+=rk(b)+' '+rk(c);refs=[v-256 for v in [b,c] if v>=256]
        else:desc+=f'B={b} C={c}'
        out.append((desc,refs))
    return out

def main():
    SCAN=Path(__file__).resolve().parents[3]/'work/PrototypeZh/complete-scan-20261113'
    natural=json.loads((SCAN/'native-lua-natural-strings.json').read_text('utf8'))
    wanted={r['text']:i for i,r in enumerate(natural)}
    entries=json.loads((SCAN/'embedded-lua.json').read_text('utf8'))
    game=Path(r'D:\Software\Steam\steamapps\common\Prototype');last=None;results=[]
    for row in entries:
        key=(row['archive'],row['asset'])
        if key!=last:raw=unpack_rz(rcf_read(game/key[0],key[1]));last=key
        functions,used=parse(raw[row['offset']:])
        for f in functions:
            ds=disasm(f)
            for ki,s in enumerate(f['constants']):
                if not isinstance(s,str) or s not in wanted:continue
                uses=[i for i,(_,refs) in enumerate(ds) if ki in refs]
                context=sorted({j for i in uses for j in range(max(0,i-7),min(len(ds),i+9))})
                results.append(dict(index=wanted[s],text=s,**row,source=f['source'],line=f['start'],
                    constant_index=ki,context=[ds[j][0] for j in context]))
    (SCAN/'lua-use-context.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    print('Audited',len(entries),'Lua blobs;',len(results),'natural constant occurrences')
    select={110,112,164,184,260,277,278,326,328,329,352,367,368,369,373,399,445,567,570,589,606,607}
    for r in results:
        if r['index'] in select:
            print(r['index'],r['asset'],r['source'],r['line'],repr(r['text']))
            print('\n'.join(r['context']))
if __name__=='__main__':main()
