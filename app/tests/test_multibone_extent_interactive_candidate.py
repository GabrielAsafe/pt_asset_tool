from __future__ import annotations
import json, pathlib, sys
import pytest
ROOT=pathlib.Path(__file__).resolve().parents[1]; PAYLOAD=ROOT/'payload'; sys.path.insert(0,str(PAYLOAD))
from pt_asset_tool import rare_rigid_multibone_extent_interactive_candidate as m

def _prior():
    kinds=('maxX','maxZ','maxY','dBound','Bound'); rows=[]
    for i,k in enumerate(kinds):
        rows.append({'format':'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_WRITE_V1','status':'PASS','candidate_only':True,'production_authorized':False,'target_bound_kind':k,'object_index':8 if k=='maxX' else i,'vertex_index':30 if k=='maxX' else 100+i,'candidate_certification_test':m.CANDIDATE_TEST,'matches_v0832_output_sha256':True,'output_sha256':str(i+1)*64})
    return {'format':'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_AUDIT_V1','status':'PASS','release_version':'0.8.33','logical':m.TARGET,'prior_v0832_strict_pass':True,'prior_v0832_witness_count':5,'candidate_witness_count':5,'exact_candidate_writer_function_exercised':'write_at_dragon_multibone_outward_extent_candidate_workspace','all_candidate_rows_pass':True,'rows':rows,'all_live_writer_outputs_match_v0832':True,'isolated_candidate_certification_count':5,'candidate_certification_test':m.CANDIDATE_TEST,'production_extent_still_blocked':True,'production_extent_output_created':False,'multi_vertex_extent_blocked':True,'multi_vertex_extent_output_created':False,'cross_object_extent_blocked':True,'cross_object_extent_output_created':False,'inward_no_extent_blocked':True,'inward_no_extent_output_created':False,'real_certification_registry_modified':False,'single_object_production_policy_modified':False,'cross_object_production_policy_modified':False,'writer_modules_modified':False,'client_modified':False,'multibone_outward_extent_live_write_authorized':False,'extent_contraction_write_authorized':False,'multi_vertex_extent_write_authorized':False,'cross_object_extent_write_authorized':False,'topology_write_authorized':False,'writer_hashes':m.EXPECTED_WRITER_HASHES}

def _prior_fail():
    return {'format':'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1','status':'FAIL','release_version':'0.8.34','logical':m.TARGET,'error':m.EXPECTED_PRIOR_V0834_ERROR,'multibone_outward_extent_live_write_authorized':False}

def test_release_scope():
    assert m.RELEASE_VERSION=='0.8.35'; assert m.MANUAL_KIND=='maxX'; assert m.FORMAT.endswith('MANUAL_WRITE_V1'); assert m.FRIENDLY_DELTAS_FIXED[0]==64

def test_strict_prior_accepts_v0833(tmp_path):
    p=tmp_path/m.PRIOR_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(_prior()))
    d=m._strict_prior_v0833(tmp_path); assert d['_rows_by_kind']['maxX']['vertex_index']==30

def test_strict_prior_rejects_extent_authorized(tmp_path):
    d=_prior(); d['multibone_outward_extent_live_write_authorized']=True; p=tmp_path/m.PRIOR_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError,match='NOT_STRICT_PASS'): m._strict_prior_v0833(tmp_path)

def test_exact_v0834_failure_gate(tmp_path):
    p=tmp_path/m.PRIOR_FAILED_REL; p.parent.mkdir(parents=True); p.write_text(json.dumps(_prior_fail()))
    assert m._strict_prior_v0834_failure(tmp_path)['error']==m.EXPECTED_PRIOR_V0834_ERROR
    d=_prior_fail(); d['error']=d['error'].replace('1358','1357'); p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError,match='NOT_EXACT_EXPECTED'): m._strict_prior_v0834_failure(tmp_path)

def test_manual_plan_prevalidates_quarter_unit_first(monkeypatch):
    prior=_prior(); prior['_rows_by_kind']={r['target_bound_kind']:r for r in prior['rows']}
    base={'object_index':8,'vertex_index':30,'changed_bound_fields':['maxX'],'before_world_fixed':[1294,370,0],'requested_after_world_fixed':[1347,370,0]}
    monkeypatch.setattr(m,'discover_witnesses',lambda *a,**k:{'found':{'maxX':base}})
    objs=[{'faces':[]} for _ in range(9)]; monkeypatch.setattr(m,'_parse_with_offsets',lambda p:{'objects':objs})
    monkeypatch.setattr(m,'_parse_skeleton_tms',lambda p:{})
    world=[[0,0,0] for _ in range(31)]; world[30]=(1294,370,0)
    monkeypatch.setattr(m,'_world_positions',lambda obj,bones:world)
    monkeypatch.setattr(m,'_build_source_normal_state',lambda world,faces:{})
    calls=[]
    def ev(obj,bones,world,state,vi,requested,kind):
        calls.append(tuple(requested))
        if tuple(requested)!=(1358,370,0): return None
        return {'guard_status':'PASS','object_index':8,'vertex_index':30,'changed_bound_fields':['maxX'],'before_world_fixed':[1294,370,0],'requested_after_world_fixed':[1358,370,0],'affected_bone_count':2,'affected_bones':['Bip01 L Calf','Bip01 L Foot'],'stored_bounds_after':{'maxZ':1396,'maxY':3989,'maxX':1358,'dBound':242,'Bound':15}}
    monkeypatch.setattr(m,'_evaluate',ev)
    q=m._manual_plan(pathlib.Path('a'),pathlib.Path('b'),prior)
    assert calls[0]==(1358,370,0); assert q['manual_delta_world_fixed']==64; assert q['manual_delta_world']==0.25; assert q['manual_friendly_delta_prevalidated'] is True

def test_wrapper_and_blender_helpers_are_manual_no_popup():
    wrapper=(PAYLOAD/'pt_asset.py').read_text(); assert 'OVERLAY_VERSION = "0.12.0"' in wrapper; assert 'rare-model-multibone-outward-extent-candidate' in wrapper
    sel=(PAYLOAD/'pt_asset_tool/blender/ensure_rare_rigid_multibone_extent_manual_selection.py').read_text(); assert 'bm.verts.ensure_lookup_table()' in sel; assert "actual!=[vi]" in sel
    ui=(PAYLOAD/'pt_asset_tool/blender/open_rare_rigid_multibone_extent_manual_candidate.py').read_text(); assert 'PT V0.8.35' in ui; assert 'status_text_set' in ui; assert 'popup' not in ui.lower()
    impl=(PAYLOAD/'pt_asset_tool/rare_rigid_multibone_extent_interactive_candidate.py').read_text(); assert 'manual_output_matches_prevalidated_friendly_delta_plan' in impl; assert 'MANUAL_OUTPUT_NOT_BYTE_IDENTICAL_TO_V0833_MAXX' not in impl

def test_certified_writers_unchanged():
    import hashlib
    for rel,expected in m.EXPECTED_WRITER_HASHES.items(): assert hashlib.sha256((PAYLOAD/rel).read_bytes()).hexdigest()==expected
