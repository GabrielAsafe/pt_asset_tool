from __future__ import annotations
import hashlib, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
PAYLOAD=ROOT/'payload'; sys.path.insert(0,str(PAYLOAD))
from pt_asset_tool import rare_rigid_cross_object_interactive_candidate as c
from pt_asset_tool.rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES

def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

def test_release_scope():
    assert c.RELEASE_VERSION=='0.8.28'
    assert c.TARGET_OBJECT_COUNT==2
    assert c.VERTICES_PER_OBJECT==2
    assert c.MAX_TOTAL==8
    assert 'INTERACTIVE_CANDIDATE_MANUAL_WRITE' in c.FORMAT

def test_prior_v0826_strict_gate(tmp_path):
    p=tmp_path/c.PRIOR_REPORT; p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
      'format':'PT_RARE_RIGID_CROSS_OBJECT_LIVE_WRITER_CANDIDATE_AUDIT_V1','status':'PASS','release_version':'0.8.26',
      'prior_v0825_gate_pass':True,'candidate_object_counts':[2,3],'candidate_total_changed_vertices':[4,6],
      'candidate_max_total_changed_vertices':8,'candidate_vertices_per_object':2,
      'production_exact_core_writer_cross_object_blocked':True,'negative_bounds_blocked':True,'nine_vertex_blocked':True,
      'real_certification_registry_modified':False,'production_policy_modified':False,'writer_modules_modified':False,'client_modified':False,
      'process_local_limits_restored_to_4':True,'production_single_object_max_vertices':8,'cross_object_live_write_authorized':False,
      'manual_artist_proof_required_before_cross_object_authorization':True,
      'rows':[{'status':'PASS','object_count':2,'object_indices':[0,5],'per_object_changed_vertex_indices':{'0':[33,155],'5':[6,7]}}]
    }),encoding='utf-8')
    assert c._prior(tmp_path)['status']=='PASS'

def test_prior_two_object_shape():
    prior={'rows':[{'status':'PASS','object_count':2,'object_indices':[0,5],'per_object_changed_vertex_indices':{'0':[33,155],'5':[6,7]}}]}
    objs,per=c._prior_two_object_shape(prior)
    assert objs==[0,5] and per=={0:[33,155],5:[6,7]}

def test_uniform_plan_constructs_common_delta(monkeypatch):
    rows={1:{'vertex_index':1,'before_world_fixed':[10,20,30]},2:{'vertex_index':2,'before_world_fixed':[40,50,60]}}
    seen=[]
    def fake(prepared,skeleton,changes):
        seen.extend(changes)
        return {'object_index':0,'changed_vertex_count':2,'changed_vertex_indices':[1,2],
                'changed_vertices':[{'vertex_index':1,'requested_after_world_fixed':changes[0]['after_world_fixed']},{'vertex_index':2,'requested_after_world_fixed':changes[1]['after_world_fixed']}]}
    monkeypatch.setattr(c.mv,'plan_requested_at_dragon_transaction',fake)
    plan=c._plan_uniform_pair(pathlib.Path('a'),pathlib.Path('b'),0,rows,(1,2),0,64)
    assert plan is not None
    assert seen[0]['after_world_fixed']==[74,20,30]
    assert seen[1]['after_world_fixed']==[104,50,60]

def test_manual_candidate_uses_no_popup():
    text=(PAYLOAD/'pt_asset_tool/blender/open_rare_rigid_cross_object_manual_candidate.py').read_text(encoding='utf-8')
    assert 'popup_menu' not in text
    assert 'status_text_set' in text

def test_selection_helper_clears_all_domains_and_reopens():
    text=(PAYLOAD/'pt_asset_tool/blender/ensure_rare_rigid_cross_object_manual_selection.py').read_text(encoding='utf-8')
    assert "for v in o.data.vertices: v.select=False" in text
    assert "for e in o.data.edges: e.select=False" in text
    assert "for f in o.data.polygons: f.select=False" in text
    assert 'REOPEN_SELECTION_MISMATCH' in text
    assert '--verify-only' in text
    lookup=text.index('bm.verts.ensure_lookup_table()')
    indexed=text.index('bm.verts[vi].select_set(True)')
    assert lookup < indexed

def test_v0827_physical_failure_is_required_and_classified(tmp_path):
    p=tmp_path/c.PRIOR_FAILED_MANUAL_REPORT; p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
      'format':'PT_RARE_RIGID_CROSS_OBJECT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
      'status':'FAIL','release_version':'0.8.27','logical':'char/tmABCD/at_dragon.smd',
      'error':"RuntimeError:command failed rc=1; log=x/selection/01_prepare_selection.log; tail=File 'ensure_rare_rigid_cross_object_manual_selection.py' | IndexError: BMElemSeq[index]: outdated internal index table, run ensure_lookup_table() first",
      'production_single_object_max_vertices':8,'cross_object_live_write_authorized':False
    }),encoding='utf-8')
    r=c._prior_v0827_failure(tmp_path)
    assert r['status']=='FAIL'


def test_manual_path_uses_live_candidate_and_production_negative():
    text=(PAYLOAD/'pt_asset_tool/rare_rigid_cross_object_interactive_candidate.py').read_text(encoding='utf-8')
    assert 'write_at_dragon_cross_object_candidate_workspace' in text
    assert '_exact_production_core_still_blocks' in text
    assert 'ready_for_cross_object_promotion_gate' in text
    assert "cross_object_live_write_authorized':False" in text

def test_wrapper_routes_manual_command():
    text=(PAYLOAD/'pt_asset.py').read_text(encoding='utf-8')
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'rare-model-cross-object-candidate' in text
    assert 'rare_rigid_cross_object_interactive_candidate' in text

def test_certified_writers_unchanged():
    for rel,expected in EXPECTED_WRITER_HASHES.items(): assert sha(PAYLOAD/rel)==expected
