from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.release_1_auto import run_release_1_automated_gate
from dev_tests._runtime_context import runtime_registry

ROOT=Path(__file__).resolve().parents[1]


def _registry():
    return runtime_registry()


def _settings(tmp_path):
    return SimpleNamespace(project_root=tmp_path,client_root=tmp_path/'client')


def _batch(name='X'):
    return {'format':name,'status':'PASS','requested':1,'passed_assets':['a'],'failed_assets':[],'results':[],'report':'r.json'}


def _patch_all(monkeypatch):
    plan={
        'rigid_representatives':{'PLAYER':[{'asset':'a','domain':'PLAYER','model_info_inx':'a.inx'}]},
        'static_representatives':{'WEAPON_ITEM':[{'asset':'b','domain':'WEAPON_ITEM'}]},
        'animation_representatives':{'PLAYER':[{'asset':'a','domain':'PLAYER','model_info_inx':'a.inx'}]},
        'stage072_representatives':[{'asset':'m','domain':'MAP'}],
    }
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_automated_gate_plan',lambda *a,**k:plan)
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',lambda *a,**k:{'status':'PASS','inventory':{'by_domain':{}}})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_static_semantic_representatives',lambda registry,resolver,domain,limit=3: ([{'asset':'b','domain':'WEAPON_ITEM'}] if domain=='WEAPON_ITEM' else []))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_animation_pose_representatives',lambda registry,domain,limit=2: ([{'asset':'a','domain':'PLAYER','model_info_inx':'a.inx'}] if domain=='PLAYER' else []))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_standalone_rigid_authorable_representatives',lambda registry,resolver,domain,limit=3: ([{'asset':'e','domain':'EFFECT','skeleton_smb':'e.smb'}] if domain=='EFFECT' else []))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_all_model062_material_representatives',lambda *a,**k:{'PLAYER':[{'asset':'a','domain':'PLAYER'}]})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_model062_material_automated_devtest_batch',lambda *a,**k:_batch('M'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_model062_material_physical_corpus',lambda *a,**k:{'status':'PASS','asset_count':10,'failure_count':0,'pass_domains':['PLAYER']})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_model062_texture_presence',lambda *a,**k:{'status':'PASS','model062_asset_count':10,'required_texture_reference_count':12,'failure_count':0,'pass_domains':['PLAYER']})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_mixed_physique_synthetic_devtest',lambda *a,**k:{'status':'PASS','real_corpus_certified':False})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_model062_physical_corpus',lambda *a,**k:{'status':'PASS','asset_count':2600,'failure_count':0,'physical_mixed_count':0,'pass_domains_by_family':{'SMD_MODEL_062_RIGID_PHYSIQUE':['PLAYER'],'SMD_MODEL_062_STATIC':['WEAPON_ITEM'],'SMD_MODEL_062_MIXED_PHYSIQUE':[]}})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_rigid_context_census',lambda *a,**k:{'status':'PASS','rigid_asset_count':1952,'unresolved_count':0,'by_domain':{}})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_rigid_lod_context_corpus',lambda *a,**k:{'status':'PASS','config_count':10,'importable_config_count':10,'content_inconsistent_config_count':0,'lod_tier_count':20,'lod_tier_missing_node_count':0,'rows':[]})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_rigid_semantic_automated_devtest_batch',lambda *a,**k:_batch('R'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_standalone_rigid_representatives',lambda *a,**k:[{'asset':'e','domain':'EFFECT','skeleton_smb':'e.smb'}])
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_standalone_rigid_automated_devtest_batch',lambda *a,**k:_batch('RS'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_static_semantic_automated_devtest_batch',lambda *a,**k:_batch('S'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_model062_static_physical_corpus',lambda *a,**k:{'status':'PASS','asset_count':100,'failure_count':0,'pass_domains':['WEAPON_ITEM']})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_physical_corpus',lambda *a,**k:{'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,'full_parse_pass_files':63,'structural_fail_files':0,'stage072_physical_complete_candidate':True})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_stagearea_rebuild',lambda *a,**k:{'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,'reconstruction_pass_files':63})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_normals',lambda *a,**k:{'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,'audit_pass_files':63})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_texture_presence',lambda *a,**k:{'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,'texture_reference_classification_complete_candidate':True,'texture_presence_complete_candidate':True})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_stage072_automated_devtest_batch',lambda *a,**k:_batch('G'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_stage072_material_automated_devtest_batch',lambda *a,**k:_batch('GM'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_material_physical_corpus',lambda *a,**k:{'status':'PASS','pass_domains':['MAP'],'asset_count':63,'failure_count':0})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_animation_pose_automated_devtest_batch',lambda *a,**k:_batch('A'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_standalone_animation_representatives',lambda *a,**k:{d: [] for d in ('PLAYER','NPC','MONSTER','WEAPON_ITEM','EFFECT','MAP')})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_smb_animation_corpus',lambda *a,**k:{'status':'PASS','smb_file_count':10,'animated_smb_file_count':1,'by_domain':{'PLAYER':{'animated_smb_file_count':1}}})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_standalone_animation_pose_devtest_batch',lambda *a,**k:{'status':'EMPTY','requested':0,'passed_assets':[],'failed_assets':[],'results':[]})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_object_local_representatives',lambda *a,**k:[{'asset':'o'}])
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_object_local_automated_devtest_batch',lambda *a,**k:_batch('O'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_object_local_writer_corpus',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_object_local_physical_corpus',lambda *a,**k:{'status':'PASS','object_local_complete_candidate':True,'segmented_tmframe_files':0,'tag_counts':{}})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_multilayer_representatives',lambda *a,**k:[{'asset':'t'}])
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_multilayer_texlink_automated_devtest_batch',lambda *a,**k:_batch('T'))
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_multilayer_texlink_corpus',lambda *a,**k:{'status':'PASS','multilayer_two_stage_complete_candidate':True,'rows':[]})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_proprietary_texture_codecs',lambda *a,**k:{'status':'PASS','pass_count':9,'failure_count':0,'pass_domains':['PLAYER']})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_proprietary_texture_physical_corpus',lambda *a,**k:{'status':'PASS','pass_domains':['PLAYER'],'asset_count':9,'failure_count':0})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_rare_outliers_and_tga',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_rare_support',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_inx_writer_corpus',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_inx_writer_edit_corpus',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_smb_writer_corpus',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_smb_writer_edit_corpus',lambda *a,**k:{'status':'PASS'})
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_motion_writer_semantic_edit_corpus',lambda *a,**k:{'status':'PASS','audited_contexts':4})


def test_release_1_auto_mixed_is_out_of_scope_after_all_automatic_gates_pass(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='PASS'
    assert result['status']=='BLOCKED_EXTERNAL'
    assert result['external_input_required'] is False
    assert not any(x.get('gate') in {'MODEL062_MIXED','MODEL062_MIXED_PHYSICAL'} for x in result['blockers'])
    assert result['mixed_physique_release_scope']['status']=='OUT_OF_SCOPE_NOT_CERTIFIED'
    assert result['mixed_physique_release_scope']['release_1_blocking'] is False
    assert result['production_authorized'] is False
    assert result['client_write_authorized'] is False



def test_release_1_auto_real_mixed_present_remains_out_of_scope_for_release_1(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_mixed_physique_representatives',lambda *a,**k:[{'asset':'mix.smd','domain':'EFFECT'}])
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_model062_physical_corpus',lambda *a,**k:{'status':'PASS','asset_count':2601,'failure_count':0,'physical_mixed_count':1,'pass_domains_by_family':{'SMD_MODEL_062_RIGID_PHYSIQUE':['PLAYER'],'SMD_MODEL_062_STATIC':['WEAPON_ITEM'],'SMD_MODEL_062_MIXED_PHYSIQUE':['EFFECT']}})
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='PASS'
    assert result['status']=='BLOCKED_EXTERNAL'
    assert result['mixed_physique_release_scope']['status']=='OUT_OF_SCOPE_NOT_CERTIFIED'
    assert result['mixed_physique_release_scope']['physical_mixed_count']==1
    assert not any(x.get('gate') in {'MODEL062_MIXED','MODEL062_MIXED_PHYSICAL'} for x in result['blockers'])



def test_release_1_auto_mixed_scope_still_requires_runtime_and_promotion(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='PASS'
    assert result['status']=='BLOCKED_EXTERNAL'
    assert result['external_input_required'] is False
    assert result['manual_review_required_now'] is True
    assert result['external_gates_pending']==['WRITER_PROMOTION_AND_PUBLISH_RESTORE']
    assert result['runtime_game_acceptance_pending'] is False
    assert result['runtime_game_acceptance_scope']=='OUT_OF_SCOPE_PT_ASSET_TOOL_1_0'
    assert result['mixed_physique_release_scope']['post_1_0_backlog'] is True
    assert result['production_authorized'] is False


def test_release_1_auto_reports_internal_failure_before_mixed_external_gate(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr('pt_asset_tool.release_1_auto.run_stage072_automated_devtest_batch',lambda *a,**k:{'status':'FAIL','requested':1,'passed_assets':[],'failed_assets':[{'asset':'m'}]})
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert result['status']=='FAIL'
    assert any(x['gate']=='stage072' for x in result['blockers'])
    assert result['external_input_required'] is False


def test_passed_domains_requires_every_selected_asset_to_pass():
    from pt_asset_tool.release_1_auto import _passed_domains
    rows=[
        {'asset':'a','domain':'MONSTER'},
        {'asset':'b','domain':'MONSTER'},
        {'asset':'c','domain':'NPC'},
    ]
    batch={'status':'FAIL','passed_assets':['a','c'],'results':[]}
    assert _passed_domains(rows,batch)=={'NPC'}


def test_release_1_auto_blocks_unsupported_multilayer_depth_even_when_batch_passes(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_multilayer_texlink_corpus',
        lambda *a,**k:{
            'status':'PASS','multilayer_two_stage_complete_candidate':False,
            'three_plus_layer_files':2,'invalid_chain_files':0,'cycle_files':0,'rows':[],
        },
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='MULTILAYER_TEXLINK' and x.get('status')=='BLOCKED_UNSUPPORTED_DEPTH_OR_CHAIN' for x in result['blockers'])
    assert result['external_input_required'] is False


def test_release_1_auto_blocks_animated_smb_domain_without_pose_space_witness(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_smb_animation_corpus',
        lambda *a,**k:{
            'status':'PASS','smb_file_count':10,'animated_smb_file_count':2,
            'by_domain':{'EFFECT':{'animated_smb_file_count':2}},
        },
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='EXISTING_ANIMATION' and x.get('domain')=='EFFECT' for x in result['blockers'])


def test_release_1_auto_combines_standalone_smb_pose_domain_with_character_pose(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    rows={d: [] for d in ('PLAYER','NPC','MONSTER','WEAPON_ITEM','EFFECT','MAP')}
    rows['EFFECT']=[{'asset':'e','domain':'EFFECT','skeleton_smb':'e.smb'}]
    monkeypatch.setattr('pt_asset_tool.release_1_auto.choose_standalone_animation_representatives',lambda *a,**k:rows)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_smb_animation_corpus',
        lambda *a,**k:{
            'status':'PASS','smb_file_count':10,'animated_smb_file_count':2,
            'by_domain':{'PLAYER':{'animated_smb_file_count':1},'EFFECT':{'animated_smb_file_count':1}},
        },
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.run_standalone_animation_pose_devtest_batch',
        lambda *a,**k:{'status':'PASS','requested':1,'passed_assets':['e'],'failed_assets':[],'results':[]},
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{
            'PLAYER':{'PHYSICAL_INX_FILE':1,'PHYSICAL_SMB_FILE':1},
            'EFFECT':{'PHYSICAL_INX_FILE':1},
        }}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='PASS'
    assert set(captured['animation_pose_pass_domains']) >= {'PLAYER','EFFECT'}


def test_release_1_stage_domain_requires_corpus_gates_not_only_representative(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr('pt_asset_tool.release_1_auto.audit_stage072_normals',lambda *a,**k:{'status':'FAIL'})
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PARTIAL','inventory':{'by_domain':{}}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert 'MAP' not in set(captured.get('stage072_pass_domains') or [])


def test_release_1_auto_blocks_animation_track_subtype_without_pose_witness(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_smb_animation_corpus',
        lambda *a,**k:{
            'status':'PASS','smb_file_count':2,'animated_smb_file_count':1,
            'by_domain':{'PLAYER':{'animated_smb_file_count':1,'rot_key_count':10,'pos_key_count':4,'scale_key_count':0}},
        },
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.run_animation_pose_automated_devtest_batch',
        lambda *a,**k:{'status':'PASS','requested':1,'passed_assets':['a'],'failed_assets':[],
                       'results':[{'status':'PASS','asset':'a','domain':'PLAYER','track_key_counts':{'rot':10,'pos':0,'scale':0}}]},
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    hit=[x for x in result['blockers'] if x.get('status')=='BLOCKED_TRACK_SUBTYPE_WITHOUT_POSE_WITNESS']
    assert hit and hit[0]['missing_track_types']==['pos']


def test_release_1_auto_blocks_failed_static_corpus_even_when_representative_passes(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_model062_static_physical_corpus',
        lambda *a,**k:{'status':'FAIL','asset_count':100,'failure_count':1,'pass_domains':[]},
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='model062_static_corpus' for x in result['blockers'])


def test_release_1_auto_never_ignores_domain_blocker_from_coverage_matrix(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.build_release_1_coverage',
        lambda *a,**k:{
            'status':'PARTIAL','inventory':{'by_domain':{}},
            'blocking_gates':[
                {'domain':'MONSTER','capability':'LOD','blocker':'unresolved physical model key'},
                {'domain':'GLOBAL','capability':'PUBLISH_RESTORE','blocker':'runtime policy'},
            ],
        },
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('status')=='BLOCKED_COVERAGE_MATRIX' and x.get('gate')=='LOD' for x in result['blockers'])
    assert not any(x.get('status')=='BLOCKED_COVERAGE_MATRIX' and x.get('gate')=='PUBLISH_RESTORE' for x in result['blockers'])


def test_release_1_auto_inx_pass_domains_are_physical_domain_specific(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto._physical_files_by_domain',
        lambda _registry,suffix: (
            {'PLAYER':['char/a.inx'],'NPC':[],'MONSTER':[],'WEAPON_ITEM':[],'EFFECT':['effect/e.inx'],'MAP':[]}
            if suffix=='.inx' else
            {'PLAYER':['char/a.smb'],'NPC':[],'MONSTER':[],'WEAPON_ITEM':[],'EFFECT':[],'MAP':[]}
        ),
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_inx_writer_corpus',
        lambda *a,**k:{'status':'FAIL' if 'effect/e.inx' in (k.get('logical_paths') or []) else 'PASS'},
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{
            'PLAYER':{'PHYSICAL_INX_FILE':1,'PHYSICAL_SMB_FILE':1},
            'EFFECT':{'PHYSICAL_INX_FILE':1},
        }}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert 'PLAYER' in set(captured.get('inx_writer_pass_domains') or [])
    assert 'EFFECT' not in set(captured.get('inx_writer_pass_domains') or [])


def test_release_1_auto_object_local_domain_pass_requires_complete_physical_corpus(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_object_local_physical_corpus',
        lambda *a,**k:{
            'status':'PASS','object_local_complete_candidate':False,
            'segmented_tmframe_files':1,'tag_counts':{'FULL_PARSE_FAILURE':1},
            'rows':[{'path':'effect/o.smd','category':'EFFECT'}],
        },
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{}}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert captured.get('object_local_pass_domains') == []


def test_release_1_auto_multilayer_domain_pass_requires_supported_complete_corpus(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_multilayer_texlink_corpus',
        lambda *a,**k:{
            'status':'PASS','multilayer_two_stage_complete_candidate':False,
            'three_plus_layer_files':1,'invalid_chain_files':0,'cycle_files':0,
            'rows':[{'relative_path':'effect/t.smd','category':'EFFECT'}],
        },
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{}}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert captured.get('multilayer_texlink_pass_domains') == []


def test_release_1_auto_stage_pass_requires_every_selected_geometry_and_material_witness(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    plan={
        'rigid_representatives':{'PLAYER':[{'asset':'a','domain':'PLAYER','model_info_inx':'a.inx'}]},
        'static_representatives':{'WEAPON_ITEM':[{'asset':'b','domain':'WEAPON_ITEM'}]},
        'animation_representatives':{'PLAYER':[{'asset':'a','domain':'PLAYER','model_info_inx':'a.inx'}]},
        'stage072_representatives':[{'asset':'m1','domain':'MAP'},{'asset':'m2','domain':'MAP'}],
    }
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_automated_gate_plan',lambda *a,**k:plan)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.run_stage072_material_automated_devtest_batch',
        lambda *a,**k:{'status':'FAIL','requested':2,'passed_assets':['m1'],'failed_assets':[{'asset':'m2'}],'results':[]},
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{}}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert 'MAP' not in set(captured.get('stage072_pass_domains') or [])


def test_object_local_feature_coverage_requires_each_physical_subtype_in_domain():
    from pt_asset_tool.release_1_auto import _object_local_feature_coverage
    physical={
        'rows':[
            {'path':'effect/a.smd','category':'EFFECT','parser_status':'PASS','channels_present':['ROT','POS'],
             'segmented_object_count':1,'legacy_affine_object_count':0,'zero_scale_spawn_object_count':0,
             'parent_edge_count_full_parse':1,'unresolved_parent_count_full_parse':0,'animated_child_count':1},
            {'path':'effect/b.smd','category':'EFFECT','parser_status':'PASS','channels_present':['SCALE'],
             'segmented_object_count':0,'legacy_affine_object_count':1,'zero_scale_spawn_object_count':1,
             'parent_edge_count_full_parse':0,'unresolved_parent_count_full_parse':1,'animated_child_count':0},
        ]
    }
    selected=[{'asset':'effect/a.smd','domain':'EFFECT'},{'asset':'effect/b.smd','domain':'EFFECT'}]
    batch={'results':[
        {'status':'PASS','asset':'effect/a.smd','candidate_writer_channels_tested':['ROT','POS'],
         'segmented_tmframe_objects':['x'],'animated_child_count':1,'unresolved_parent_count':0,
         'blender_bake':{'legacy_affine_object_count':0,'zero_scale_spawn_object_count':0,'parent_edge_count':1,'unresolved_parent_count':0}},
        {'status':'PASS','asset':'effect/b.smd','candidate_writer_channels_tested':['SCALE'],
         'segmented_tmframe_objects':[],'animated_child_count':0,'unresolved_parent_count':1,
         'blender_bake':{'legacy_affine_object_count':1,'zero_scale_spawn_object_count':1,'parent_edge_count':0,'unresolved_parent_count':1}},
    ]}
    passed,details=_object_local_feature_coverage(physical,selected,batch)
    assert 'EFFECT' in passed
    assert details['EFFECT']['missing']==[]
    assert set(details['EFFECT']['required']) == {
        'ROT','POS','SCALE','SEGMENTED_TMFRAME','LEGACY_AFFINE','ZERO_SCALE_SPAWN',
        'HIERARCHICAL','UNRESOLVED_PARENT','ANIMATED_CHILD',
    }


def test_object_local_feature_coverage_blocks_missing_scale_witness():
    from pt_asset_tool.release_1_auto import _object_local_feature_coverage
    physical={'rows':[{'path':'maps/a.smd','category':'MAP','parser_status':'PASS','channels_present':['ROT','SCALE'],
                       'segmented_object_count':0,'legacy_affine_object_count':0,'zero_scale_spawn_object_count':0,
                       'parent_edge_count_full_parse':0,'unresolved_parent_count_full_parse':0,'animated_child_count':0}]}
    selected=[{'asset':'maps/a.smd','domain':'MAP'}]
    batch={'results':[{'status':'PASS','asset':'maps/a.smd','candidate_writer_channels_tested':['ROT'],
                       'blender_bake':{},'segmented_tmframe_objects':[]}]}
    passed,details=_object_local_feature_coverage(physical,selected,batch)
    assert 'MAP' not in passed
    assert details['MAP']['missing']==['SCALE']


def test_multilayer_profile_coverage_requires_full_partial_and_distinct_uv_profiles():
    from pt_asset_tool.release_1_auto import _multilayer_profile_coverage
    physical={'rows':[
        {'relative_path':'Effect/full.smd','category':'EFFECT','mode':'STATIC','multilayer_faces':10,'total_faces':10,'uv_different_multilayer_faces':0},
        {'relative_path':'Effect/partial.smd','category':'EFFECT','mode':'RIGID','multilayer_faces':2,'total_faces':10,'uv_different_multilayer_faces':1},
    ]}
    selected=[
        {'asset':'Effect/full.smd','domain':'EFFECT','coverage_features':['FAMILY_STATIC','FULL_FACE_MULTILAYER']},
        {'asset':'Effect/partial.smd','domain':'EFFECT','coverage_features':['FAMILY_RIGID','PARTIAL_FACE_MULTILAYER','DISTINCT_UV_STAGE']},
    ]
    batch={'passed_assets':['Effect/full.smd','Effect/partial.smd'],'results':[]}
    passed,details=_multilayer_profile_coverage(physical,selected,batch)
    assert 'EFFECT' in passed
    assert details['EFFECT']['missing']==[]


def test_multilayer_profile_coverage_blocks_unwitnessed_partial_profile():
    from pt_asset_tool.release_1_auto import _multilayer_profile_coverage
    physical={'rows':[
        {'relative_path':'Maps/full.smd','category':'MAP','mode':'STATIC','multilayer_faces':10,'total_faces':10,'uv_different_multilayer_faces':0},
        {'relative_path':'Maps/partial.smd','category':'MAP','mode':'STATIC','multilayer_faces':2,'total_faces':10,'uv_different_multilayer_faces':0},
    ]}
    selected=[{'asset':'Maps/full.smd','domain':'MAP','coverage_features':['FAMILY_STATIC','FULL_FACE_MULTILAYER']}]
    batch={'passed_assets':['Maps/full.smd'],'results':[]}
    passed,details=_multilayer_profile_coverage(physical,selected,batch)
    assert 'MAP' not in passed
    assert details['MAP']['missing']==['PARTIAL_FACE_MULTILAYER']


def test_release_1_stage_texture_audit_pass_does_not_hide_unclassified_reference(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_texture_presence',
        lambda *a,**k:{
            'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,
            'texture_reference_classification_complete_candidate':False,
            'unclassified_unique_texture_references':1,'texture_presence_complete_candidate':False,
        },
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='STAGE072' and x.get('status')=='BLOCKED_UNCLASSIFIED_TEXTURE_REFERENCE' for x in result['blockers'])


def test_release_1_stage_known_missing_texture_is_transport_classified_not_false_failure(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_texture_presence',
        lambda *a,**k:{
            'status':'PASS','candidate_files_expected':63,'physical_files_audited':63,
            'texture_reference_classification_complete_candidate':True,
            'texture_presence_complete_candidate':False,'client_missing_unique_texture_references':2,
            'serialized_invalid_unique_texture_references':1,'unclassified_unique_texture_references':0,
        },
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='PASS'


def test_release_1_stage_material_corpus_failure_blocks_even_when_representative_passes(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_material_physical_corpus',
        lambda *a,**k:{'status':'FAIL','pass_domains':[],'asset_count':63,'failure_count':1},
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='stage072_material_corpus' for x in result['blockers'])


def test_release_1_proprietary_texture_corpus_failure_blocks_representative_codec_pass(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_proprietary_texture_physical_corpus',
        lambda *a,**k:{'status':'FAIL','pass_domains':[],'asset_count':9,'failure_count':1},
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('gate')=='proprietary_texture_corpus' for x in result['blockers'])


def test_model062_material_family_coverage_requires_each_physical_family_witness():
    from pt_asset_tool.release_1_auto import _model062_material_family_coverage
    physical={
        'status':'PASS',
        'rows':[
            {'asset':'char/a.smd','domain':'PLAYER','family':'SMD_MODEL_062_RIGID_PHYSIQUE','status':'PASS'},
            {'asset':'char/b.smd','domain':'PLAYER','family':'SMD_MODEL_062_STATIC','status':'PASS'},
        ],
    }
    selected=[
        {'asset':'char/a.smd','domain':'PLAYER','family':'SMD_MODEL_062_RIGID_PHYSIQUE'},
        {'asset':'char/b.smd','domain':'PLAYER','family':'SMD_MODEL_062_STATIC'},
    ]
    passed,details=_model062_material_family_coverage(
        physical,selected,{'passed_assets':['char/a.smd'],'results':[]},
    )
    assert 'PLAYER' not in passed
    assert details['PLAYER']['missing']==['SMD_MODEL_062_STATIC']


def test_release_1_auto_blocks_stage_subset_even_if_every_subset_audit_reports_pass(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_physical_corpus',
        lambda *a,**k:{
            'status':'PASS','candidate_files_expected':62,'physical_files_audited':62,
            'full_parse_pass_files':62,'structural_fail_files':0,
            'stage072_physical_complete_candidate':False,
        },
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_stagearea_rebuild',
        lambda *a,**k:{'status':'PASS','candidate_files_expected':62,'physical_files_audited':62,'reconstruction_pass_files':62},
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_normals',
        lambda *a,**k:{'status':'PASS','candidate_files_expected':62,'physical_files_audited':62,'audit_pass_files':62},
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_texture_presence',
        lambda *a,**k:{
            'status':'PASS','candidate_files_expected':62,'physical_files_audited':62,
            'texture_reference_classification_complete_candidate':True,
            'texture_presence_complete_candidate':True,
        },
    )
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_stage072_material_physical_corpus',
        lambda *a,**k:{'status':'PASS','pass_domains':['MAP'],'asset_count':62,'failure_count':0},
    )
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert any(x.get('status')=='BLOCKED_INCOMPLETE_PHYSICAL_CORPUS' for x in result['blockers'])


def test_release_1_auto_domain_writer_pass_requires_motion_semantic_domain_pass(tmp_path,monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        'pt_asset_tool.release_1_auto.audit_motion_writer_semantic_edit_corpus',
        lambda *a,**k:{
            'status':'PASS','audited_contexts':4,
            'by_domain':{
                'PLAYER':{'context_count':2,'unresolved_asset_count':0,'status':'FAIL'},
            },
        },
    )
    captured={}
    def fake_coverage(*a,**k):
        if k.get('external_evidence'):
            captured.update(k['external_evidence'])
        return {'status':'PASS','inventory':{'by_domain':{'PLAYER':{'PHYSICAL_INX_FILE':1,'PHYSICAL_SMB_FILE':1}}}}
    monkeypatch.setattr('pt_asset_tool.release_1_auto.build_release_1_coverage',fake_coverage)
    settings=_settings(tmp_path); settings.client_root.mkdir()
    result=run_release_1_automated_gate(settings,_registry(),object(),object())
    assert result['automatic_gate_status']=='FAIL'
    assert 'PLAYER' not in set(captured.get('inx_writer_pass_domains') or [])
    assert 'PLAYER' not in set(captured.get('smb_writer_pass_domains') or [])
    assert any(x.get('gate')=='MOTION_SEMANTIC_EDIT' and x.get('domain')=='PLAYER' for x in result['blockers'])
