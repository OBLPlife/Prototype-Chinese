"""Installation/ownership fixtures with real native assets and inert engine copies."""
import argparse
import copy
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock
import setup
from resources import *

p=argparse.ArgumentParser()
p.add_argument('--game',required=True,type=Path)
p.add_argument('--package',required=True,type=Path)
p.add_argument('--report',required=True,type=Path)
p.add_argument('--previous-package',type=Path)
p.add_argument('--legacy-package',type=Path,help='Real pre-runtime package, separate from the previous runtime version')
p.add_argument('--original-engine',type=Path)
a=p.parse_args()
manifest=json.loads((a.package/'manifest.json').read_text('utf-8'))
support=setup.runtime_spec(manifest)
if not support:raise ValueError('These checks require a package with runtime_support')
runtime=(a.package/setup.RUNTIME).read_bytes()
assert sha(runtime)==support['sha256']
cement,_=setup.cement_edit((a.game/'cementfiles.p3d').read_bytes(),False)
modern_engine=(a.game/'prototypeenginef.dll').read_bytes()
original_path=a.original_engine or a.game/'PrototypeModern.Backup/prototypeenginef.dll.original'
original_engine=original_path.read_bytes() if original_path.is_file() else modern_engine

def disk_offset(data,target):
    pe=u32(data,0x3c);sections=struct.unpack_from('<H',data,pe+6)[0]
    table=pe+24+struct.unpack_from('<H',data,pe+20)[0]
    for i in range(sections):
        _,rva,size,offset=struct.unpack_from('<IIII',data,table+40*i+8)
        if rva<=target<rva+size:return offset+target-rva
    raise AssertionError('Fixture RVA has no file mapping: '+hex(target))

# Full resource serialization/font correctness has separate full-package checks.
# Use complete real representatives, not 14,318 audio files for each ownership case.
chosen=[]
for kind in ['text','font','audio-subtitles','credits']:
    row=next((r for r in manifest['resources'] if r['kind']==kind),None)
    if row and row['asset'] not in chosen:chosen.append(row['asset'])
for row in manifest['resources']:
    if 'subtitle_layout' in row and row['asset'] not in chosen:chosen.append(row['asset'])
assert any(r['kind']=='font' and r['asset'] in chosen for r in manifest['resources'])
passed=[]

with tempfile.TemporaryDirectory(prefix='prototypezh-install-fixture-') as temp:
    root=Path(temp)
    def fixture_package(source,dest,legacy=False):
        source_manifest=json.loads((source/'manifest.json').read_text('utf-8'))
        selected=[r for r in source_manifest['resources'] if r['asset'] in chosen]
        assert selected
        payloads={r['asset']:rcf_read(source/setup.OWN,r['asset']) for r in selected}
        assert all(sha(payloads[r['asset']])==r['sha256'] for r in selected)
        content=make_rcf(payloads)
        result=copy.deepcopy(source_manifest)
        result['resources']=selected;result['archive_sha256']=sha(content)
        if legacy:result.pop('runtime_support',None)
        dest.mkdir();(dest/setup.OWN).write_bytes(content)
        if result.get('runtime_support'):
            (dest/setup.RUNTIME).write_bytes((source/setup.RUNTIME).read_bytes())
        (dest/'manifest.json').write_bytes(setup.json_bytes(result))
        return result

    package=root/'package'
    fixture_manifest=fixture_package(a.package,package)
    legacy_package=root/'legacy-package'
    legacy_source=a.legacy_package or a.previous_package or a.package
    legacy_manifest=fixture_package(legacy_source,legacy_package,legacy=True)
    all_resources=fixture_manifest['resources']+legacy_manifest['resources']
    archives={}
    for r in all_resources:
        archives.setdefault(r['archive'],{})[r['asset']]=rcf_read(a.game/r['archive'],r['asset'])
        assert sha(archives[r['archive']][r['asset']])==r['source_sha256']

    def make_game(name,engine=original_engine):
        game=root/name;game.mkdir()
        (game/'cementfiles.p3d').write_bytes(cement)
        (game/'prototypef.exe').write_bytes(b'inert fixture marker; never execute')
        (game/'prototypeenginef.dll').write_bytes(engine)
        for name,resources in archives.items():(game/name).write_bytes(make_rcf(resources))
        return game

    def other_patches(game):
        (game/'PrototypeModern.dll').write_bytes(b'inert independent Modern ownership marker')
        (game/'prototypeenginef.dll').write_bytes(modern_engine)
        (game/'art.rcf').write_bytes(make_rcf({**archives['art.rcf'],r'\art\zh_fixture_texture':b'HD texture bytes'}))
        (game/'FixtureHD.rcf').write_bytes(make_rcf({r'\art\zh_fixture_second_texture':b'HD archive bytes'}))
        original_name=setup.OWN
        try:
            setup.OWN='FixtureHD.rcf'
            data,_=setup.cement_edit((game/'cementfiles.p3d').read_bytes(),True)
        finally:setup.OWN=original_name
        (game/'cementfiles.p3d').write_bytes(data)

    def protected(game):
        return {f.name:sha(f.read_bytes()) for f in game.iterdir() if f.is_file()
                and f.name not in [setup.OWN,setup.RUNTIME,'cementfiles.p3d']}

    def owned_snapshot(game):
        paths=[game/setup.OWN,game/setup.RUNTIME,game/'cementfiles.p3d',game/'PrototypeZh/state.json']
        return {str(path.relative_to(game)):path.read_bytes() if path.exists() else None for path in paths}

    def check_status(game):
        result=setup.status(game)
        assert result['checksum_ok'] and result['runtime_required'] and result['runtime_present']
        assert result['runtime_checksum_ok'] and result['runtime_engine']['compatible']
        assert result['runtime_engine']['font_lookup_checked']==bool(support.get('font_lookup'))
        assert result['runtime_engine']['font_kerning_checked']==bool(support.get('font_kerning'))
        assert result['registered']==1

    def expect_rejected(game,package,phrase):
        snapshot=owned_snapshot(game);keep=protected(game)
        try:setup.install(game,package)
        except ValueError as e:assert phrase in str(e),(phrase,str(e))
        else:raise AssertionError('Expected rejection: '+phrase)
        assert owned_snapshot(game)==snapshot and protected(game)==keep

    for order in ['other-patches-first','localization-first']:
        game=make_game(order)
        if order=='other-patches-first':other_patches(game)
        keep=protected(game)
        setup.install(game,package)
        assert protected(game)==keep
        if order=='localization-first':other_patches(game)
        check_status(game);keep=protected(game)
        setup.uninstall(game)
        assert protected(game)==keep
        _,groups=setup.cement_edit((game/'cementfiles.p3d').read_bytes(),False)
        assert 'FixtureHD.rcf' in dict(groups)['default'] and setup.OWN not in dict(groups)['default']
        assert not (game/setup.OWN).exists() and not (game/setup.RUNTIME).exists()
        passed.append(order+': owns only localization files; preserves Modern engine/DLL and HD data/registration')

    game=make_game('plain');keep=protected(game)
    setup.install(game,package);check_status(game)
    assert not (game/'PrototypeModern.dll').exists() and protected(game)==keep
    registered=(game/'cementfiles.p3d').read_bytes()
    setup.install(game,package);assert (game/'cementfiles.p3d').read_bytes()==registered
    (game/'cementfiles.p3d').write_bytes(cement)
    assert setup.status(game)['registered']==0
    setup.install(game,package);assert (game/'cementfiles.p3d').read_bytes()==registered
    (game/setup.RUNTIME).unlink()
    assert not setup.status(game)['runtime_checksum_ok']
    setup.install(game,package);check_status(game)
    setup.uninstall(game)
    assert (game/'cementfiles.p3d').read_bytes()==cement and protected(game)==keep
    passed.append('original engine only: install, reinstall, missing registration/runtime repair and selective uninstall')

    for label,payload in [('foreign',b'HD loader owned by another project'),('identical-but-unowned',runtime)]:
        game=make_game(label);(game/setup.RUNTIME).write_bytes(payload)
        expect_rejected(game,package,'Unowned or changed '+setup.RUNTIME)
        assert (game/setup.RUNTIME).read_bytes()==payload
    passed.append('foreign XInput DLL rejected before changes, including identical bytes without ownership state')

    game=make_game('legacy-upgrade')
    setup.install(game,legacy_package)
    old_status=setup.status(game);assert not old_status['runtime_required'] and not old_status['runtime_present']
    setup.install(game,package);check_status(game)
    assert setup.status(game)['version']==manifest['version']
    setup.uninstall(game);assert (game/'cementfiles.p3d').read_bytes()==cement
    passed.append('resource-only legacy 0.2.3 state upgrades to owned runtime and uninstalls cleanly')

    if a.previous_package:
        previous_package=root/'previous-package'
        previous_manifest=fixture_package(a.previous_package,previous_package)
        if previous_manifest.get('runtime_support'):
            game=make_game('previous-runtime-upgrade')
            setup.install(game,previous_package)
            snapshot=owned_snapshot(game);keep=protected(game)
            setup.install(game,package);check_status(game)
            setup.install(game,previous_package)
            previous_state=json.loads((game/'PrototypeZh/state.json').read_text('utf-8'))
            assert previous_state['version']==previous_manifest['version']
            assert (game/setup.OWN).read_bytes()==(previous_package/setup.OWN).read_bytes()
            assert (game/setup.RUNTIME).read_bytes()==(previous_package/setup.RUNTIME).read_bytes()
            previous_status=setup.status(game)
            assert previous_status['registered']==1 and previous_status['checksum_ok'] and previous_status['runtime_checksum_ok']
            assert protected(game)==keep
            setup.uninstall(game)
            assert (game/'cementfiles.p3d').read_bytes()==cement and protected(game)==keep
            passed.append('real previous runtime manifest: upgrade, exact previous payload rollback and selective uninstall')

    game=make_game('legacy-conflict')
    (game/setup.RUNTIME).write_bytes(b'pre-existing HD XInput loader')
    setup.install(game,legacy_package)
    expect_rejected(game,package,'Unowned or changed '+setup.RUNTIME)
    result=setup.uninstall(game)
    assert result['foreign_or_changed_runtime_preserved'] and (game/setup.RUNTIME).read_bytes()==b'pre-existing HD XInput loader'
    passed.append('legacy state does not claim an existing HD loader; legacy uninstall preserves it')

    game=make_game('changed-owned-runtime');setup.install(game,package)
    foreign=b'new third-party replacement of the former localization loader'
    (game/setup.RUNTIME).write_bytes(foreign)
    assert not setup.status(game)['runtime_checksum_ok']
    expect_rejected(game,package,'Unowned or changed '+setup.RUNTIME)
    result=setup.uninstall(game)
    assert result['foreign_or_changed_runtime_preserved'] and not result['runtime_support_removed']
    assert (game/setup.RUNTIME).read_bytes()==foreign and not (game/setup.OWN).exists()
    passed.append('changed formerly owned runtime: upgrade refuses overwrite; uninstall preserves replacement')

    corrupt_package=root/'corrupt-package';shutil.copytree(package,corrupt_package)
    (corrupt_package/setup.RUNTIME).write_bytes(runtime+b'checksum mismatch')
    game=make_game('corrupt-package-case')
    expect_rejected(game,corrupt_package,'runtime support checksum mismatch')
    passed.append('corrupt runtime package rejected before game changes')

    incompatible=bytearray(original_engine)
    location=incompatible.find(setup.CONSTRUCTOR_SIGNATURE)
    assert location>=0 and incompatible.find(setup.CONSTRUCTOR_SIGNATURE,location+1)<0
    incompatible[location+23]=0
    game=make_game('engine-conflict',bytes(incompatible))
    assert not setup.status(game)['runtime_engine']['compatible']
    expect_rejected(game,package,'constructor signature mismatch')
    passed.append('unsupported/conflicting engine constructor rejected; status reports incompatibility')

    if support.get('font_buffers'):
        for rva,signature in setup.FONT_BUFFER_SIGNATURES.items():
            incompatible=bytearray(original_engine);site=incompatible.find(signature)
            assert site>=0 and incompatible.find(signature,site+1)<0
            incompatible[site]^=1
            game=make_game('font-callsite-conflict-'+hex(rva),bytes(incompatible))
            assert not setup.engine_runtime_status(game,True)['compatible']
            expect_rejected(game,package,'font buffer callsite signature mismatch')
        passed.append('either conflicting font buffer callsite rejected before installation; alloc/free pair required')
        unsupported=root/'missing-font-buffer-support';shutil.copytree(package,unsupported)
        unsupported_manifest=copy.deepcopy(fixture_manifest)
        unsupported_manifest['runtime_support'].pop('font_buffers')
        (unsupported/'manifest.json').write_bytes(setup.json_bytes(unsupported_manifest))
        game=make_game('missing-font-buffer-support-case')
        expect_rejected(game,unsupported,'missing paired font buffer support')
        passed.append('GBK package cannot be installed with missing paired font buffer support')

    if support.get('font_lookup'):
        for rva in [*setup.FONT_LOOKUP_SIGNATURES,setup.FONT_LOOKUP_SLOT_RVA]:
            incompatible=bytearray(original_engine);incompatible[disk_offset(incompatible,rva)]^=1
            game=make_game('lookup-conflict-'+hex(rva),bytes(incompatible))
            assert not setup.engine_runtime_status(game,True,True)['compatible']
            expect_rejected(game,package,'compact font lookup signature mismatch')
        passed.append('compact lookup wrapper/search/vtable conflicts rejected before installation')

    if support.get('font_kerning'):
        for rva in [*setup.FONT_KERNING_SIGNATURES,setup.FONT_KERNING_SLOT_RVA]:
            incompatible=bytearray(original_engine);incompatible[disk_offset(incompatible,rva)]^=1
            game=make_game('kerning-conflict-'+hex(rva),bytes(incompatible))
            assert not setup.engine_runtime_status(game,True,True,True)['compatible']
            expect_rejected(game,package,'compact font kerning signature mismatch')
        passed.append('compact kerning wrapper/search/vtable conflicts rejected before installation')

    if support.get('subtitles'):
        for rva in [0x8649df,0x4d1954,0x641130]:
            incompatible=bytearray(original_engine);incompatible[disk_offset(incompatible,rva)]^=1
            game=make_game('subtitle-conflict-'+hex(rva),bytes(incompatible))
            assert not setup.engine_runtime_status(game,True,True,True,True)['compatible']
            expect_rejected(game,package,'subtitle signature mismatch')
        passed.append('subtitle update/objective/encoding conflicts rejected atomically before installation')

    relocated=bytearray(original_engine);pe=u32(relocated,0x3c)
    struct.pack_into('<I',relocated,pe+24+28,0x20000000)
    struct.pack_into('<I',relocated,location+7,0x20e8d914)
    if support.get('font_lookup'):
        struct.pack_into('<I',relocated,disk_offset(relocated,setup.FONT_LOOKUP_SLOT_RVA),
                         0x20000000+setup.FONT_LOOKUP_WRAPPER_RVA)
    if support.get('font_kerning'):
        struct.pack_into('<I',relocated,disk_offset(relocated,setup.FONT_KERNING_SLOT_RVA),
                         0x20000000+setup.FONT_KERNING_WRAPPER_RVA)
        for relative,target in [(23,0xe1fdf8),(39,0xde09f0)]:
            struct.pack_into('<I',relocated,disk_offset(relocated,setup.FONT_KERNING_WRAPPER_RVA)+relative,0x20000000+target)
    if support.get('subtitles'):
        from subtitle_support import SIGNATURES
        for rva,_,_,offsets in SIGNATURES:
            for relative in offsets:
                offset=disk_offset(relocated,rva+relative)
                struct.pack_into('<I',relocated,offset,(u32(relocated,offset)+0x10000000)&0xffffffff)
    game=make_game('preferred-base',bytes(relocated))
    assert setup.engine_runtime_status(game)['compatible']
    setup.install(game,package);check_status(game)
    assert (game/'prototypeenginef.dll').read_bytes()==relocated
    setup.uninstall(game)
    passed.append('constructor and compact lookup signatures honor PE preferred-base pointers without writing engine bytes')

    game=make_game('font-conflict')
    name=next(r['asset'] for r in fixture_manifest['resources'] if r['kind']=='font')
    bad=dict(archives['art.rcf']);bad[name]+=b'changed by another patch'
    (game/'art.rcf').write_bytes(make_rcf(bad))
    expect_rejected(game,package,'Shared resource changed')
    passed.append('shared native font asset conflict detected before changes')

    for row in fixture_manifest['resources']:
        if 'subtitle_layout' not in row:continue
        game=make_game('layout-conflict-'+row['asset'].split('\\')[-1])
        bad=dict(archives[row['archive']]);bad[row['asset']]+=b'changed by another UI patch'
        (game/row['archive']).write_bytes(make_rcf(bad))
        expect_rejected(game,package,'Shared resource changed')
    if any('subtitle_layout' in row for row in fixture_manifest['resources']):
        passed.append('both shared subtitle/HUD movie conflicts detected before changes')

    original_write=setup.atomic_write
    for point in ['state.json','cementfiles.p3d']:
        game=make_game('fresh-rollback-'+point);snapshot=owned_snapshot(game);keep=protected(game)
        failed=[False]
        def fail_after_write(path,data):
            original_write(path,data)
            if path.name==point and not failed[0]:
                failed[0]=True;raise OSError('fixture failure after publishing '+point)
        with mock.patch.object(setup,'atomic_write',fail_after_write):
            try:setup.install(game,package)
            except OSError:pass
            else:raise AssertionError('Install failure injection did not run')
        assert failed[0] and owned_snapshot(game)==snapshot and protected(game)==keep
    passed.append('fresh install failures after state or registration publication rollback archive/runtime/state/registration')

    upgrade_package=root/'upgrade-package';shutil.copytree(package,upgrade_package)
    upgrade_manifest=copy.deepcopy(fixture_manifest)
    upgrade_runtime=runtime+b'\0fixture overlay; never executed'
    upgrade_archive=(upgrade_package/setup.OWN).read_bytes()+b'\0'
    (upgrade_package/setup.RUNTIME).write_bytes(upgrade_runtime)
    (upgrade_package/setup.OWN).write_bytes(upgrade_archive)
    upgrade_manifest['runtime_support']['sha256']=sha(upgrade_runtime)
    upgrade_manifest['archive_sha256']=sha(upgrade_archive)
    (upgrade_package/'manifest.json').write_bytes(setup.json_bytes(upgrade_manifest))
    game=make_game('upgrade-rollback');setup.install(game,package)
    snapshot=owned_snapshot(game);keep=protected(game);failed=[False]
    def fail_upgrade(path,data):
        original_write(path,data)
        if path.name=='state.json' and not failed[0]:
            failed[0]=True;raise OSError('fixture upgrade failure')
    with mock.patch.object(setup,'atomic_write',fail_upgrade):
        try:setup.install(game,upgrade_package)
        except OSError:pass
        else:raise AssertionError('Upgrade failure injection did not run')
    assert failed[0] and owned_snapshot(game)==snapshot and protected(game)==keep
    check_status(game)
    passed.append('upgrade failure restores exact previous runtime/archive and ownership state')

    original_unlink=Path.unlink;failed=[False]
    def fail_state_delete(path,*args,**kwargs):
        if path==game/'PrototypeZh/state.json' and not failed[0]:
            failed[0]=True;raise OSError('fixture uninstall failure after payload deletions')
        return original_unlink(path,*args,**kwargs)
    with mock.patch.object(Path,'unlink',fail_state_delete):
        try:setup.uninstall(game)
        except OSError:pass
        else:raise AssertionError('Uninstall failure injection did not run')
    assert failed[0] and owned_snapshot(game)==snapshot and protected(game)==keep
    check_status(game)
    passed.append('uninstall failure restores deleted owned payloads and registration, retaining prior state')

report=dict(passed=True,version=manifest['version'],archive_sha256=manifest['archive_sha256'],
            runtime_sha256=support['sha256'],fixture_resource_count=len(fixture_manifest['resources']),
            fixture_uses_complete_representative_assets=True,full_package_resource_verification=False,
            original_engine_sha256=sha(original_engine),modern_engine_sha256=sha(modern_engine),
            distinct_original_and_modern_engines=original_engine!=modern_engine,
            checks=passed,game_executed=False,engine_code_executed=False,real_hd_patch_tested=False)
a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
