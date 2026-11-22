"""Localize existing save-slot captions at display time, without writing saves."""
import json,subprocess,struct
from pathlib import Path
from resources import swf_tags,p32,sha
from full_resources import tag_bytes
from avm1_literals import inline_constants


def save_mapping(rows):
    keys={'STORY_COMPLETE_NAME','DefaultDataSlotName','NewDataSlot','SlotCorrupted',
          'DIFFICULTY_1','DIFFICULTY_2','DIFFICULTY_3'}
    return {r['text'].upper():r['id'] for r in rows
            if r['id'].endswith('_MISSION_NAME') or r['id'] in keys}


def make_actions(work,ffdec,rows):
    mapping=save_mapping(rows);work.mkdir(parents=True,exist_ok=True)
    source='var zhSaveLabels = new Object();\n'+''.join(
        'zhSaveLabels['+json.dumps(text)+'] = '+json.dumps(key)+';\n' for text,key in mapping.items())+'''
function ZhSavedCaption(value) {
    if (typeof(value) != "string") return value;
    var first = 0;
    var last = value.length;
    while (first < last && value.charAt(first) == " ") first++;
    while (last > first && value.charAt(last - 1) == " ") last--;
    var core = value.substring(first,last);
    var key = zhSaveLabels[core.toUpperCase()];
    if (key == undefined) return value;
    return value.substring(0,first) + _global.gLoc.Loc("$" + key) + value.substring(last);
}
// Original Initialize01 has already read and indexed these entries. Only
// their display strings change; slot indices, dates and save callbacks remain.
for (var zhSlot = 0; zhSlot < mSlotInfo.length; zhSlot++) {
    mSlotInfo[zhSlot].episode = ZhSavedCaption(mSlotInfo[zhSlot].episode);
    mSlotInfo[zhSlot].difficulty = ZhSavedCaption(mSlotInfo[zhSlot].difficulty);
}
'''
    scripts=work/'scripts/frame_1';scripts.mkdir(parents=True,exist_ok=True)
    (scripts/'DoAction.as').write_text(source,encoding='utf-8')
    body=b'\x08\x00'+struct.pack('<HH',24*256,1)+tag_bytes(12,b'\0')+tag_bytes(1,b'')+tag_bytes(0,b'')
    blank=work/'blank.swf';blank.write_bytes(b'FWS\x08'+p32(len(body)+8)+body)
    compiled=work/'compiled.swf'
    result=subprocess.run(['java','-Djava.awt.headless=true','-jar',str(ffdec),'-importScript',str(blank),str(compiled),str(work/'scripts')],capture_output=True)
    (work/'compile.log').write_bytes(result.stdout+result.stderr);result.check_returncode()
    actions=[p for c,p,_ in swf_tags(compiled.read_bytes())[1] if c==12];assert len(actions)==1
    code=inline_constants(actions[0]);(work/'save-labels.avm1').write_bytes(code)
    return code,dict(mapping=mapping,actions_sha256=sha(code),save_files_modified=False,
                     native_query='FormatText via _global.gLoc.Loc',original_actions_unchanged=True)


def append_actions(movie,code):
    prefix,tags=swf_tags(movie);out=[];done=False
    for c,p,raw in tags:
        if c==1 and not done:out.append(tag_bytes(12,code));done=True
        out.append(raw)
    assert done
    result=bytearray(prefix+b''.join(out));result[4:8]=p32(len(result));return bytes(result)
