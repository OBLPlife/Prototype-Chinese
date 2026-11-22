"""Disk-side counterparts of native_subtitles.h's supported-code guards."""
import struct

LEGACY_SUBTITLE_SUPPORT=dict(update_call_rva=0x8649df,objective_call_rva=0x4d1954,
    independent_expiry=True,chronological_stacking=True,native_nodes_and_cleanup=True,
    shared_ui_resource_modified=False,per_frame_ui_rebuild=False)
SUBTITLE_SUPPORT=dict(LEGACY_SUBTITLE_SUPPORT,objective_visibility_refresh=True,
    shared_ui_resource_modified=True,event_driven_objective_layout=True)
SIGNATURES=[
    (0x876b60,0x5e2,0x6afa7a2a,[0xb0,0x14d,0x167,0x1e4,0x24d,0x2b4,0x2dc,0x2e2,0x301,0x30a,0x34c,0x352,0x357,0x376,0x3b9,0x413,0x483,0x4a4,0x561]),
    (0x8649c8,0x1c,0xff9721ed,[2]),
    (0x4d1940,0x61,0x452a3a51,[0xe,0x2d,0x34,0x3a,0x3f]),
    (0x864330,6,0x110b30ff,[1]),(0x872830,8,0xae12e592,[]),
    (0x885820,0x229,0x76cf0bd6,[0x9c,0xe0,0x122,0x204]),
    (0x63ced0,0x42,0x0411114d,[9,0xf,0x15]),(0x63b990,0x1c,0x467cfab1,[]),
    (0x641130,0x166,0xd827c966,[0x79]),(0x7defd0,0xf,0x26ddfa54,[2])]

def check_signatures(data,image_base,table,sections):
    for target,size,expected,relocations in SIGNATURES:
        matches=[]
        for i in range(sections):
            _,rva,raw_size,offset=struct.unpack_from('<IIII',data,table+i*40+8)
            if rva<=target and target+size<=rva+raw_size:matches.append(offset+target-rva)
        if len(matches)!=1 or matches[0]+size>len(data):raise ValueError('Incomplete subtitle code mapping')
        code=bytearray(data[matches[0]:matches[0]+size])
        for offset in relocations:
            value=struct.unpack_from('<I',code,offset)[0]
            struct.pack_into('<I',code,offset,(value-image_base+0x10000000)&0xffffffff)
        digest=2166136261
        for value in code:digest=((digest^value)*16777619)&0xffffffff
        if digest!=expected:raise ValueError(f'Engine subtitle signature mismatch at RVA {target:08x}')
