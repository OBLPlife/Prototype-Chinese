"""Read/write only the English field of native AudioDialogueSubtitle objects."""
import struct
from resources import chunk, walk_chunks, u32

ENGLISH_FIELD = bytes.fromhex('bc8a33493c490709') + b'\x01\x07\0\0\0english\0'


def sized_string(data, offset):
    size = u32(data, offset)
    end = offset + 4 + size
    assert end < len(data) and data[end] == 0
    return data[offset+4:end].decode('utf-8'), end+1


def object_type(head):
    if len(head) < 21 or u32(head,12) != 10:
        return None
    return sized_string(head,16)[0]


def subtitle_field(head):
    name, p = sized_string(head,16)
    assert name == 'AudioDialogueSubtitle'
    version = u32(head,p); p += 4
    identifier,p = sized_string(head,p)
    positions = []
    offset = head.find(ENGLISH_FIELD,p)
    while offset >= 0:
        positions.append(offset)
        offset = head.find(ENGLISH_FIELD,offset+1)
    assert len(positions) == 1, (identifier,positions)
    start = positions[0] + len(ENGLISH_FIELD)
    text,end = sized_string(head,start)
    return dict(id=identifier,version=version,text=text,start=start,end=end)


def read_audio_subtitles(data):
    rows = []
    def visit(block,base=0):
        offset=0
        for kind,head,children,raw in walk_chunks(block):
            if kind == 0xfe000000 and object_type(head) == 'AudioDialogueSubtitle':
                row = subtitle_field(head)
                rows.append(dict(id=row['id'],version=row['version'],text=row['text'],chunk_offset=base+offset))
            if children:
                visit(children,base+offset+len(head))
            offset += len(raw)
    visit(data)
    return rows


def patch_audio_subtitles(data, translations):
    changes = []
    def visit(block):
        output=[]
        for kind,head,children,raw in walk_chunks(block):
            if kind == 0xfe000000 and object_type(head) == 'AudioDialogueSubtitle':
                row=subtitle_field(head)
                if row['id'] in translations:
                    source,zh=translations[row['id']]
                    assert row['text'] == source, row['id']
                    assert isinstance(zh,str) and '\0' not in zh
                    encoded=zh.encode('utf-8')
                    body=head[12:row['start']]+struct.pack('<I',len(encoded))+encoded+b'\0'+head[row['end']:]
                    output.append(chunk(kind,body,children))
                    changes.append(dict(id=row['id'],source=source,zh=zh))
                    continue
            rewritten=visit(children) if children else children
            output.append(raw if rewritten==children else chunk(kind,head[12:],rewritten))
        return b''.join(output)
    result=visit(data)
    assert len(changes)==len(translations)
    verify_audio_structure(data,result)
    return result,changes


def verify_audio_structure(original,translated):
    before=list(walk_chunks(original));after=list(walk_chunks(translated))
    assert len(before)==len(after)
    for (ka,ha,ca,ra),(kb,hb,cb,rb) in zip(before,after):
        assert ka==kb
        if ka==0xfe000000 and object_type(ha)=='AudioDialogueSubtitle':
            a,b=subtitle_field(ha),subtitle_field(hb)
            assert a['id']==b['id'] and a['version']==b['version']
            assert ha[12:a['start']]==hb[12:b['start']]
            assert ha[a['end']:]==hb[b['end']:]
            assert ca==cb
        elif ca or cb:
            assert ha[12:]==hb[12:]
            verify_audio_structure(ca,cb)
        else:
            assert ra==rb, 'Non-subtitle payload changed'
