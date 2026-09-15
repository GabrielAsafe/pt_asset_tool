from __future__ import annotations

from types import SimpleNamespace


def _identity():
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _motion(index: int, state: str, start: int = 0, end: int = 3, engine_end: int = 480):
    return {
        "index": index,
        "state_name": state,
        "repeat": 0,
        "motion_frame": 1,
        "active_container": True,
        "global_start": start,
        "global_end": end,
        "engine_start": start * 160,
        "engine_end": engine_end,
    }


def test_motion_all_mode_parses_context_once_and_caches_repeated_pose_calls(monkeypatch, tmp_path):
    import pt_asset_tool.motion_core as core
    import pt_asset_tool.animation_source_regression as regression

    counts = {"parse_inx": 0, "parse_smb": 0, "evaluate_pose": 0}
    motions = [_motion(0, "STAND"), _motion(1, "WALK")]

    class Eval:
        def parse_smb(self, _path):
            counts["parse_smb"] += 1
            return {"bones": [{"name": "Bip01", "tm": _identity()}]}

        def evaluate_pose(self, _smb, _engine, _engine_end):
            counts["evaluate_pose"] += 1
            return ([_identity()], None, None, None)

    class Inx:
        def parse_inx(self, _path):
            counts["parse_inx"] += 1
            return {"layout": {"name": "synthetic"}, "motion_count": len(motions), "motions": []}

        def validate_with_smb(self, _parsed, _smb_path):
            return {"check": "PASS"}

    monkeypatch.setattr(core, "load_motion_system", lambda *_a, **_k: (Eval(), Inx()))
    monkeypatch.setattr(core, "enrich_motions", lambda *_a, **_k: list(motions))

    result = regression.audit_animation_source_regression(
        tmp_path, tmp_path / "x.inx", tmp_path / "x.smb", mode="all"
    )
    assert result["status"] == "PASS"
    assert result["audited_motion_count"] == 2
    assert counts["parse_inx"] == 1
    assert counts["parse_smb"] == 1
    # Both motions request the same three (engine, engine_end) evaluations.
    assert counts["evaluate_pose"] == 3


def test_motion_pose_cache_does_not_merge_different_engine_end(monkeypatch, tmp_path):
    import pt_asset_tool.motion_core as core
    import pt_asset_tool.animation_source_regression as regression

    counts = {"evaluate_pose": 0}
    motions = [_motion(0, "STAND", engine_end=480), _motion(1, "WALK", engine_end=640)]

    class Eval:
        def parse_smb(self, _path):
            return {"bones": [{"name": "Bip01", "tm": _identity()}]}
        def evaluate_pose(self, _smb, _engine, _engine_end):
            counts["evaluate_pose"] += 1
            return ([_identity()], None, None, None)

    class Inx:
        def parse_inx(self, _path):
            return {"layout": {"name": "synthetic"}, "motion_count": len(motions), "motions": []}
        def validate_with_smb(self, _parsed, _smb_path):
            return {"check": "PASS"}

    monkeypatch.setattr(core, "load_motion_system", lambda *_a, **_k: (Eval(), Inx()))
    monkeypatch.setattr(core, "enrich_motions", lambda *_a, **_k: list(motions))
    result = regression.audit_animation_source_regression(
        tmp_path, tmp_path / "x.inx", tmp_path / "x.smb", mode="all"
    )
    assert result["status"] == "PASS"
    # Same frame numbers but different engine_end are semantically distinct calls.
    assert counts["evaluate_pose"] == 6


def test_exact_rigid_zero_score_has_valid_witness(monkeypatch, tmp_path):
    import pt_asset_tool.motion_core as core

    motion=_motion(0,"STAND",start=0,end=2,engine_end=320)

    class Eval:
        def parse_smb(self,_path):
            return {"bones":[{"name":"Bip01","tm":_identity()}]}
        def evaluate_pose(self,_smb,_engine,_engine_end):
            # Exactly the bind pose: every rigidity metric is exactly zero.
            return ([_identity()],None,None,None)
    class Inx:
        def parse_inx(self,_path):
            return {"layout":{"name":"synthetic"},"motion_count":1,"motions":[]}
        def validate_with_smb(self,_parsed,_smb_path):
            return {"check":"PASS"}

    monkeypatch.setattr(core,"load_motion_system",lambda *_a,**_k:(Eval(),Inx()))
    monkeypatch.setattr(core,"enrich_motions",lambda *_a,**_k:[motion])
    prepared=core.prepare_motion_source_audit(tmp_path,tmp_path/"x.inx",tmp_path/"x.smb")
    row=core.analyze_prepared_motion(prepared,motion)
    assert row["frames"] == 2
    assert row["worst_rigidity"]["score"] == 0.0
    assert row["worst_rigidity"]["bone"] == "Bip01"
