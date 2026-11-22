"""Translate audited display-only Lua constants without relocating FIG data.

The native FIG wrapper also contains offsets and unrelated object data. Selected
Chinese strings or native $text IDs have exactly the original byte length, so all Lua lengths,
constant indices, instructions, FIG offsets and P3D headers remain untouched.
New text IDs may end in underscores to preserve the binary length; those IDs are
resolved by the original text system and are never displayed as padding.
No script evaluation, hooks or game logic changes are used.
"""
from audit_lua_context import parse

def patch_display(data,rows):
    out=bytearray(data);changes=[]
    for row in rows:
        at=row['lua_offset'];functions,used=parse(data[at:]);matches=[]
        for f in functions:
            for index,start,end in f['string_spans']:
                if f['constants'][index]==row['source']:matches.append((at+start,at+end))
        assert len(matches)==1,('Ambiguous display literal',row,matches)
        begin,end=matches[0];replacement=row.get('replacement',row['zh']);encoded=replacement.encode('utf8')
        assert len(encoded)==end-begin,('Native FIG offsets must remain fixed',row)
        assert b'\0' not in encoded and data[begin:end].decode('utf8')==row['source']
        out[begin:end]=encoded
        changes.append(dict(offset=begin,bytes=len(encoded),source=row['source'],zh=row['zh'],replacement=replacement,
                            lua_offset=at,lua_bytes=used))
        after,n=parse(bytes(out[at:]));assert n==used
        for old,new in zip(functions,after):
            assert old['instructions']==new['instructions'] and old['string_spans']==new['string_spans']
    result=bytes(out)
    verify_display(data,result,changes)
    return result,changes

def verify_display(original,translated,changes):
    assert len(original)==len(translated)
    restored=bytearray(translated)
    for row in changes:
        begin=row['offset'];end=begin+row['bytes']
        assert original[begin:end].decode('utf8')==row['source']
        assert translated[begin:end].decode('utf8')==row.get('replacement',row['zh'])
        restored[begin:end]=original[begin:end]
        old,n=parse(original[row['lua_offset']:]);new,m=parse(translated[row['lua_offset']:])
        assert n==m==row['lua_bytes'] and len(old)==len(new)
        for a,b in zip(old,new):assert a['instructions']==b['instructions']
    assert bytes(restored)==original,'Non-display byte changed'
