from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "payload"))

from pt_asset_tool import rare_rigid_cross_object_probe as c


def test_release_and_scope_constants():
    assert c.RELEASE_VERSION == "0.8.22"
    assert c.PROBE_OBJECT_COUNTS == (2, 3)
    assert "CROSS_OBJECT" in c.FORMAT


def test_in_ranges_union():
    ranges = [[10, 20], [30, 40]]
    assert c._in_ranges(10, ranges)
    assert c._in_ranges(19, ranges)
    assert c._in_ranges(30, ranges)
    assert not c._in_ranges(20, ranges)
    assert not c._in_ranges(29, ranges)


def test_pair_score_prefers_shared_face_and_more_bones():
    a = {
        "changed_vertex_pairs_sharing_face": 1,
        "affected_bone_count": 4,
        "max_target_reimport_normal_error_fixed": 100,
        "max_requested_reimport_error_fixed": 0,
        "max_current_source_normal_delta_fixed": 3000,
        "object_index": 0,
        "changed_vertex_indices": [1, 2],
    }
    b = dict(a)
    b["changed_vertex_pairs_sharing_face"] = 0
    assert c._pair_score(a) < c._pair_score(b)


def test_cross_object_transaction_contract_requires_two_objects():
    tx = {"per_object_plans": []}
    try:
        c.patch_cross_object_transaction(pathlib.Path("x"), pathlib.Path("y"), pathlib.Path("z"), tx)
    except ValueError as exc:
        assert "AT_LEAST_TWO_OBJECT_PLANS" in str(exc)
    else:
        raise AssertionError("expected fail-closed")
