"""Whole-package offline assertions; deliberately makes no runtime stability claim."""
import argparse,json,re,collections
from pathlib import Path
from resources import *
from full_resources import *
from inventory_all import holders
import catalog
import setup
from font_charset import full_gbk,MAPPING_SHA256
from render_text import render_text
from audio_dialogue import read_audio_subtitles,verify_audio_structure
from lua_display import verify_display
import subtitle_layout
from upgrade_row_layout import fit_upgrade_row

p=argparse.ArgumentParser();p.add_argument('--game',required=True,type=Path);p.add_argument('--work',required=True,type=Path);a=p.parse_args()
package=a.work/'package';manifest=json.loads((package/'manifest.json').read_text('utf-8'))
assert sha((package/'PrototypeZh.rcf').read_bytes())==manifest['archive_sha256']
runtime=manifest['runtime_support']
assert runtime['file']=='XInput1_3.dll' and sha((package/runtime['file']).read_bytes())==runtime['sha256']
assert (runtime['constructor_rva'],runtime['heap_id_rva'],runtime['original_heap_id'],runtime['native_heap_id'])==(0x9615c0,0x9615d7,0x72,0)
assert runtime['engine_file_modified'] is False and runtime['modern_dependency'] is False
assert setup.runtime_spec(manifest)['font_buffers']==setup.FONT_BUFFER_SUPPORT
assert setup.runtime_spec(manifest)['font_lookup']==setup.FONT_LOOKUP_SUPPORT
assert manifest['character_set']['mapping_sha256']==MAPPING_SHA256
needed=(a.work/'chars.txt').read_text('utf-8')
assert full_gbk()<=set(needed) and len(needed)==manifest['required_characters']
weights=manifest.get('cjk_face_weights')
if weights:
    font_sources=json.loads((catalog.ROOT/'catalog/font-sources.json').read_text('utf-8'))
    assert weights==font_sources['cjk_faces']
    assert set(manifest['font_donors'])==set(weights.values())
    for weight,donor in manifest['font_donors'].items():
        path=catalog.ROOT.parents[1]/'vendor'/f'NotoSansCJKsc-{weight}.otf'
        assert donor['weight']==weight and sha(path.read_bytes())==donor['source_sha256']==font_sources['cjk_source_sha256'][weight]
modern=json.loads((catalog.ROOT/'catalog/policy.json').read_text('utf-8'))['modern_labels']
modernroot=catalog.ROOT.parent/'PrototypeModern/src'
source=(modernroot/'display_text.h').read_text('utf-8');as2=(modernroot/'display_menu.as').read_text('utf-8')
assert source.index('nativeTextQuery(key)')<source.index('entry.english')
for k in modern:assert '"'+k+'"' in source and '"$'+k+'"' in as2
assert '"FormatText",key' in as2
for x in ['mValue:0','mValue:1','mValue:2']:assert x in as2
stats=collections.Counter();assets=[]
for r in manifest['resources']:
    original=rcf_read(a.game/r['archive'],r['asset']);new=rcf_read(package/'PrototypeZh.rcf',r['asset'])
    assert sha(original)==r['source_sha256'] and sha(new)==r['sha256']
    if r['kind']=='text':
        aa=unpack_rz(original);bb=unpack_rz(new);check_structure(aa,bb,r['appended_ids'])
        old=holders(aa);translated=holders(bb)
        assert len(translated)==len(old)+len(r['appended_ids'])
        for i,(o,t) in enumerate(zip(old,translated)):
            ch=r['changes'][i];assert o['id']==t['id']==ch['id'] and o['text']==ch['source'] and t['text']==ch['zh']
            assert o['holder_ordinal']==t['holder_ordinal']
        if r['appended_ids']:assert {t['id']:t['text'] for t in translated[-len(r['appended_ids']):]}=={**modern,**manifest['native_display_labels']}
        stats['original_text_rows']+=len(old);stats['text_assets']+=1
    if r['kind']=='audio-subtitles':
        aa,bb=unpack_rz(original),unpack_rz(new)
        verify_audio_structure(aa,bb)
        before,after=read_audio_subtitles(aa),read_audio_subtitles(bb)
        assert len(before)==len(after)==len(r['changes'])
        for x,y,c in zip(before,after,r['changes']):
            assert x['id']==y['id']==c['id'] and x['text']==c['source'] and y['text']==c['zh']
        stats['audio_subtitle_rows']+=len(after);stats['audio_subtitle_assets']+=1
    if r['kind']=='lua-display':
        verify_display(unpack_rz(original),unpack_rz(new),r['changes'])
        stats['lua_display_rows']+=len(r['changes']);stats['lua_display_assets']+=1
    if r['kind'] in ['initial-ui-labels','save-ui-labels']:
        if 'upgrade_core_layout' in r:
            assert r['asset']==r'\art\hud\protopowerpurchase.gfx' and r['upgrade_core_layout'] in (1,2)
            new=fit_upgrade_row(new,restore=True,revision=r['upgrade_core_layout'])
        if 'upgrade_cost_bounds' in r:
            assert r['asset']==r'\art\hud\protopowerpurchase.gfx'
            new,bounds_audit=patch_upgrade_cost_bounds(new,restore=True)
            assert bounds_audit==r['upgrade_cost_bounds']
            stats['upgrade_cost_fields']=len(bounds_audit)
        if 'subtitle_layout' in r:
            layout=r['subtitle_layout']
            code,compiled=subtitle_layout.read_actions(a.work/'subtitle-layout')
            basename=r['asset'].split('\\')[-1]
            expected=subtitle_layout.LOCATIONS[basename]
            assert sorted((x['name'],x['sprite_id'],x['frame']) for x in layout['insertions'])==sorted(expected)
            for record in layout['insertions']:
                name=record['name']
                assert record['actions_sha256']==sha(code[name]) and record['action_bytes']==len(code[name])
                assert layout['sources'][name]==compiled[name]
                assert sha(subtitle_layout.SOURCES[name].read_bytes())==compiled[name]['source_sha256']
            new=subtitle_layout.strip_actions(new,layout)
            assert layout['original_actions_unchanged'] and layout['original_geometry_and_timelines_unchanged']
            assert layout['event_driven'] and not layout['per_frame_polling']
            stats['subtitle_layout_movies']+=1
            stats['subtitle_layout_actions']+=len(layout['insertions'])
        def flatten(d):
            all=[]
            def visit(code,p):
                if code!=39:all.append((code,p))
            map_tags(d,visit);return all
        if r['kind']=='save-ui-labels':
            code=(a.work/'save-labels/save-labels.avm1').read_bytes()
            assert sha(code)==r['save_labels']['actions_sha256']
            prefix,tags=swf_tags(new);matches=[i for i,(c,p,_) in enumerate(tags) if c==12 and p==code]
            assert len(matches)==1 and tags[matches[0]+1][0]==1
            reconstructed=bytearray(prefix+b''.join(raw for i,(_,_,raw) in enumerate(tags) if i!=matches[0]))
            reconstructed[4:8]=p32(len(reconstructed));new=bytes(reconstructed)
            assert r['save_labels']['save_files_modified'] is False
            stats['save_caption_mappings']=len(r['save_labels']['mapping'])
        before=flatten(original);after=flatten(new);assert len(before)==len(after)
        for (ca,pa),(cb,pb) in zip(before,after):
            assert ca==cb
            if ca==37 and pa!=pb:
                qa,_=edit_text_parts(pa);qb,_=edit_text_parts(pb);assert qa==qb and pa[:qa]==pb[:qb]
            else:assert pa==pb
        stats['gfx_movies']+=1;stats['gfx_fields']+=len(r['changes'])
    if r['kind']=='credits':
        old=original.decode('utf-8').splitlines(keepends=True);translated=new.decode('utf-8').splitlines(keepends=True)
        assert len(old)==len(translated)
        changed={x['line'] for x in r['changes']}
        for i,(o,t) in enumerate(zip(old,translated)):
            if i not in changed:assert o==t
            if o.startswith(' '):assert o==t
            assert re.findall(r'\r?\n',o)==re.findall(r'\r?\n',t)
        stats['credit_heading_lines']=len(changed);stats['credit_unchanged_nonempty_lines']=len(r['preserved_lines'])
    if r['kind']=='font':
        if weights: assert r['cjk_advance_weight']=='Regular'
        assert len(new)<=manifest['font_file_budget']==0x2000000
        assert r['asset'] in runtime['font_buffers']['assets']
        assert manifest['native_temporary_heap_bytes']==0x200000
        classic=(a.work/('classic-'+r['asset'].split('\\')[-1])).read_bytes()
        assert sha(classic)==r['classic_sha256']
        compact_dir=a.work/('compact-'+r['asset'].split('\\')[-1])
        assert r['compact_validation']==json.loads((compact_dir/'validation.json').read_text('utf-8'))
        assert r['compact_validation']['outlines_exact'] and r['compact_validation']['metrics_exact']
        assert r['compact_validation']['kerning_exact']
        assert r['compact_validation']['bounds_from_outlines'] and r['compact_validation']['updated_bounds']>0
        assert r['compact_validation']['contours_losslessly_shared']
        assert r['compact_validation']['shared_contours']>0 and r['compact_validation']['saved_edge_bytes']>0
        oldtags=swf_tags(classic)[1];newtags=swf_tags(new)[1];assert len(oldtags)==len(newtags)
        for (c,p,raw),(nc,np,nraw) in zip(oldtags,newtags):
            if c==75 and font_name(p) in ['PrototypeBodyPC','PrototypeSubtitle','PrototypeTitlePC']:
                f=font3(p);assert nc==1005 and np==(compact_dir/('font-'+str(f['id'])+'.bin')).read_bytes()
                end=np.index(0,2);assert np[2:end].decode('ascii')==f['name']
                flags,nominal,asc,desc,lead,count,nbytes=struct.unpack_from('<HHhhhII',np,end+1)
                assert nominal==2048 and count==len(f['codes'])
                assert struct.pack('<hhh',asc*20,desc*20,lead*20)==f['metrics']
                table=end+1+18+nbytes
                entries=[struct.unpack_from('<HhI',np,table+i*8) for i in range(count)]
                assert [v[0] for v in entries]==f['codes'] and [v[1]*10 for v in entries]==f['advances']
            else:assert raw==nraw
        orig={font_name(p):font3(p) for c,p,_ in swf_tags(original)[1] if c==75}
        samples={}
        for c,p,_ in swf_tags(classic)[1]:
            if c!=75:continue
            f=font3(p);o=orig[f['name']]
            if f['name'] not in ['PrototypeBodyPC','PrototypeSubtitle','PrototypeTitlePC']:assert f==o;continue
            assert f['codes']==sorted(set(f['codes'])) and f['metrics']==o['metrics'] and f['kern']==o['kern']
            for i,code in enumerate(o['codes']):
                j=f['codes'].index(code)
                for key in ['glyphs','advances','bounds']:assert f[key][j]==o[key][i]
            available=set(f['codes']);assert all(ord(c) in available for c in needed)
            if weights:
                samples[f['name']]=tuple(f['glyphs'][f['codes'].index(ord(char))] for char in '玻笼进点')
            stats['font_sets']+=1
        if weights:
            assert set(samples)==set(weights) and len(set(samples.values()))==len(set(weights.values()))
    assets.append(r['asset'])
assert len(assets)==len(set(assets)) and r'\art\hud\protolist.gfx' not in assets
assert stats['original_text_rows']==3127*2+957 and stats['text_assets']==190 and stats['font_sets']==6
assert stats['audio_subtitle_rows']==manifest['audio_subtitle_rows']==14318
assert stats['audio_subtitle_assets']==manifest['audio_subtitle_assets']==14318
assert stats['lua_display_rows']==manifest['lua_display_rows']==18
assert stats['lua_display_assets']==manifest['lua_display_assets']==5
if runtime.get('subtitles')==setup.SUBTITLE_SUPPORT:
    assert stats['subtitle_layout_movies']==2 and stats['subtitle_layout_actions']==4
report=dict(passed=True,counts=dict(stats),
    archive_sha256=manifest['archive_sha256'],runtime_sha256=runtime['sha256'],
    checks=['all original English UI/subtitle rows mapped positionally including duplicate IDs',
    'all original IDs, other languages, subtitle timing and non-text P3D metadata exact',
    '14318 AudioDialogueSubtitle bodies translated; encoded audio and non-English data byte-exact',
    '18 direct Lua display constants translated or routed through nine new native text IDs; byte lengths, instructions and all FIG offsets unchanged',
    'four Modern keys in both UI bibles; native query has priority over English fallback',
    'GFX original actions and serialized text geometry/font bindings/render flags unchanged; save-caption action and four exact removable subtitle-layout actions verified separately; subtitle position/height change only through these event-driven actions',
    'all credit names and company-only lines unchanged, with original newlines',
    'six font sets cover every required character; original Latin outlines and layout metrics exact',
    'complete GBK/CP936 glyph repertoire plus used characters in all six fonts; both font resources have paired native system-heap buffer support and stay below the reviewed 32 MiB per-file bound',
    'compact fonts preserve every contour, code, advance and kerning pair; stored bounds are recomputed from true outline extrema rather than copying classic placeholder rectangles',
    'old control-side label bridge absent'],
    runtime_verified=False,game_executed=False)
(a.work/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
