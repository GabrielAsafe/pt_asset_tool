from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.deployment import plan_deployment


class Registry:
    def __init__(self, asset):
        self.asset = asset
    def resolve(self, target):
        return self.asset


class Resolver:
    def __init__(self, source):
        self.source = Path(source)
    def resolve(self, logical):
        return self.source


def _asset(path="char/test/body.smd", family="SMD_MODEL_062_STATIC", visual_mode="STATIC"):
    return SimpleNamespace(
        asset_id="AST-TEST",
        primary_path=path,
        family=family,
        kind="SMD_MODEL_062",
        visual_mode=visual_mode,
    )


def test_deployment_planner_is_read_only_and_blocks_unpromoted_static(tmp_path):
    source = tmp_path / "client" / "body.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "body.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    result = plan_deployment(tmp_path, Resolver(source), Registry(_asset()), "body", artifact)
    assert result["status"] == "BLOCKED"
    assert result["client_write_authorized"] is False
    assert result["apply_mode_available"] is False
    assert result["artifact_inside_pt_build"] is True
    assert result["artifact_differs_from_source"] is True
    assert "ASSET_WRITER_NOT_PRODUCTION_AUTHORIZED" in result["blockers"]
    assert source.read_bytes() == b"source"


def test_deployment_planner_rejects_artifact_outside_pt_build(tmp_path):
    source = tmp_path / "client" / "body.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "outside.smd"
    artifact.write_bytes(b"edited")
    result = plan_deployment(tmp_path, Resolver(source), Registry(_asset()), "body", artifact)
    assert "ARTIFACT_OUTSIDE_PT_BUILD" in result["blockers"]
    assert result["client_write_authorized"] is False


def test_certified_build_still_does_not_imply_client_publish_authorization(tmp_path):
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    result = plan_deployment(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    assert result["writer_plan"]["authorized"] is True
    assert "ASSET_WRITER_NOT_PRODUCTION_AUTHORIZED" not in result["blockers"]
    assert "GENERIC_CLIENT_DEPLOYMENT_POLICY_NOT_PROMOTED" in result["blockers"]
    assert result["client_write_authorized"] is False


def test_deployment_prepare_creates_verified_backup_and_staged_copy_without_client_write(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, verify_deployment_transaction
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    result = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    assert result["status"] == "PREPARED_BLOCKED"
    assert result["backup"]["verified"] is True
    assert result["staged_artifact"]["verified"] is True
    assert result["rollback_material_ready"] is True
    assert result["prewrite_drift_snapshot_ready"] is True
    assert result["client_write_authorized"] is False
    assert result["apply_mode_available"] is False
    assert source.read_bytes() == b"source"
    assert "TRANSACTION_MANIFEST_NOT_CREATED" not in result["remaining_blockers"]
    assert "VERIFIED_BACKUP_AND_ROLLBACK_GATE_REQUIRED" not in result["remaining_blockers"]
    assert "PREWRITE_CLIENT_DRIFT_GATE_REQUIRED" not in result["remaining_blockers"]
    verified = verify_deployment_transaction(result["manifest"])
    assert verified["status"] == "PASS"
    assert verified["client_write_authorized"] is False


def test_deployment_verify_detects_client_drift_after_prepare(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, verify_deployment_transaction
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    result = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    source.write_bytes(b"drifted")
    verified = verify_deployment_transaction(result["manifest"])
    assert verified["status"] == "FAIL"
    assert verified["client_drift"] is True
    assert "CLIENT_DRIFT" in verified["errors"]
    assert verified["client_write_authorized"] is False


def test_deployment_simulation_proves_replace_postwrite_and_rollback_without_client_write(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, simulate_deployment_transaction
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    tx = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    before = source.read_bytes()
    result = simulate_deployment_transaction(tx["manifest"])
    assert result["status"] == "PASS"
    assert result["atomic_replace_pass"] is True
    assert result["postwrite_verification_pass"] is True
    assert result["rollback_pass"] is True
    assert result["failure_injected"] is False
    assert result["client_source_unchanged"] is True
    assert result["client_write_authorized"] is False
    assert source.read_bytes() == before == b"source"
    simulated = Path(result["simulated_destination"])
    assert simulated.read_bytes() == b"source"
    assert str(simulated.resolve()).startswith(str((tmp_path / "pt_build").resolve()))


def test_deployment_simulation_injected_postwrite_failure_is_rolled_back(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, simulate_deployment_transaction
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    tx = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    result = simulate_deployment_transaction(tx["manifest"], inject_failure="postwrite")
    assert result["status"] == "PASS"
    assert result["failure_injected"] is True
    assert "INJECTED_POSTWRITE_FAILURE" in result["caught_error"]
    assert result["atomic_replace_pass"] is True
    assert result["postwrite_verification_pass"] is True
    assert result["rollback_pass"] is True
    assert result["client_source_unchanged"] is True
    assert source.read_bytes() == b"source"
    assert Path(result["simulated_destination"]).read_bytes() == b"source"


def test_deployment_simulation_refuses_drifted_transaction(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, simulate_deployment_transaction
    import pytest
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    tx = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    source.write_bytes(b"drift")
    with pytest.raises(RuntimeError, match="verified transaction"):
        simulate_deployment_transaction(tx["manifest"])


def test_client_state_classifier_and_restore_plan_fail_closed(tmp_path):
    from pt_asset_tool.deployment import (
        prepare_deployment_transaction,
        classify_client_transaction_state,
        plan_restore_transaction,
    )
    source = tmp_path / "client" / "at_dragon.smd"
    source.parent.mkdir()
    source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"
    artifact.parent.mkdir()
    artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    tx = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)

    state = classify_client_transaction_state(tx["manifest"])
    assert state["status"] == "PASS"
    assert state["state"] == "ORIGINAL_SOURCE"
    assert state["restore_candidate"] is False
    restore = plan_restore_transaction(tx["manifest"])
    assert restore["restore_semantically_eligible"] is False
    assert "RESTORE_NOT_NEEDED_CLIENT_IS_ORIGINAL_SOURCE" in restore["blockers"]

    # Simulate a known managed deployment externally; planner may recognize it,
    # but apply remains disabled.
    source.write_bytes(b"edited")
    state = classify_client_transaction_state(tx["manifest"])
    assert state["status"] == "PASS"
    assert state["state"] == "MANAGED_ARTIFACT"
    assert state["restore_candidate"] is True
    restore = plan_restore_transaction(tx["manifest"])
    assert restore["status"] == "RESTORE_CANDIDATE_BLOCKED"
    assert restore["restore_semantically_eligible"] is True
    assert "GENERIC_CLIENT_RESTORE_POLICY_NOT_PROMOTED" in restore["blockers"]
    assert restore["apply_mode_available"] is False

    source.write_bytes(b"unknown drift")
    state = classify_client_transaction_state(tx["manifest"])
    assert state["status"] == "BLOCKED"
    assert state["state"] == "UNKNOWN_DRIFT"
    restore = plan_restore_transaction(tx["manifest"])
    assert restore["restore_semantically_eligible"] is False
    assert "CLIENT_DRIFT_UNKNOWN_REFUSE_RESTORE" in restore["blockers"]


def test_deployment_transaction_carries_selected_authoring_context_and_rechecks_it(tmp_path):
    from pt_asset_tool.authoring import build_selected_authoring_context
    from pt_asset_tool.build_provenance import write_build_provenance
    from pt_asset_tool.deployment import prepare_deployment_transaction, verify_deployment_transaction
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    inx = tmp_path / "client" / "body.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    artifact = tmp_path / "pt_build" / "body.smd"; artifact.parent.mkdir(); artifact.write_bytes(b"edited")
    asset = SimpleNamespace(
        asset_id="AST-TEST", primary_path="char/test/body.smd",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062", visual_mode="RIGID",
        binding_skeleton_smb="char/test/body.smb",
        configs=[{
            "inx":"char/test/body.inx", "motion_smb":"char/test/body.smb",
            "lod_groups":{"default":["Body"]},
        }],
    )
    context = build_selected_authoring_context(
        model_info_logical="char/test/body.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups=asset.configs[0]["lod_groups"],
    )
    write_build_provenance(
        artifact, asset=asset, source=source,
        build_mode="CANDIDATE_RIGID", adapter="writer.py",
        build_status="PASS", production_authorized=False,
        selected_context=context,
    )

    class ContextResolver:
        def resolve(self, logical, required=True):
            logical = str(logical).replace("\\", "/")
            return {
                "char/test/body.smd": source,
                "char/test/body.inx": inx,
                "char/test/body.smb": smb,
            }[logical]
    tx = prepare_deployment_transaction(tmp_path, ContextResolver(), Registry(asset), asset.primary_path, artifact)
    assert tx["selected_context"]["model_info_inx"]["logical"] == "char/test/body.inx"
    verified = verify_deployment_transaction(tx["manifest"])
    assert verified["status"] == "PASS"
    assert verified["selected_context_ready"] is True

    inx.write_bytes(b"drift")
    drift = verify_deployment_transaction(tx["manifest"])
    assert drift["status"] == "FAIL"
    assert "SELECTED_CONTEXT_DRIFT" in drift["errors"]
