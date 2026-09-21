from __future__ import annotations

import json
from types import SimpleNamespace

from pt_asset_tool.client_enrichment import asset_analysis_evidence, build_client_enrichment_summary


def test_asset_analysis_evidence_surfaces_completed_and_inflight_artifacts(tmp_path):
    work_root = tmp_path / "pt_build" / "pt_asset_tool"
    asset_id = "AST-TEST"
    structural = work_root / asset_id / "structural"
    visual = work_root / asset_id / "visual_geometry"
    structural.mkdir(parents=True)
    visual.mkdir(parents=True)
    (structural / "summary.json").write_text(json.dumps({"check": "PASS", "mode": "STATIC", "authoring_ready_v1": True}), encoding="utf-8")
    (structural / "static_capability.json").write_text(json.dumps({"status": "PASS", "ready_objects": ["x"]}), encoding="utf-8")
    (visual / "witness.json").write_text(json.dumps({"status": "PASS", "format": "WITNESS_V1"}), encoding="utf-8")
    (visual / "texture_overlay_report.json").write_text(json.dumps({"status": "PASS", "entries": [{"logical": "x.bmp"}]}), encoding="utf-8")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "assets.jsonl").write_text(json.dumps({
        "asset_id": asset_id, "test": "STRUCTURAL", "layer": "AUTOMATIC", "result": "PASS", "timestamp": "2026-09-18T19:00:00Z"
    }) + "\n", encoding="utf-8")
    settings = SimpleNamespace(work_dir=work_root, certifications_dir=certs)

    result = asset_analysis_evidence(settings, asset_id)
    assert result["status"] == "AVAILABLE"
    assert result["reports"]["structural"]["result"] == "PASS"
    assert result["artifacts"]["structural_static_capability"]["result"] == "PASS"
    assert result["artifacts"]["visual_witness"]["format"] == "WITNESS_V1"
    assert result["artifacts"]["visual_texture_overlay"]["entry_count"] == 1
    assert result["certifications"][0]["test"] == "STRUCTURAL"


def test_client_enrichment_summary_uses_existing_pt_build_evidence_without_writes(tmp_path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    client.mkdir(parents=True)
    registry_dir = project / "pt_build" / "state" / "asset_registry"
    registry_dir.mkdir(parents=True)
    (registry_dir / "registry_meta.json").write_text(json.dumps({"record_count": 2, "client_root": str(client)}), encoding="utf-8")
    certs = project / "pt_build" / "certifications"
    certs.mkdir(parents=True)
    (certs / "assets.jsonl").write_text("", encoding="utf-8")
    contracts = project / "pt_build" / "asset_contracts"
    contracts.mkdir(parents=True)
    (contracts / "player_class_contract_census.json").write_text(json.dumps({"status": "PASS", "class_count": 10}), encoding="utf-8")
    vendor = project / "pt_build" / "enrichment_vendor"
    vendor.mkdir(parents=True)
    (vendor / "dependency_graph.result.json").write_text(json.dumps({"status": "PASS", "summary_data": {"nodes": 11, "edges": 19, "missing_reference_edges": 2}}), encoding="utf-8")

    rows = [
        {"path": "char/npc/Test/Test.smd", "category": "NPC", "role": "MODEL", "visibility_tier": "GAME_ASSET", "physical_hint": "SMD_MODEL_062_STATIC", "ext": ".smd", "name": "Test.smd", "folder": "Test", "folder_path": "char/npc/Test"},
        {"path": "Thumbs.db", "category": "SYSTEM", "role": "NOISE", "visibility_tier": "NOISE", "physical_hint": "OTHER", "ext": ".db", "name": "Thumbs.db", "folder": "root", "folder_path": ""},
    ]
    catalog = SimpleNamespace(assets=rows, stats=SimpleNamespace(total_bytes=1234))
    settings = SimpleNamespace(
        inventory=registry_dir / "asset_inventory.json",
        certifications_dir=certs,
    )

    result = build_client_enrichment_summary(project, client, catalog, None, registry=None, settings=settings)
    assert result["status"] == "READY"
    assert result["catalog"]["file_count"] == 2
    assert result["catalog"]["default_hidden_count"] == 1
    assert result["registry"]["record_count"] == 2
    assert result["reports"]["player_classes"]["class_count"] == 10
    assert result["reports"]["vendor_graph"]["nodes"] == 11
    assert result["reports"]["client_census"]["status"] == "NOT_RUN"
    assert result["policy"]["client_write_only_via_verified_bundle"] is True
    assert result["client_modified"] is False


def test_client_enrichment_audit_persists_entity_gaps_and_query_filters(tmp_path):
    from pt_asset_tool.client_enrichment import audit_client_enrichment, query_client_enrichment_report

    project = tmp_path / "project"
    client = tmp_path / "client"
    client.mkdir(parents=True)
    certs = project / "pt_build" / "certifications"
    certs.mkdir(parents=True)
    (certs / "assets.jsonl").write_text("", encoding="utf-8")
    rows = [
        {"path": "char/npc/Test/Test.smd", "category": "NPC", "role": "MODEL", "visibility_tier": "GAME_ASSET", "physical_hint": "SMD_MODEL_062_STATIC", "physical_family": "SMD_MODEL_062_STATIC", "ext": ".smd", "name": "Test.smd", "folder": "Test", "folder_path": "char/npc/Test", "size": 100, "previewable": False},
        {"path": "Image/Items/DropItem/IT001.bmp", "category": "ITEM", "role": "TEXTURE", "visibility_tier": "GAME_ASSET", "physical_hint": "TEXTURE", "physical_family": "TEXTURE", "ext": ".bmp", "name": "IT001.bmp", "folder": "DropItem", "folder_path": "Image/Items/DropItem", "size": 50, "previewable": True},
    ]
    catalog = SimpleNamespace(assets=rows, stats=SimpleNamespace(total_bytes=150))
    settings = SimpleNamespace(certifications_dir=certs)
    registry = SimpleNamespace(assets=[])

    result = audit_client_enrichment(project, client, catalog, None, registry=registry, settings=settings)
    assert result["status"] == "PASS"
    assert result["entities"]["partial_evidence_count"] >= 1
    assert result["issues"]["count"] >= 1
    assert (project / "pt_build" / "client_enrichment" / "result.json").is_file()
    assert result["client_modified"] is False

    q = query_client_enrichment_report(project, group="NPC", limit=20)
    assert q["status"] == "PASS"
    assert q["filtered_rows"] >= 1
    assert all(row["group"] == "NPC" for row in q["rows"])


def test_client_enrichment_applies_actor_binding_rules_only_to_actor_models(tmp_path):
    from pt_asset_tool.client_enrichment import audit_client_enrichment

    project = tmp_path / "project"
    client = tmp_path / "client"
    client.mkdir(parents=True)
    certs = project / "pt_build" / "certifications"
    certs.mkdir(parents=True)
    (certs / "assets.jsonl").write_text("", encoding="utf-8")

    rows = [
        {"path": "Effect/Test/static.smd", "category": "EFFECT", "role": "MODEL", "visibility_tier": "GAME_ASSET", "physical_family": "MODEL", "ext": ".smd", "name": "static.smd", "folder": "Test", "folder_path": "Effect/Test", "size": 100, "previewable": False},
        {"path": "Effect/Test/static.tga", "category": "EFFECT", "role": "TEXTURE", "visibility_tier": "GAME_ASSET", "physical_family": "TEXTURE", "ext": ".tga", "name": "static.tga", "folder": "Test", "folder_path": "Effect/Test", "size": 50, "previewable": True},
        {"path": "wav/Effects/monster/FakeActor/hit.wav", "category": "MONSTER", "role": "AUDIO", "visibility_tier": "GAME_ASSET", "physical_family": "AUDIO", "ext": ".wav", "name": "hit.wav", "folder": "FakeActor", "folder_path": "wav/Effects/monster/FakeActor", "size": 10, "previewable": False},
    ]
    catalog = SimpleNamespace(assets=rows, stats=SimpleNamespace(total_bytes=160))
    effect_asset = SimpleNamespace(
        asset_id="EFFECT-STATIC", primary_path="Effect/Test/static.smd", category="EFFECT",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        textures=["Effect/Test/static.tga"], configs=[], motions=[],
        rigid_context_ready=False, animation_binding_ready=False, binding_source="NONE",
    )
    registry = SimpleNamespace(assets=[effect_asset], pairing=[])
    settings = SimpleNamespace(certifications_dir=certs)

    result = audit_client_enrichment(project, client, catalog, None, registry=registry, settings=settings)
    rows_out = result["issues"]["rows"]
    assert not any(row["target"] == "EFFECT-STATIC" and "NO_MODEL_INFO_CONFIG" in row["reasons"] for row in rows_out)
    assert not any(row["target"] == "EFFECT-STATIC" and "RIGID_CONTEXT_UNRESOLVED" in row["reasons"] for row in rows_out)
    assert not any(row["group"] == "MONSTER" and "FakeActor" in str(row.get("path")) for row in rows_out)


def test_client_enrichment_animation_gap_only_counts_models_with_animation_expectation(tmp_path):
    from pt_asset_tool.client_enrichment import audit_client_enrichment

    project = tmp_path / "project"
    client = tmp_path / "client"
    client.mkdir(parents=True)
    certs = project / "pt_build" / "certifications"
    certs.mkdir(parents=True)
    (certs / "assets.jsonl").write_text("", encoding="utf-8")
    rows = [
        {"path": "char/npc/Test/body.smd", "category": "NPC", "role": "MODEL", "visibility_tier": "GAME_ASSET", "physical_family": "MODEL", "ext": ".smd", "name": "body.smd", "folder": "Test", "folder_path": "char/npc/Test", "size": 100, "previewable": False},
        {"path": "char/npc/Test/body.tga", "category": "NPC", "role": "TEXTURE", "visibility_tier": "GAME_ASSET", "physical_family": "TEXTURE", "ext": ".tga", "name": "body.tga", "folder": "Test", "folder_path": "char/npc/Test", "size": 50, "previewable": True},
    ]
    catalog = SimpleNamespace(assets=rows, stats=SimpleNamespace(total_bytes=150))
    static_actor = SimpleNamespace(
        asset_id="NPC-STATIC", primary_path="char/npc/Test/body.smd", category="NPC",
        family="SMD_MODEL_062_RIGID_PHYSIQUE", kind="SMD_MODEL_062",
        textures=["char/npc/Test/body.tga"], configs=[{"inx": "char/npc/Test/body.inx"}], motions=[],
        rigid_context_ready=True, rigid_binding_ready=True, animation_binding_ready=False,
        binding_skeleton_smb="", binding_mode="ROOT_SKELETON_BOUND", binding_source="VERIFIED_INX_LINKFILE",
    )
    registry = SimpleNamespace(assets=[static_actor], pairing=[])
    settings = SimpleNamespace(certifications_dir=certs)

    result = audit_client_enrichment(project, client, catalog, None, registry=registry, settings=settings)
    entity_issues = [x for x in result["issues"]["rows"] if x["kind"] == "ENTITY_RELATION_GAP"]
    assert not any("ANIMATION_CONTEXT_PARTIAL" in x["reasons"] for x in entity_issues)


def test_client_enrichment_promotes_reachable_missing_assets_from_general_census(tmp_path):
    from pt_asset_tool.client_enrichment import audit_client_enrichment, query_client_enrichment_report

    project = tmp_path / "project"
    client = tmp_path / "client"
    client.mkdir(parents=True)
    certs = project / "pt_build" / "certifications"
    certs.mkdir(parents=True)
    (certs / "assets.jsonl").write_text("", encoding="utf-8")
    census = project / "pt_build" / "general_asset_census"
    census.mkdir(parents=True)
    (census / "result.json").write_text(json.dumps({"status": "PASS", "census_state": "REVIEW_REQUIRED"}), encoding="utf-8")
    header = ["side", "decision", "required_by_reachable_root", "path", "extension", "physical_family", "category", "reachability_evidence", "review_evidence", "reason", "selected_source", "recovery_bundle_status", "recovery_bundle_member_count"]
    rows_tsv = [
        ["CLIENT", "RECOVERABLE_REACHABLE_CANDIDATE", "true", "char/monster/Missing/Missing.smd", ".smd", "MODEL", "MONSTER", "SERVER_ENTITY_MODEL", "", "", "/donor/Missing.smd", "CLOSED", "3"],
        ["CLIENT", "MISSING_REACHABLE_NO_DONOR", "true", "Effect/Required/missing.tga", ".tga", "TEXTURE", "EFFECT", "SOURCE_LITERAL", "", "", "", "", "0"],
        ["CLIENT", "REVIEW_HARD_CONFLICT", "false", "unused.bin", ".bin", "OTHER", "OTHER", "", "review only", "", "", "", "0"],
    ]
    (census / "candidates.tsv").write_text("\t".join(header) + "\n" + "\n".join("\t".join(r) for r in rows_tsv) + "\n", encoding="utf-8")

    catalog = SimpleNamespace(assets=[], stats=SimpleNamespace(total_bytes=0))
    settings = SimpleNamespace(certifications_dir=certs)
    registry = SimpleNamespace(assets=[])
    result = audit_client_enrichment(project, client, catalog, None, registry=registry, settings=settings)
    avail = result["asset_availability"]
    assert avail["actionable_count"] == 2
    assert avail["decision_counts"]["RECOVERABLE_REACHABLE_CANDIDATE"] == 1
    assert avail["decision_counts"]["MISSING_REACHABLE_NO_DONOR"] == 1
    issues = [x for x in result["issues"]["rows"] if x["kind"] == "CLIENT_ASSET_AVAILABILITY"]
    assert {x["state"] for x in issues} == {"RECOVERABLE", "MISSING"}
    assert any(x["suggested_action"] == "RESTORE_FROM_VERIFIED_DONOR" for x in issues)
    assert any(x["suggested_action"] == "LOCATE_OR_RECONSTRUCT_REQUIRED_ASSET" for x in issues)

    q = query_client_enrichment_report(project, query="restore_from_verified_donor")
    assert q["filtered_rows"] == 1
