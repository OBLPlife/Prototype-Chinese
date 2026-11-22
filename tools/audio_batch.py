"""Show unresolved unique audio dialogue with stable source ordinals."""
import argparse,collections,json,re
import catalog

p=argparse.ArgumentParser();p.add_argument('--group');p.add_argument('--limit',type=int,default=160);a=p.parse_args()
rows,done,_=catalog.load('audio');seen=set();pending=[]
for i,r in sorted(enumerate(rows),key=lambda pair:int(pair[1]['id'].split('_')[0]) if pair[1]['id'].split('_')[0].isdigit() else 0):
    if i in done:continue
    group=r['id'].split('_')[1] if '_' in r['id'] else r['id']
    if a.group and group!=a.group:continue
    if r['text'] in seen:continue
    seen.add(r['text']);pending.append((i,r))
for i,r in pending[:a.limit]:print(i,r['id'],json.dumps(r['text'],ensure_ascii=False))
print('PENDING UNIQUE IN SELECTION',len(pending),'AUDIO RECORDS TRANSLATED',len(done),'OF',len(rows))
