"""Translation catalog, tied to immutable original rows and retaining every ordinal."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT.parents[1]/'exa-results/prototype-2009-2026-11-12/evidence'
FILES={'ui':'english_text_inventory.json','subtitles':'english_subtitles.json',
       'audio':ROOT.parents[1]/'work/PrototypeZh/complete-scan-20261113/audio-subtitles.json'}
BUTTON_TERMS={
 'IN MILITARY DISGUISE':'军人伪装状态','TARGET ENEMY':'锁定敌人','IN CRITICAL MASS':'临界状态',
 'HOLDING ENEMY IN AIR':'在空中抓着敌人','LAUNCHED BY ENEMY ATTACK':'被敌人攻击击飞时','WHILE IN AIR':'在空中',
 'CONNECT WITH TARGET':'命中目标','FROM AIR COMBO':'空中连击后','FROM WALLRUN':'沿墙奔跑时',
 'HOLDING OBJECT':'持有物体','HOLDING HUMAN':'抓着人类','DOWNED OPPONENT':'敌人倒地时',
 'GRAB HELICOPTER':'抓住直升机','GRAB VEHICLE':'抓住载具','GRAB OBJECT':'抓住物体','STUN HUNTER':'击晕猎人',
 'ON HUMAN':'锁定人类','UPPERCUT':'上勾拳','IN AIR':'在空中','AWAY':'远离目标方向','GLIDE':'滑翔时',
 'HOLD':'按住','PRESS':'按下','CLAWS':'利爪','BLADE':'利刃','MUSCLEMASS':'超能肌肉',
 'HAMMERFIST':'重锤','WHIPFIST':'鞭拳','SHIELD':'护盾','ARMOR':'装甲','THERMAL VISION':'热成像视野',
 'INFECTED VISION':'感染者视野','DISGUISE':'伪装','AGAINST WALL':'贴墙时','DIRECTIONAL':'方向',
 'or':'或','WHILE GRABBING A HUNTER':'抓着猎人时','REACH MAXIMUM HEALTH':'生命值达到上限',
 'GAIN ADDITIONAL HEALTH':'继续获得生命值','BEHIND HUMAN':'在人类身后',
 'DOUBLE-TAP + RELEASE':'连按两次后松开','DOUBLE-TAP + HOLD':'连按两次并按住',
 'any MOVEMENT key':'任意移动键','and use the':'并使用','to select':'选择','twice':'重复两次'
}

def button_translation(text):
    placeholders={}
    def hold(m):
        token='§'+str(len(placeholders))+'§';placeholders[token]=m.group();return token
    out=re.sub(r'%\d+:[A-Z][A-Z0-9_]*',hold,text)
    for en,zh in sorted(BUTTON_TERMS.items(),key=lambda x:-len(x[0])):
        out=re.sub(r'(?<![A-Za-z])'+re.escape(en)+r'(?![A-Za-z])',lambda m:zh,out)
    if re.search('[A-Za-z]',out):return None
    for token,value in placeholders.items():out=out.replace(token,value)
    return out

def load(kind):
    source = ROOT.parents[1] / 'work/PrototypeZh/english-catalog' / Path(FILES[kind]).name
    if not source.is_file():
        source = EVIDENCE / FILES[kind]
    rows=json.loads(source.read_text('utf-8'));done={};provenance={}
    for f in sorted((ROOT/'catalog'/kind).glob('*.json')):
        for number,zh in json.loads(f.read_text('utf-8')).items():
            i=int(number)
            if i in done:raise ValueError(f'Duplicate translation ordinal {kind}:{i}')
            if not isinstance(zh,str):raise ValueError('Translation must be text')
            done[i]=zh;provenance[i]=str(f.relative_to(ROOT))
    # Identical source text reuse, with explicit per-ID entries taking precedence.
    known={}
    for i,t in done.items():known.setdefault(rows[i]['text'],set()).add(t)
    for i,r in enumerate(rows):
        if i in done:continue
        if len(known.get(r['text'],[]))==1:
            done[i]=next(iter(known[r['text']]));provenance[i]='identical-source-reuse'
        elif not re.search('[A-Za-z\u00c0-\u024f]',re.sub(r'%\d+:[A-Z][A-Z0-9_]*','',r['text'])):
            done[i]=r['text'];provenance[i]='numeric-symbol-control-only'
        elif kind=='ui' and '_Bttn' in r['id'] and (zh:=button_translation(r['text'])) is not None:
            done[i]=zh;provenance[i]='reviewed-input-phrase-template'
    return rows,done,provenance

def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=FILES);p.add_argument('--start',type=int,default=0);p.add_argument('--end',type=int);p.add_argument('--pending',action='store_true');a=p.parse_args()
    rows,done,_=load(a.kind)
    for i in range(a.start,min(a.end or len(rows),len(rows))):
        if a.pending and i in done:continue
        print(i,rows[i]['id'],json.dumps(rows[i]['text'],ensure_ascii=False))
    print('TRANSLATED',len(done),'TOTAL',len(rows),'MISSING',len(rows)-len(done))

if __name__=='__main__':main()
