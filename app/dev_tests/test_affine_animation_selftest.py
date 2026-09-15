from __future__ import annotations

import json
import pathlib

import pt_asset_tool.affine_animation_selftest as mod


class Settings:
    def __init__(self, root: pathlib.Path):
        self.project_root = root

    def blender_command(self):
        return ["fake-blender"]


def test_affine_animation_selftest_requires_build_and_reopen_pass(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, log, timeout_seconds=None, cwd=None):
        calls.append((list(cmd), pathlib.Path(log), timeout_seconds))
        args = list(cmd)
        if "affine_rig_selftest_build.py" in " ".join(args):
            out = pathlib.Path(args[args.index("--out") + 1])
            expected = pathlib.Path(args[args.index("--expected") + 1])
            report = pathlib.Path(args[args.index("--report") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"BLEND")
            expected.write_text(json.dumps({"cases": []}), encoding="utf-8")
            report.write_text(json.dumps({"status": "PASS", "rank_counts": {"3": 1, "2": 1}}), encoding="utf-8")
        else:
            report = pathlib.Path(args[args.index("--report") + 1])
            report.write_text(json.dumps({"status": "PASS", "max_abs_matrix_error": 1e-6}), encoding="utf-8")
        class P:
            returncode = 0
        return P()

    monkeypatch.setattr(mod, "run_logged", fake_run)
    result = mod.run_affine_animation_selftest(Settings(tmp_path), timeout_seconds=12.0)
    assert result["status"] == "PASS"
    assert len(calls) == 2
    assert all(row[2] == 12.0 for row in calls)
    assert result["client_write_authorized"] is False
    assert result["server_write_authorized"] is False


def test_affine_animation_selftest_fails_closed_on_blender_error(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise TimeoutError("synthetic")

    monkeypatch.setattr(mod, "run_logged", fake_run)
    result = mod.run_affine_animation_selftest(Settings(tmp_path), timeout_seconds=1.0)
    assert result["status"] == "FAIL"
    assert "TimeoutError" in result["failure"]
    assert pathlib.Path(result["report"]).is_file()


def test_affine_helper_edit_bone_must_not_be_connected():
    """The first affine factor needs all three translation DOFs in Blender."""
    source = (
        pathlib.Path(__file__).parents[1]
        / "pt_asset_tool"
        / "blender"
        / "bake_actions.py"
    ).read_text(encoding="utf-8")
    install = source[source.index("def _install_affine_controls"):source.index("def _matrix3_rows")]
    assert "ctrl.use_connect=False" in install
    assert "ctrl.use_connect=bool(eb.use_connect)" not in install


def test_affine_selftest_exercises_connected_source_bone():
    source = (
        pathlib.Path(__file__).parents[1]
        / "pt_asset_tool"
        / "blender"
        / "affine_rig_selftest_build.py"
    ).read_text(encoding="utf-8")
    assert 'src = arm_data.edit_bones.new("Source")' in source
    assert "src.use_connect = True" in source
    assert '"SHEAR_FULL_RANK"' in source


def test_affine_selftest_uses_blender_hierarchy_conversion_for_target():
    source = (
        pathlib.Path(__file__).parents[1]
        / "pt_asset_tool"
        / "blender"
        / "affine_rig_selftest_build.py"
    ).read_text(encoding="utf-8")
    assert "def _pose_from_basis_original_hierarchy" in source
    assert "convert_local_to_pose" in source
    assert "expected_pose_by_frame" in source
    assert "BLENDER_CONVERT_LOCAL_TO_POSE_RESIDUAL_V2" in source
    # A physical failure must leave matrix evidence instead of only an exception.
    assert '"live_failures"' in source
    assert '"actual_source_matrix"' in source


def test_affine_split_uses_blender_residual_for_second_factor_and_blocks_singular_parent():
    source = (
        pathlib.Path(__file__).parents[1]
        / "pt_asset_tool"
        / "blender"
        / "bake_actions.py"
    ).read_text(encoding="utf-8")
    assert "def _derive_blender_residual_basis" in source
    assert "convert_local_to_pose" in source
    assert "parent_matrix=helper_pose" in source
    assert "rank-deficient non-TRS affine basis is not Blender-certified" in source
    assert "SVD_BLENDER_RESIDUAL_TWO_BONE_TRS_V2" in source


def test_affine_selftest_declares_rank_deficient_nontrs_expected_block():
    source = (
        pathlib.Path(__file__).parents[1]
        / "pt_asset_tool"
        / "blender"
        / "affine_rig_selftest_build.py"
    ).read_text(encoding="utf-8")
    assert "RANK_DEFICIENT_NON_TRS" in source
    assert "EXPECTED_BLOCKED" in source
    assert "SINGULAR_PARENT_INVERSION_NOT_BLENDER_CERTIFIED" in source
