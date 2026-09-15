from __future__ import annotations
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payload'))
from pt_asset_tool.rare_rigid_large_transaction_probe import _beam_candidate_sets


def row(vi, faces, affected, bone):
    return {
        "vertex_index": vi,
        "incident_face_indices": faces,
        "affected_vertices": [{"vertex_index": x} for x in affected],
        "affected_bones": [bone],
        "max_target_reimport_normal_error_fixed": 0,
        "requested_reimport_error_fixed": 0,
        "max_current_source_normal_delta_fixed": 1,
    }


def test_probe_beam_counts_5_to_8():
    rows = [
        row(1,[10],[1,2,3],"A"),
        row(2,[10,11],[1,2,3,4],"B"),
        row(3,[11,12],[2,3,4,5],"C"),
        row(4,[12,13],[3,4,5,6],"D"),
        row(5,[13,14],[4,5,6,7],"E"),
        row(6,[14,15],[5,6,7,8],"F"),
        row(7,[15,16],[6,7,8,9],"G"),
        row(8,[16],[7,8,9],"H"),
    ]
    for n in (5,6,7,8):
        got = _beam_candidate_sets(rows, n, beam_limit=64)
        assert got, n
        assert all(len(c) == n for c in got)
