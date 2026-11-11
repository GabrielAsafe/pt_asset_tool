from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pt_asset_tool import etervale_p0_alias as alias
from pt_asset_tool import etervale_p0_binary as binary
from pt_asset_tool import etervale_p0_content_probe as content
from pt_asset_tool import etervale_native_pipeline as native
from pt_asset_tool import etervale_p0_release as release


def _sha(blob: bytes)->str:return hashlib.sha256(blob).hexdigest()


def fixture_game(tmp_path):
    game=tmp_path/'game';source=game/'assets'/'GameServer'
    for dirname in ('Field','Monster','NPC','OpenItem'):(source/dirname).mkdir(parents=True,exist_ok=True)
    (source/'Field'/'Test.spm').write_bytes('*출현간격\t5\t23\r\n*출연자 "Test" 12\r\n'.encode('cp949'))
    (source/'Monster'/'Mon.inf').write_bytes('*이름 "Mon"\r\n*레벨 11\r\n'.encode('cp949'))
    (source/'NPC'/'One.npc').write_bytes('*E_CHAT "Hello"\r\n'.encode('cp949'))
    (source/'OpenItem'/'Item.txt').write_bytes('*코드 AA101\r\n*레벨 10\r\n'.encode('cp949'))
    return game,source


def _native_spec(src,rel,ops):
    return {'format':native.FORMAT,'files':[{'path':rel,'sha256':_sha(src.read_bytes()),'operations':ops}]}


def test_alias_english_to_korean_preserves_original_token(tmp_path):
    root,server=fixture_game(tmp_path);src=server/'Field'/'Test.spm'
    manifest=native.build_overlay(_native_spec(src,'Field/Test.spm',[{'op':'set','key':'*DELAY','values':[3,2]}]),root,tmp_path/'work')
    raw=Path(manifest['files'][0]['output']).read_bytes()
    assert '*출현간격 3 2' in raw.decode('cp949')
    assert '*DELAY' not in raw.decode('cp949')
    assert src.read_bytes().decode('cp949').startswith('*출현간격\t5')


def test_alias_no_multi_match_without_occurrence(tmp_path):
    root,server=fixture_game(tmp_path);src=server/'Field'/'Test.spm'
    src.write_bytes(src.read_bytes()+b'*DELAY 4 5\r\n')
    with pytest.raises(ValueError,match='EXACT_MATCH'):
        native.build_overlay(_native_spec(src,'Field/Test.spm',[{'op':'set','key':'*DELAY','values':[3,2]}]),root,tmp_path/'work')


def test_alias_item_level_scope_and_append_reject_nonexistent(tmp_path):
    root,server=fixture_game(tmp_path);src=server/'OpenItem'/'Item.txt'
    obj=native.build_overlay(_native_spec(src,'OpenItem/Item.txt',[{'op':'set','key':'*LEVEL','values':[15]}]),root,tmp_path/'work')
    assert '*레벨 15' in Path(obj['files'][0]['output']).read_bytes().decode('cp949')
    with pytest.raises(ValueError,match='ALIAS_NEEDS_EXISTING'):
        native.build_overlay(_native_spec(src,'OpenItem/Item.txt',[{'op':'append','key':'*PRICE','values':[5]}]),root,tmp_path/'work')


def test_automatic_four_domain_existing_content_probe(tmp_path):
    root,server=fixture_game(tmp_path)
    out=content.prepare(root,['OpenItem/Item.txt','Monster/Mon.inf','NPC/One.npc','Field/Test.spm'],tmp_path/'work')
    assert len(out['overlay']['files'])==4
    assert not out['overlay']['identity_review_required']
    for row in out['overlay']['files']:
        assert row['source_sha256'] != row['new_sha256']
    assert out['operation_summaries'][-1]['operation']['key']=='*DELAY'
    assert '*출현간격 6 23' in (Path(out['overlay']['files'][-1]['output']).read_bytes().decode('cp949'))


def test_model062_real_surgical_writer_preserves_every_other_byte(tmp_path):
    from pt_asset_tool.model062_static_compiler import compile_static_model062
    payload={'mesh':{'materials':[{'textures':[]}], 'objects':[{'name':'Test',
      'vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[{'vertices':[0,1,2],'material':0}]}]}}
    raw,_=compile_static_model062(payload)
    src=tmp_path/'test.smd';src.write_bytes(raw)
    dst=tmp_path/'new.smd'
    proof=binary.patch_smd_material(src,dst)
    assert proof['status']=='PASS' and proof['kind']=='MODEL_062'
    assert len(raw)==dst.stat().st_size
    loc=binary.material_offsets(raw)[1][0]+148
    assert raw[:loc]==dst.read_bytes()[:loc]
    assert raw[loc+4:]==dst.read_bytes()[loc+4:]


def test_stage072_real_surgical_writer_preserves_collision_payload(tmp_path):
    from pt_asset_tool.stage072_compiler import compile_stage072
    payload={'materials':[{'textures':[]}],'vertices':[[0,0,0],[64,0,0],[0,0,64]],
             'faces':[{'vertices':[0,2,1],'material':0}],'area_mode':'NONE'}
    raw,_=compile_stage072(payload)
    src=tmp_path/'test.smd';src.write_bytes(raw)
    dst=tmp_path/'new.smd'
    proof=binary.patch_smd_material(src,dst)
    assert proof['status']=='PASS' and proof['kind']=='STAGE_072'
    loc=binary.material_offsets(raw)[1][0]+148
    assert raw[:loc]==dst.read_bytes()[:loc]
    assert raw[loc+4:]==dst.read_bytes()[loc+4:]


def fake_native_report(manifest,work):
    proof=work/'native-verify.json'
    proof.write_text(json.dumps({'format':'PT_ASSET_ETERVALE_NATIVE_IMPORT_GATE_V2',
                                 'status':'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED','manifest':manifest['manifest'],
                                 'game_assets_modified':False,'new_unresolved':[],'semantic_errors':[],
                                 'steps':{'baseline':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]},
                                          'candidate':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]}},
                                 'semantic_catalog_changes':{'Field':['fields']}}),encoding='utf-8')
    return proof


def test_release_plan_apply_rollback_with_hash_approval(tmp_path):
    game,server=fixture_game(tmp_path);work=tmp_path/'work'
    source=server/'Field'/'Test.spm'
    overlay=native.build_overlay(_native_spec(source,'Field/Test.spm',[{'op':'set','key':'*DELAY','values':[3,2]}]),game,work)
    proof=fake_native_report(overlay,work)
    plan=release.make_native_plan(game,work,Path(overlay['manifest']),proof)
    before=source.read_bytes()
    with pytest.raises(ValueError,match='APPROVAL'):
        release.apply(game,work,Path(plan['plan']),'bad')
    published=release.apply(game,work,Path(plan['plan']),plan['approval_sha256'])
    assert published['status']=='PUBLISHED_NOT_RUNTIME_CERTIFIED'
    assert source.read_bytes()!=before
    rolled=release.rollback(game,work,Path(published['journal']),plan['approval_sha256'])
    assert rolled['status']=='ROLLED_BACK'
    assert source.read_bytes()==before
    with pytest.raises(ValueError,match='ALREADY_COMPLETED'):
        release.rollback(game,work,Path(published['journal']),plan['approval_sha256'])


def test_release_refuses_external_modifications_and_new_entities(tmp_path):
    game,server=fixture_game(tmp_path);work=tmp_path/'work'
    src=server/'Field'/'Test.spm'
    overlay=native.build_overlay(_native_spec(src,'Field/Test.spm',[{'op':'set','key':'*DELAY','values':[3,2]}]),game,work)
    proof=fake_native_report(overlay,work)
    plan=release.make_native_plan(game,work,Path(overlay['manifest']),proof)
    src.write_bytes(src.read_bytes()+b'// external\r\n')
    with pytest.raises(ValueError,match='CHANGED_SINCE_PLAN'):
        release.apply(game,work,Path(plan['plan']),plan['approval_sha256'])
    # New monster identities cannot be promoted merely because importer accepted a clone.
    src=server/'Monster'/'Mon.inf'
    recipe={'format':native.FORMAT,'files':[{'path':'Monster/New.inf','template':'Monster/Mon.inf',
            'sha256':_sha(src.read_bytes()),'operations':[{'op':'set','key':'*레벨','values':[13]}]}]}
    new=native.build_overlay(recipe,game,work)
    proof=work/'new-verify.json'
    proof.write_text(json.dumps({'status':'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED','manifest':new['manifest'],
                                 'game_assets_modified':False,'new_unresolved':[],'semantic_errors':[],
                                 'steps':{'baseline':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]},
                                          'candidate':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]}},
                                 'semantic_catalog_changes':{'Monster':['monsters']}}))
    with pytest.raises(ValueError,match='IDENTITY'):
        release.make_native_plan(game,work,Path(new['manifest']),proof)


def test_release_proof_binding_and_rollback_drift_block(tmp_path):
    game,server=fixture_game(tmp_path);work=tmp_path/'work'
    src=server/'Field'/'Test.spm'
    overlay=native.build_overlay(_native_spec(src,'Field/Test.spm',[{'op':'set','key':'*DELAY','values':[3,2]}]),game,work)
    proof=fake_native_report(overlay,work)
    plan=release.make_native_plan(game,work,Path(overlay['manifest']),proof)
    proof.write_text(proof.read_text()+'\n')
    with pytest.raises(ValueError,match='PROOF_CHANGED'):
        release.apply(game,work,Path(plan['plan']),plan['approval_sha256'])
    # Repair proof to original digest and apply.
    proof.write_text(proof.read_text().rstrip('\n'))
    pub=release.apply(game,work,Path(plan['plan']),plan['approval_sha256'])
    src.write_bytes(b'Other process overwrote this file')
    with pytest.raises(ValueError,match='CHANGED_EXTERNALLY'):
        release.rollback(game,work,Path(pub['journal']),plan['approval_sha256'])


def test_binary_proof_release_requires_reader_and_offsets(tmp_path):
    game,server=fixture_game(tmp_path);work=tmp_path/'work'
    src=game/'assets'/'custom.smd'
    src.write_bytes(b'SMD Source');candidate=work/'candidate.smd';candidate.parent.mkdir();candidate.write_bytes(b'SMD Edited')
    proof=work/'binary.json'
    data={'format':binary.FORMAT,'status':'PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED',
          'asset':'custom.smd','source':str(src),'source_sha256':_sha(src.read_bytes()),
          'candidate':str(candidate),'candidate_sha256':_sha(candidate.read_bytes()),
          'writer_evidence':{'status':'PASS','allowed_offsets_only':True},
          'writer_status':'PASS','reader_status':'READER_ACCEPTED','game_assets_modified':False,
          'probe_only':False,'authoring_intent':'USER_SCALAR_EDIT',
          'reader_result':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]}}
    proof.write_text(json.dumps(data))
    # Single root asset needs a category directory, preventing arbitrary root writes.
    with pytest.raises(ValueError,match='PATH_UNSAFE'):
        release.make_binary_plan(game,work,proof)
    rel=game/'assets'/'char'/'probe.smd';rel.parent.mkdir(parents=True);rel.write_bytes(src.read_bytes())
    data.update(asset='char/probe.smd',source=str(rel));proof.write_text(json.dumps(data))
    result=release.make_binary_plan(game,work,proof)
    assert result['kind']=='SMD_SMB_INX'
    data['probe_only']=True;proof.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='PROBE_CANDIDATE'):
        release.make_binary_plan(game,work,proof)
    data['probe_only']=False
    data['writer_evidence']['allowed_offsets_only']=False;proof.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='OFFSETS'):
        release.make_binary_plan(game,work,proof)


def test_commands_registered():
    import argparse
    from pt_asset_tool import etervale_p0_release, etervale_p0_binary, etervale_p0_content_probe
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd')
    for module in (etervale_p0_release,etervale_p0_binary,etervale_p0_content_probe):module.register(sp)
    assert set(('p0-binary-probe','p0-binary-edit','p0-content-probe','p0-release-plan','p0-release-apply','p0-release-rollback'))<=set(sp.choices)


def test_closure_audit_requires_real_four_binary_types_and_four_native_domains(tmp_path):
    from pt_asset_tool import etervale_p0_closure_audit as gate
    assert gate.inspect(tmp_path)['status']=='P0_AUTHORING_GATES_INCOMPLETE'
    w=tmp_path/'writer_probes';w.mkdir()
    for n,(asset,kind) in enumerate((('Field/Stage.smd','STAGE_072'),('char/Model.smd','MODEL_062'),
                                     ('char/Monster.smb',None),('char/Monster.inx',None))):
        (w/f'{n}.json').write_text(json.dumps({'format':binary.FORMAT,
           'status':'PASS_BINARY_WRITER_READER_NOT_RUNTIME_CERTIFIED','reader_status':'READER_ACCEPTED',
           'game_assets_modified':False,'asset':asset,'writer_evidence':{'kind':kind}}))
    native_dir=tmp_path/'content_compat';native_dir.mkdir()
    (native_dir/'native.json').write_text(json.dumps({'format':content.FORMAT,
        'status':'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED','game_assets_modified':False,
        'verification':{'semantic_catalog_changes':{'OpenItem':['items'],'Monster':['monsters'],
                 'NPC':['npc_texts'],'Field':['fields']}}}))
    summary=gate.inspect(tmp_path)
    assert summary['status']=='P0_AUTHORING_GATES_PASSED_NOT_RUNTIME_CERTIFIED'
    assert len(summary['binary_reader_writer_proofs'])==4
    assert summary['remaining_gates']==[]
    assert summary['game_runtime']=='NOT_CERTIFIED'


def test_auto_native_selects_four_existing_domains(tmp_path):
    root,server=fixture_game(tmp_path)
    assert set(x.split('/')[0] for x in content.choose_auto(root))==set(content.OPTIONS)


def test_automatic_content_probe_never_authorizes_publication(tmp_path):
    game,server=fixture_game(tmp_path);work=tmp_path/'work'
    candidate=content.prepare(game,['OpenItem/Item.txt','Monster/Mon.inf','NPC/One.npc','Field/Test.spm'],work)
    manifest=json.loads(Path(candidate['manifest']).read_text())
    assert manifest['probe_only'] is True
    verification=work/'not-publishable.json'
    verification.write_text(json.dumps({'format':'PT_ASSET_ETERVALE_NATIVE_IMPORT_GATE_V2',
       'status':'PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED','manifest':candidate['manifest'],
       'game_assets_modified':False,'new_unresolved':[],'semantic_errors':[],
       'semantic_catalog_changes':{'OpenItem':['items'],'Monster':['monsters'],
                                   'NPC':['npc_texts'],'Field':['fields']},
       'steps':{'baseline':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]},
                'candidate':{'exit_code':0,'steps':[{'command':['dotnet'],'exit_code':0}]}}}))
    with pytest.raises(ValueError,match='EXPERIMENTAL_PROBE'):
        release.make_native_plan(game,work,Path(candidate['manifest']),verification)
