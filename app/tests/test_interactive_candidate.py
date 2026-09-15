import importlib.util, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]/'payload'
sys.path.insert(0,str(ROOT))
from pt_asset_tool import rare_rigid_edit as redit, rare_rigid_multivertex as mv
from pt_asset_tool.rare_rigid_large_interactive_candidate import _widen, RELEASE_VERSION, TARGET_COUNT

def test_version_and_target(): assert RELEASE_VERSION=='0.8.19' and TARGET_COUNT==5

def test_widen_restores():
    assert redit.MAX_TRANSACTION_VERTICES==4 and mv.MAX_TRANSACTION_VERTICES==4
    with _widen(): assert redit.MAX_TRANSACTION_VERTICES==8 and mv.MAX_TRANSACTION_VERTICES==8
    assert redit.MAX_TRANSACTION_VERTICES==4 and mv.MAX_TRANSACTION_VERTICES==4

def test_widen_restores_after_error():
    try:
        with _widen(): raise RuntimeError('x')
    except RuntimeError: pass
    assert redit.MAX_TRANSACTION_VERTICES==4 and mv.MAX_TRANSACTION_VERTICES==4


def test_large_selection_helper_clears_all_mesh_domains():
    helper=(ROOT/'pt_asset_tool/blender/ensure_rare_rigid_large_candidate_selection.py').read_text(encoding='utf-8')
    assert 'bpy.ops.mesh.select_all(action="DESELECT")' in helper
    assert 'for face in bm.faces:' in helper and 'face.select_set(False)' in helper
    assert 'for edge in bm.edges:' in helper and 'edge.select_set(False)' in helper
    assert 'POST_SAVE_SELECTION_MISMATCH' in helper
    assert 'selected_vertex_indices_after_save' in helper

def test_v0818_failed_gate_is_required_and_classified():
    mod=(ROOT/'pt_asset_tool/rare_rigid_large_interactive_candidate.py').read_text(encoding='utf-8')
    assert 'PRIOR_V0818_FAILURE_NOT_EXPECTED_SELECTION_FLUSH_BUG' in mod
    assert 'REOPEN_SELECTION_MISMATCH:' in mod
    assert 'V0.8.20 production-promotion gate' in mod
