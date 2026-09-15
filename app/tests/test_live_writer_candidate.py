from __future__ import annotations
import pathlib, tempfile

from pt_asset_tool.certification import CertificationRegistry
from pt_asset_tool import rare_rigid_edit as redit
from pt_asset_tool import rare_rigid_multivertex as mv
from pt_asset_tool.rare_rigid_large_live_writer_candidate import (
    _CandidateCertificationProxy, _candidate_widening, CANDIDATE_TEST, PROBE_MAX,
)


def test_process_local_widening_restores_four():
    assert redit.MAX_TRANSACTION_VERTICES == 4
    assert mv.MAX_TRANSACTION_VERTICES == 4
    with _candidate_widening():
        assert redit.MAX_TRANSACTION_VERTICES == PROBE_MAX == 8
        assert mv.MAX_TRANSACTION_VERTICES == PROBE_MAX
    assert redit.MAX_TRANSACTION_VERTICES == 4
    assert mv.MAX_TRANSACTION_VERTICES == 4


def test_candidate_certification_proxy_relabels_and_isolates():
    with tempfile.TemporaryDirectory() as td:
        reg = CertificationRegistry(pathlib.Path(td))
        proxy = _CandidateCertificationProxy(reg)
        row = proxy.add(
            asset_id="X", asset_path="char/tmABCD/at_dragon.smd", family="F",
            test="RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE", layer="AUTOMATIC", result="PASS",
            metadata={"artist_changed_vertices": 5, "write_scope": "legacy"},
        )
        assert row["test"] == CANDIDATE_TEST
        assert row["metadata"]["candidate_only"] is True
        assert row["metadata"]["production_authorized"] is False
        assert row["metadata"]["candidate_max_vertices"] == 8
        assert len(reg.records()) == 1


def test_candidate_proxy_rejects_wrong_vertex_count():
    with tempfile.TemporaryDirectory() as td:
        proxy = _CandidateCertificationProxy(CertificationRegistry(pathlib.Path(td)))
        try:
            proxy.add(asset_id="X", asset_path="x", family="F", test="RARE_RIGID_ARTIST_GUARDED_TRANSACTION_WRITE", layer="AUTOMATIC", result="PASS", metadata={"artist_changed_vertices": 4})
        except RuntimeError as exc:
            assert "OUTSIDE_5_8" in str(exc)
        else:
            raise AssertionError("expected rejection")
