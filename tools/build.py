"""Build the complete text catalog into an independent native archive."""
import argparse,json,shutil,subprocess,collections,re
from pathlib import Path
from resources import *
from full_resources import *
import catalog
from font_cjk_quadratic import make_donor
from render_text import render_text
from font_charset import build_characters
from save_labels import make_actions,append_actions
import subtitle_layout
from upgrade_row_layout import fit_upgrade_row
from audio_dialogue import patch_audio_subtitles
from lua_display import patch_display
from setup import FONT_LOOKUP_SUPPORT,FONT_KERNING_SUPPORT,SUBTITLE_SUPPORT
from subtitle_capture_support import CAPTURE_SUPPORT
ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parents[1]
VERSION='0.2.13-font-weights'
FONT_FILE_BUDGET=0x2000000  # 32 MiB per GBK font resource, routed as a paired system-heap buffer.
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def build_native_support(work,package):
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:raise RuntimeError('PowerShell is required to compile the native text-memory support')
    output=work/'runtime'
    subprocess.run([shell,'-NoProfile','-File',str(ROOT/'tools/build_runtime.ps1'),'-Output',str(output.resolve())],check=True)
    runtime=output/'XInput1_3.dll'
    shutil.copy2(runtime,package/runtime.name)
    return dict(file=runtime.name,sha256=sha(runtime.read_bytes()),
        constructor_rva=0x9615c0,heap_id_rva=0x9615d7,original_heap_id=0x72,native_heap_id=0,
        purpose='Original GFx allocator uses existing engine system heap; no allocator rewrite',
        font_buffers=dict(alloc_call_rva=0x95c6d4,free_call_rva=0x95c799,original_heap_id=1,native_heap_id=0,
            assets=[r'\art\hud\fonts_latin.gfx',r'\art\hud\gfxfontlib.gfx'],
            paired_release=True,other_resources_unchanged=True),
        font_lookup=dict(FONT_LOOKUP_SUPPORT),
        font_kerning=dict(FONT_KERNING_SUPPORT),
        subtitles=dict(SUBTITLE_SUPPORT),
        subtitle_capture=dict(CAPTURE_SUPPORT),
        engine_file_modified=False,modern_dependency=False)

def credits_translate(original,mapping):
    lines=original.decode('utf-8').splitlines(keepends=True);result=[];audit=[];preserved=[]
    companies={'ACTIVISION','ACTIVISION PUBLISHING','BEENOX','DEMONWARE','IRON GALAXY STUDIOS'}
    for i,line in enumerate(lines):
        text=line.rstrip('\r\n');key=text.strip()
        if key and not text.startswith(' ') and key in mapping:
            new=text.replace(key,mapping[key]);result.append(new+line[len(text):]);audit.append(dict(line=i,source=key,zh=mapping[key]))
        else:
            assert not key or text.startswith(' ') or key in companies or key.startswith(('LOGO:','$')),('Unreviewed credit heading',i,key)
            result.append(line)
            if key:preserved.append(dict(line=i,text=text))
    new=''.join(result).encode('utf-8');after=new.decode('utf-8').splitlines();assert len(after)==len(lines)
    for row in preserved:assert after[row['line']]==row['text']
    return new,audit,preserved

def build_fonts(work,game,chars,add):
    charsfile=work/'chars.txt';charsfile.write_text(chars,encoding='utf-8')
    spec=json.loads((ROOT/'catalog/font-sources.json').read_text('utf-8'))
    weights=spec['cjk_faces']
    donors={}
    donor_audit={}
    for weight in dict.fromkeys(weights.values()):
        source=WORKSPACE/'vendor'/f'NotoSansCJKsc-{weight}.otf'
        source_sha=sha(source.read_bytes())
        if source_sha!=spec['cjk_source_sha256'][weight]:
            raise ValueError(f'Unexpected donor font: {source.name}')
        donors[weight]=work/f'PrototypeZhCJK-{weight}-Quadratic.ttf'
        info=make_donor(source,chars,donors[weight],weight)
        donor_audit[weight]=dict(info,weight=weight,source_sha256=source_sha)
    font_audit=[]
    classes=work/'classes';classes.mkdir(exist_ok=True);libs=WORKSPACE/'vendor/ffdec_26.4.0/lib/*'
    subprocess.run(['javac','-encoding','UTF-8','-cp',str(libs),'-d',str(classes),str(ROOT/'tools/EmbedChinese.java'),str(ROOT/'tools/CompactFonts.java')],check=True)
    for name in ['fonts_latin.gfx','gfxfontlib.gfx']:
        asset='\\art\\hud\\'+name;original=rcf_read(game/'art.rcf',asset);input_file=work/('original-'+name);input_file.write_bytes(original)
        generated=work/('generated-'+name)
        regular=work/('regular-advances-'+name)
        command=['java','-Djava.awt.headless=true','-cp',str(classes)+';'+str(libs),'EmbedChinese',str(input_file)]
        sources=[str(donors[weights['PrototypeSubtitle']]),str(charsfile),str(WORKSPACE/'vendor/NotoSans-Regular.ttf'),
                 str(WORKSPACE/'vendor/NotoSansMath-Regular.ttf')]
        # Derive the previous line metrics from the same stock face and full charset.
        # Quotation marks, dashes and the name dot otherwise acquire weight-dependent widths.
        subprocess.run(command+[str(regular)]+sources,check=True)
        subprocess.run(command+[str(generated)]+sources+[str(donors[weights['PrototypeBodyPC']]),
                       str(donors[weights['PrototypeTitlePC']])],check=True)
        patched,info=merge_fonts(original,generated.read_bytes(),allow_reindex=True,advance_reference=regular.read_bytes())
        # The classic file is a build intermediate only. Enforce the reviewed
        # per-font size bound on the compact GFX routed by native_font_buffers.h.
        for entry in info:entry.update(asset=asset,cjk_weight=weights[entry['font']])
        font_audit.extend(info)
        for code,body,_ in swf_tags(patched)[1]:
            if code==75 and font_name(body) in {'PrototypeBodyPC','PrototypeSubtitle','PrototypeTitlePC'}:
                codes=set(font3(body)['codes']);missing={c for c in chars if ord(c) not in codes}
                assert not missing,('Missing glyphs',font_name(body),missing)
        classic=work/('classic-'+name);classic.write_bytes(patched)
        compact_dir=work/('compact-'+name)
        subprocess.run(['java','-Djava.awt.headless=true','-cp',str(classes)+';'+str(libs),'CompactFonts',str(classic),str(compact_dir)],check=True)
        prefix,tags=swf_tags(patched);out=[]
        for code,body,raw_tag in tags:
            if code==75 and font_name(body) in {'PrototypeBodyPC','PrototypeSubtitle','PrototypeTitlePC'}:
                payload=(compact_dir/('font-'+str(struct.unpack_from('<H',body)[0])+'.bin')).read_bytes()
                out.append(tag_bytes(1005,payload))
            else:out.append(raw_tag)
        packed=bytearray(prefix+b''.join(out));packed[4:8]=p32(len(packed));patched=bytes(packed)
        assert len(patched)<=FONT_FILE_BUDGET,('Font exceeds native temporary-loading budget',name,len(patched))
        compact_check=json.loads((compact_dir/'validation.json').read_text('utf-8'))
        (work/('patched-'+name)).write_bytes(patched)
        add('art.rcf',asset,original,patched,'font',encoding='DefineCompactedFont',classic_sha256=sha(classic.read_bytes()),
            compact_validation=compact_check,cjk_advance_weight='Regular')
    return font_audit,donor_audit,weights

def main():
    p=argparse.ArgumentParser();p.add_argument('--game',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    cats={};alltexts=[];bilingual={}
    for kind in ['ui','subtitles','audio']:
        rows,done,provenance=catalog.load(kind);assert len(done)==len(rows),(kind,'Incomplete catalog')
        cats[kind]=[dict(r,zh=render_text(done[i])) for i,r in enumerate(rows)]
        bilingual[kind]=[dict(r,ordinal=i,zh=done[i],rendered_zh=render_text(done[i]),provenance=provenance[i]) for i,r in enumerate(rows)]
        alltexts.extend(r['zh'] for r in cats[kind])
    modern=json.loads((ROOT/'catalog/policy.json').read_text('utf-8'))['modern_labels'];alltexts.extend(modern.values())
    credits_original=rcf_read(a.game/'scripts.rcf',r'scripts\credits_english.txt')
    credits,credit_audit,credit_preserved=credits_translate(credits_original,json.loads((ROOT/'catalog/credits.json').read_text('utf-8')))
    alltexts.append(credits.decode('utf-8'))
    gfxmap=json.loads((ROOT/'catalog/gfx-labels.json').read_text('utf-8'));alltexts.extend(gfxmap.values())
    lua_rows=json.loads((ROOT/'catalog/lua-display.json').read_text('utf-8'));alltexts.extend(r['zh'] for r in lua_rows)
    native_labels={r['key']:r['zh'] for r in lua_rows if 'key' in r}
    extra_labels={**modern,**native_labels}
    inventory=json.loads((WORKSPACE/'work/PrototypeZh/full-inventory/all-text-holders.json').read_text('utf-8'))
    gfx_inventory=json.loads((WORKSPACE/'work/PrototypeZh/full-inventory/all-gfx.json').read_text('utf-8'))
    payloads={};audit=[]
    def add(ar,name,original,changed,kind,**details):
        assert name not in payloads;payloads[name]=changed
        audit.append(dict(archive=ar,asset=name,source_sha256=sha(original),sha256=sha(changed),kind=kind,**details))
    subs=collections.defaultdict(list)
    for row in cats['subtitles']:subs[(row['archive'],row['asset'])].append(row)
    for item in inventory:
        ar,name=item['archive'],item['asset'];original=rcf_read(a.game/ar,name);assert sha(original)==item['source_sha256']
        raw=unpack_rz(original);is_ui=name in [r'\art\hud\textbible_english.p3d.rz',r'\art\hud\fe_textbible.p3d.rz']
        rows=cats['ui'] if is_ui else subs.pop((ar,name));extra=extra_labels if is_ui else {}
        assert patch_text(raw,{},[])==raw
        new,changes=patch_rows(raw,rows,extra);assert patch_text(new,{},[])==new
        packed=repack_rz(original,new);assert unpack_rz(packed)==new
        add(ar,name,original,packed,'text',changes=changes,appended_ids=list(extra),ids_and_control_metadata_preserved=True)
    assert not subs
    audio_groups=collections.defaultdict(list)
    for row in cats['audio']:audio_groups[(row['archive'],row['asset'])].append(row)
    for (ar,name),rows in audio_groups.items():
        original=rcf_read(a.game/ar,name)
        assert all(sha(original)==r['source_sha256'] for r in rows)
        assert len({r['id'] for r in rows})==len(rows)
        raw=unpack_rz(original)
        changed,changes=patch_audio_subtitles(raw,{r['id']:(r['text'],r['zh']) for r in rows})
        packed=repack_rz(original,changed)
        add(ar,name,original,packed,'audio-subtitles',changes=changes,audio_payload_unchanged=True,
            other_languages_and_metadata_unchanged=True)
    lua_groups=collections.defaultdict(list)
    for row in lua_rows:lua_groups[(row['archive'],row['asset'])].append(row)
    for (ar,name),rows in lua_groups.items():
        original=rcf_read(a.game/ar,name)
        assert all(sha(original)==r['source_sha256'] for r in rows)
        raw=unpack_rz(original);changed,changes=patch_display(raw,rows)
        packed=repack_rz(original,changed)
        add(ar,name,original,packed,'lua-display',changes=changes,script_instructions_and_fig_offsets_unchanged=True)
    add('scripts.rcf',r'scripts\credits_english.txt',credits_original,credits,'credits',changes=credit_audit,preserved_lines=credit_preserved)
    gfx_audit=[]
    save_actions,save_audit=make_actions(a.work/'save-labels',WORKSPACE/'vendor/ffdec_26.4.0/ffdec.jar',cats['ui'])
    layout_actions,layout_sources=subtitle_layout.make_actions(a.work/'subtitle-layout',WORKSPACE/'vendor/ffdec_26.4.0/ffdec.jar')
    for item in gfx_inventory:
        name=item['asset'];original=rcf_read(a.game/item['archive'],name)
        # All game references to these exported fonts are dynamic text, not stored glyph indices.
        if any('gfxfontlib' in s or 'fonts_latin' in s for s in item['imports']):
            def verify_dynamic(code,body):assert code not in (11,33),('Static external font index reference',name)
            map_tags(original,verify_dynamic)
        basename=name.split('\\')[-1]
        # List-control defaults are overwritten through native text queries.
        # Keep the shared control resource completely original after the sample upgrade.
        if basename=='protolist.gfx':continue
        if not (basename.startswith(('proto','TUT')) or basename in ['storage.gfx','tutorial.gfx']):continue
        changed,labels=patch_gfx_labels(original,gfxmap)
        bounds={}
        if basename=='protopowerpurchase.gfx':
            changed,bounds_audit=patch_upgrade_cost_bounds(changed)
            changed=fit_upgrade_row(changed,revision=2)
            bounds=dict(upgrade_cost_bounds=bounds_audit,upgrade_core_layout=2)
        layout={}
        if basename in subtitle_layout.LOCATIONS:
            changed,layout_audit=subtitle_layout.patch_movie(changed,name,layout_actions,layout_sources)
            layout=dict(subtitle_layout=layout_audit,original_actions_unchanged=True)
        if basename=='storage.gfx':
            changed=append_actions(changed,save_actions)
            add(item['archive'],name,original,changed,'save-ui-labels',changes=labels,save_labels=save_audit)
            gfx_audit.append(dict(asset=name,changes=labels))
        elif labels or layout or bounds:
            add(item['archive'],name,original,changed,'initial-ui-labels',changes=labels,actions_unchanged=not bool(layout),**layout,**bounds)
            gfx_audit.append(dict(asset=name,changes=labels))
    chars,character_set=build_characters(alltexts)
    font_audit,donor_audit,weights=build_fonts(a.work,a.game,chars,add)
    output=a.work/'package';output.mkdir(exist_ok=True);rcf=make_rcf(payloads);rcfpath=output/'PrototypeZh.rcf';rcfpath.write_bytes(rcf)
    for name,contents in payloads.items():assert rcf_read(rcfpath,name)==contents
    assert r'\art\hud\protolist.gfx' not in payloads,'Retired sample bridge must not ship'
    manifest=dict(version=VERSION,archive_sha256=sha(rcf),resources=audit,font_audit=font_audit,
        ui_unique=len(cats['ui']),subtitles_rows=len(cats['subtitles']),subtitle_assets=len(inventory)-2,
        audio_subtitle_rows=len(cats['audio']),audio_subtitle_assets=len(audio_groups),
        lua_display_rows=len(lua_rows),lua_display_assets=len(lua_groups),
        modern_labels=modern,native_display_labels=native_labels,credit_heading_lines=len(credit_audit),credits_preserved_lines=len(credit_preserved),
        gfx_label_fields=sum(len(x['changes']) for x in gfx_audit),required_characters=len(chars),runtime_verified=False,
        font_donor=donor_audit['Regular'],font_donors=donor_audit,cjk_face_weights=weights,character_set=character_set,font_file_budget=FONT_FILE_BUDGET,native_temporary_heap_bytes=0x200000,
        name_separator=dict(source='U+00B7',render='U+2027',glyph='Noto middle dot; native U+00B7 icons retained'),
        modern_bridge='native text query IDs; no UI hook or Modern DLL change')
    manifest['runtime_support']=build_native_support(a.work,output)
    dump(output/'manifest.json',manifest);dump(a.work/'bilingual-catalog.json',bilingual)
    dump(a.work/'gfx-label-audit.json',gfx_audit);(a.work/'credits.zh.txt').write_bytes(credits)
    shutil.copy2(WORKSPACE/'vendor/NotoSansCJK-LICENSE.txt',output/'NotoSansCJK-LICENSE.txt')
    shutil.copy2(WORKSPACE/'vendor/NotoSans-LICENSE.txt',output/'NotoSans-LICENSE.txt')
    shutil.copy2(WORKSPACE/'vendor/NotoSansMath-LICENSE.txt',output/'NotoSansMath-LICENSE.txt')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['resources','font_audit']},ensure_ascii=False,indent=2))
    print('Built',rcfpath,len(rcf),'bytes',flush=True)
if __name__=='__main__':main()
