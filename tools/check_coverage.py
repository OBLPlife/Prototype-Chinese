"""Join the independent full scan, editable catalog and built resource manifest."""
import argparse,collections,json,re
from pathlib import Path
import catalog
from render_text import render_text

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',required=True,type=Path);a=p.parse_args()
    scan_dir=catalog.ROOT.parents[1]/'work/PrototypeZh/complete-scan-20261113'
    def unique_pairs(pairs):
        result={}
        for key,value in pairs:
            assert key not in result,('Duplicate JSON key',key)
            result[key]=value
        return result
    for path in (catalog.ROOT/'catalog').rglob('*.json'):
        json.loads(path.read_text('utf8'),object_pairs_hook=unique_pairs)
    scan=json.loads((scan_dir/'scan.json').read_text('utf8'));assert not scan['errors']
    manifest=json.loads((a.work/'package/manifest.json').read_text('utf8'))
    resources=manifest['resources'];byasset={r['asset']:r for r in resources}
    previous=json.loads((a.work.parent/'build-0.2.3/package/manifest.json').read_text('utf8'))
    unchanged=0;changed=[]
    for old in previous['resources']:
        new=byasset[old['asset']];assert old['source_sha256']==new['source_sha256']
        if old['sha256']==new['sha256']:unchanged+=1
        else:
            assert new['kind']==old['kind'],('Resource purpose changed',new['asset'])
            assert new['kind'] in ('font','text','audio-subtitles','initial-ui-labels','save-ui-labels')
            changed.append(new['asset'])
            if new['kind'] in ('text','audio-subtitles'):
                # A translation revision may change the Chinese, while each
                # original record and its position must still be identical.
                identity=lambda r:(r.get('id'),r.get('source'))
                assert list(map(identity,new['changes']))==list(map(identity,old['changes']))
            if new['kind']=='text':
                assert new['appended_ids']==old['appended_ids']
    counts={};retained=[];aliases={}
    words={
      'ui':set('Xbox PS MB XMB PROTOTYPE Prototype Publishing Activision Inc Alienware Corporation tyo DNA BE HZ KNP Wolfenstein AE ENTER TAB CONNECT UBISOFT Ubisoft Connect START'.split()),
      'subtitles':set('DX DNA AE'.split()),
      'audio':set('DNA AE IDF MM GPS HUD FTL F-L-I-R CAO YY'.split())}
    controls=re.compile(r'%\d+:[A-Z][A-Z0-9_]*|\\[A-Za-z]+')
    for kind in ['ui','subtitles','audio']:
        rows,done,provenance=catalog.load(kind);assert len(rows)==len(done)
        aliases[kind]=0
        for i,row in enumerate(rows):
            zh=done[i];assert zh and '\0' not in zh
            assert sorted(controls.findall(row['text']))==sorted(controls.findall(zh)),(kind,i,'control sequence')
            remaining=set(re.findall(r'[A-Za-z]+(?:-[A-Za-z]+)*',controls.sub('',zh)))
            unexpected={w for w in remaining if len(w)>1 and w not in words[kind]}
            assert not unexpected,(kind,i,unexpected)
            if remaining:retained.append(dict(kind=kind,ordinal=i,id=row['id'],tokens=sorted(remaining)))
            aliases[kind]+=render_text(zh)!=zh
            if kind=='ui':
                targets=[byasset[n] for n in (r'\art\hud\textbible_english.p3d.rz',r'\art\hud\fe_textbible.p3d.rz')]
                for target in targets:
                    actual=target['changes'][i]
                    assert actual['id']==row['id'] and actual['source']==row['text'] and actual['zh']==render_text(zh)
            else:
                target=byasset[row['asset']]
                matches=[c for c in target['changes'] if c['id']==row['id'] and c['source']==row['text'] and c['zh']==render_text(zh)]
                assert matches,(kind,i,row['id'])
        counts[kind]=dict(original_rows=len(rows),mapped_rows=len(done),missing_rows=0,
                         coverage='all rows matched to built resource changes')
    assert counts['audio']['original_rows']==scan['counts']['audio_subtitle_rows']==14318
    assert counts['ui']['original_rows']*2+counts['subtitles']['original_rows']==scan['counts']['holder_rows']
    reported=next(c for r in resources if r['kind']=='audio-subtitles' for c in r['changes'] if c['id']=='7915_mabhk_014')
    assert reported['source']=="Ready to engage. Let's get some!"
    assert reported['zh']=='准备交战。给他们点厉害瞧瞧！'
    report=dict(passed=True,version=manifest['version'],archive_sha256=manifest['archive_sha256'],
        scan_files=scan['counts']['files'],scan_archives=len(scan['archives']),counts=counts,
        unique_catalog_rows=sum(c['original_rows'] for c in counts.values()),
        built_physical_text_rows=scan['counts']['holder_rows']+scan['counts']['audio_subtitle_rows'],
        reported_dialogue=reported,lua_direct_display_rows=manifest['lua_display_rows'],
        existing_nonfont_resources_unchanged=unchanged,changed_existing_resources=changed,
        name_dot_alias_rows=aliases,retained_latin_tokens=retained,
        retained_latin_policy='Real brands/company names, key names, scientific and military codes, call-sign letters, numeric labels and original MIX_TYPE_EVENTS=tyo. No untranslated dialogue sentence remains in these catalogs.',
        scope='Subtitles, menus and prompts. Environment texture lettering unchanged by user instruction.',
        runtime_verified=False,game_executed=False,
        limit='Resource coverage is not proof that every gameplay branch, subtitle layout or pause-menu transition has been exercised.')
    (a.work/'coverage-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='retained_latin_tokens'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
