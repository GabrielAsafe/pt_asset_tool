from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.build_provenance import write_build_provenance, verify_build_provenance
from pt_asset_tool.deployment import plan_deployment


class Registry:
    def __init__(self, asset): self.asset = asset
    def resolve(self, target): return self.asset


class Resolver:
    def __init__(self, source): self.source = Path(source)
    def resolve(self, logical): return self.source


def _asset(path="char/test/body.smd", family="SMD_MODEL_062_STATIC", visual_mode="STATIC"):
    return SimpleNamespace(
        asset_id="AST-TEST", primary_path=path, family=family,
        kind="SMD_MODEL_062", visual_mode=visual_mode,
    )


def test_candidate_build_provenance_is_integral_but_not_publish_authorized(tmp_path):
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "body.smd"; artifact.parent.mkdir(); artifact.write_bytes(b"edited")
    asset = _asset()
    prov = write_build_provenance(
        artifact, asset=asset, source=source,
        build_mode="CANDIDATE_STATIC", adapter="writer.py",
        build_status="PASS", production_authorized=False,
    )
    assert prov.is_file()
    verified = verify_build_provenance(
        artifact, expected_asset_id=asset.asset_id,
        expected_asset_path=asset.primary_path, expected_source=source,
    )
    assert verified["status"] == "PASS"
    assert verified["production_authorized"] is False
    plan = plan_deployment(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    assert "BUILD_PROVENANCE_NOT_PRODUCTION_AUTHORIZED" in plan["blockers"]
    assert plan["build_provenance"]["status"] == "PASS"
    assert plan["client_write_authorized"] is False


def test_production_build_provenance_passes_provenance_gate_but_not_deploy_policy(tmp_path):
    from pt_asset_tool.deployment import prepare_deployment_transaction, verify_deployment_transaction
    source = tmp_path / "client" / "at_dragon.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    artifact = tmp_path / "pt_build" / "at_dragon.smd"; artifact.parent.mkdir(); artifact.write_bytes(b"edited")
    asset = _asset("char/tmABCD/at_dragon.smd", family="SMD_MODEL_062_VARIANT_OR_DAMAGED", visual_mode="RIGID")
    write_build_provenance(
        artifact, asset=asset, source=source,
        build_mode="PRODUCTION_CERTIFIED", adapter="RARE_RIGID_AT_DRAGON_CERTIFIED",
        build_status="PASS", production_authorized=True,
    )
    plan = plan_deployment(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    assert plan["writer_plan"]["authorized"] is True
    assert plan["build_provenance"]["production_authorized"] is True
    assert "BUILD_PROVENANCE_INVALID" not in plan["blockers"]
    assert "BUILD_PROVENANCE_NOT_PRODUCTION_AUTHORIZED" not in plan["blockers"]
    assert "GENERIC_CLIENT_DEPLOYMENT_POLICY_NOT_PROMOTED" in plan["blockers"]
    assert plan["client_write_authorized"] is False
    tx = prepare_deployment_transaction(tmp_path, Resolver(source), Registry(asset), asset.primary_path, artifact)
    snap = tx["build_provenance_snapshot"]
    assert snap is not None
    assert Path(snap["path"]).is_file()
    verified = verify_deployment_transaction(tx["manifest"])
    assert verified["status"] == "PASS"
    assert verified["build_provenance_snapshot_ready"] is True


def test_build_provenance_detects_artifact_drift(tmp_path):
    source = tmp_path / "source.smd"; source.write_bytes(b"source")
    artifact = tmp_path / "artifact.smd"; artifact.write_bytes(b"edited")
    asset = _asset()
    write_build_provenance(
        artifact, asset=asset, source=source,
        build_mode="CANDIDATE_STATIC", adapter="writer.py",
        build_status="PASS", production_authorized=False,
    )
    artifact.write_bytes(b"tampered")
    verified = verify_build_provenance(artifact, expected_asset_id=asset.asset_id, expected_asset_path=asset.primary_path, expected_source=source)
    assert verified["status"] == "FAIL"
    assert "ARTIFACT_SHA_DRIFT" in verified["errors"]


def test_rigid_candidate_build_provenance_carries_selected_context_and_detects_context_drift(tmp_path):
    from pt_asset_tool.authoring import build_selected_authoring_context
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    inx = tmp_path / "client" / "body.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    artifact = tmp_path / "pt_build" / "body.smd"; artifact.parent.mkdir(); artifact.write_bytes(b"edited")
    asset = _asset(family="SMD_MODEL_062_RIGID_PHYSIQUE", visual_mode="RIGID")
    context = build_selected_authoring_context(
        model_info_logical="char/test/body.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups={"default":["Body"]},
    )
    write_build_provenance(
        artifact, asset=asset, source=source,
        build_mode="CANDIDATE_RIGID", adapter="writer.py",
        build_status="PASS", production_authorized=False,
        selected_context=context,
    )
    verified = verify_build_provenance(
        artifact, expected_asset_id=asset.asset_id,
        expected_asset_path=asset.primary_path, expected_source=source,
    )
    assert verified["status"] == "PASS"
    assert verified["selected_context"]["lod"] == "default"
    inx.write_bytes(b"drift")
    drift = verify_build_provenance(
        artifact, expected_asset_id=asset.asset_id,
        expected_asset_path=asset.primary_path, expected_source=source,
    )
    assert drift["status"] == "FAIL"
    assert "SELECTED_CONTEXT_DRIFT" in drift["errors"]


def test_standalone_rigid_provenance_binds_explicit_skeleton_context(tmp_path):
    from pt_asset_tool.authoring import build_standalone_rigid_authoring_context
    source = tmp_path / "client" / "piece.smd"; source.parent.mkdir(); source.write_bytes(b"source")
    smb = tmp_path / "client" / "class.smb"; smb.write_bytes(b"skeleton")
    gate = tmp_path / "gate.json"; gate.write_text('{"status":"PASS"}')
    artifact = tmp_path / "pt_build" / "piece.smd"; artifact.parent.mkdir(); artifact.write_bytes(b"edited")
    asset = _asset(path="char/test/piece.smd", family="SMD_MODEL_062_RIGID_PHYSIQUE", visual_mode="RIGID")
    context = build_standalone_rigid_authoring_context(
        asset_logical=asset.primary_path, source_path=source,
        skeleton_logical="char/test/class.smb", skeleton_path=smb,
        selected_nodes=["Piece"], structural_gate_report=gate,
        selection_basis={"kind":"EXPLICIT_SKELETON","roundtrip_target":asset.primary_path,"structural_gate":"PASS"},
    )
    write_build_provenance(
        artifact, asset=asset, source=source, build_mode="CANDIDATE_RIGID",
        adapter="writer.py", build_status="PASS", production_authorized=False,
        selected_context=context,
    )
    verified = verify_build_provenance(artifact, expected_asset_id=asset.asset_id, expected_asset_path=asset.primary_path, expected_source=source)
    assert verified["status"] == "PASS"
    assert verified["selected_context"]["format"] == "PT_ASSET_STANDALONE_RIGID_CONTEXT_V1"
    smb.write_bytes(b"drift")
    drift = verify_build_provenance(artifact, expected_asset_id=asset.asset_id, expected_asset_path=asset.primary_path, expected_source=source)
    assert drift["status"] == "FAIL"
    assert "SELECTED_CONTEXT_DRIFT" in drift["errors"]


def test_mixed_candidate_provenance_requires_selected_context(tmp_path):
    source = tmp_path / "source.smd"; source.write_bytes(b"source")
    artifact = tmp_path / "artifact.smd"; artifact.write_bytes(b"edited")
    asset = _asset(path="char/test/mixed.smd", family="SMD_MODEL_062_MIXED_PHYSIQUE", visual_mode="MIXED")
    write_build_provenance(
        artifact, asset=asset, source=source, build_mode="CANDIDATE_MIXED",
        adapter="mixed.py", build_status="PASS", production_authorized=False,
    )
    verified = verify_build_provenance(artifact, expected_asset_id=asset.asset_id, expected_asset_path=asset.primary_path, expected_source=source)
    assert verified["status"] == "FAIL"
    assert "SELECTED_CONTEXT_MISSING" in verified["errors"]
