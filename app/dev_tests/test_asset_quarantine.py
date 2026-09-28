from __future__ import annotations

import csv
import json
from pathlib import Path

from pt_asset_tool.asset_quarantine import (
    APPLY_CONFIRM,
    Q1_COMPONENT_CONFIRM,
    RESTORE_CONFIRM,
    apply_quarantine_plan,
    apply_q1_component_quarantine,
    build_quarantine_plan,
    restore_quarantine_transaction,
    quarantine_review_queue,
)

FIELDS = [
    "path", "state", "graph_linked", "root_reachable", "entity_bundle", "evidence",
    "cook_status", "cook_documented_outlier", "integrity_action", "deletion_authorized",
    "physical_family", "cook_failure_class", "cook_integrity_state", "cook_asset_classification",
    "cook_runtime_note", "component_id",
]


def _write_retention(project: Path, rows: list[dict[str, str]], components=None):
    out = project / "pt_build" / "asset_retention"
    out.mkdir(parents=True)
    with (out / "assets.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            cooked = {k: row.get(k, "") for k in FIELDS}
            w.writerow(cooked)
    (out / "result.json").write_text(json.dumps({"format": "PT_ASSET_RETENTION_EVIDENCE_V2", "status": "PASS"}), encoding="utf-8")
    (out / "components.json").write_text(json.dumps({"components": components or []}), encoding="utf-8")


def _q0(path: str):
    return {
        "path": path,
        "state": "ORPHAN_CANDIDATE",
        "graph_linked": "False",
        "root_reachable": "False",
        "entity_bundle": "",
        "evidence": "",
        "cook_status": "error",
        "cook_documented_outlier": "True",
        "integrity_action": "INVALID_UNREACHABLE_QUARANTINE_REVIEW",
        "deletion_authorized": "False",
        "physical_family": "TEXTURE",
        "cook_failure_class": "TRUNCATED_INPUT",
        "cook_integrity_state": "KNOWN_INVALID_OR_NON_IMAGE",
        "cook_asset_classification": "NON_IMAGE_TEXT_CONFIG_MISLABELED_BMP",
        "cook_runtime_note": "fixture",
    }


def test_plan_q0_requires_documented_invalid_zero_linkage(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "bad.bmp").write_bytes(b"bad")
    (client / "valid.tga").write_bytes(b"valid")
    rows = [_q0("bad.bmp"), {
        "path": "valid.tga", "state": "ORPHAN_CANDIDATE", "graph_linked": "False", "root_reachable": "False",
        "cook_status": "skipped", "cook_documented_outlier": "False", "integrity_action": "VALID_DECODE_POLICY_SKIPPED",
        "deletion_authorized": "False",
    }]
    _write_retention(project, rows)
    result = build_quarantine_plan(project, client)
    assert result["status"] == "PASS"
    assert result["q0_count"] == 1
    assert result["q0"][0]["path"] == "bad.bmp"
    assert result["deletion_authorized"] is False


def test_q1_component_is_review_only_and_positive_evidence_blocks(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "a.smd").write_bytes(b"a"); (client / "b.tga").write_bytes(b"b")
    rows = [
        {"path": "a.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE", "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00001", "deletion_authorized": "False"},
        {"path": "b.tga", "state": "PROTECTED_MANIFEST_EVIDENCE", "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00001", "evidence": "CLIENT_MANIFEST_EXACT", "deletion_authorized": "False"},
    ]
    _write_retention(project, rows, [{"component_id": "URC-00001", "entry_nodes": ["a.smd"], "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0}])
    result = build_quarantine_plan(project, client)
    assert result["q1_component_count"] == 1
    comp = result["q1_components"][0]
    assert comp["tier"] == "Q1_BLOCKED_POSITIVE_EVIDENCE"
    assert comp["action"] == "REVIEW_ONLY"
    assert comp["deletion_authorized"] is False


def test_apply_and_restore_q0_transaction(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    src = client / "Effect" / "sky" / "s.bmp"
    src.parent.mkdir(parents=True); src.write_bytes(b"text-not-bmp")
    _write_retention(project, [_q0("Effect/sky/s.bmp")])
    plan = build_quarantine_plan(project, client)
    assert plan["q0_count"] == 1

    refused = apply_quarantine_plan(project, client, confirm="WRONG")
    assert refused["status"] == "REFUSED"
    applied = apply_quarantine_plan(project, client, confirm=APPLY_CONFIRM)
    assert applied["status"] == "QUARANTINED"
    assert not src.exists()
    qpath = Path(applied["items"][0]["quarantine_path"])
    assert qpath.is_file()
    assert applied["delete_authorized"] is False

    restored = restore_quarantine_transaction(project, client, confirm=RESTORE_CONFIRM)
    assert restored["status"] == "RESTORED"
    assert src.read_bytes() == b"text-not-bmp"
    assert not qpath.exists()
    assert restored["delete_authorized"] is False


def test_apply_refuses_stale_retention_report(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir(); (client / "bad.bmp").write_bytes(b"bad")
    _write_retention(project, [_q0("bad.bmp")])
    build_quarantine_plan(project, client)
    report = project / "pt_build" / "asset_retention" / "result.json"
    report.write_text(json.dumps({"changed": True}), encoding="utf-8")
    result = apply_quarantine_plan(project, client, confirm=APPLY_CONFIRM)
    assert result["status"] == "REFUSED"
    assert result["reason"] == "RETENTION_REPORT_CHANGED_REBUILD_PLAN"
    assert (client / "bad.bmp").is_file()


def test_q1_priority_a_for_small_isolated_documented_invalid_component(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    rows = [
        {
            "path": "Effect/AssaEffect/MonsterFury/m_fury.smd",
            "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False",
            "component_id": "URC-02537", "evidence": "CONTRACT_GRAPH_EDGE",
            "deletion_authorized": "False",
        },
        {
            **_q0("Effect/AssaEffect/MonsterFury/m_fury.tga"),
            "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True",
            "component_id": "URC-02537",
            "evidence": "CONTRACT_GRAPH_EDGE",
            "integrity_action": "INVALID_GRAPH_LINKED_ROOT_UNREACHABLE_QUARANTINE_REVIEW",
        },
    ]
    _write_retention(project, rows, [{
        "component_id": "URC-02537", "entry_count": 1,
        "entry_nodes": ["Effect/AssaEffect/MonsterFury/m_fury.smd"],
        "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0,
    }])
    result = build_quarantine_plan(project, client)
    comp = result["q1_components"][0]
    assert comp["review_band"] == "A"
    assert comp["review_score"] == 80
    assert comp["documented_invalid_member_count"] == 1
    assert comp["action"] == "REVIEW_ONLY"
    assert comp["deletion_authorized"] is False


def test_q1_valid_isolated_component_stays_low_priority_review(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    rows = [
        {
            "path": "Effect/a.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00010",
            "evidence": "CONTRACT_GRAPH_EDGE", "deletion_authorized": "False",
        },
        {
            "path": "Effect/a.tga", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00010",
            "evidence": "CONTRACT_GRAPH_EDGE", "cook_status": "up-to-date",
            "integrity_action": "GRAPH_LINKED_ROOT_UNREACHABLE_REVIEW", "deletion_authorized": "False",
        },
    ]
    _write_retention(project, rows, [{
        "component_id": "URC-00010", "entry_count": 1, "entry_nodes": ["Effect/a.smd"],
        "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0,
    }])
    result = build_quarantine_plan(project, client)
    comp = result["q1_components"][0]
    assert comp["review_band"] == "C"
    assert comp["review_score"] == 30
    assert comp["action"] == "REVIEW_ONLY"


def test_quarantine_review_queue_filters_and_never_authorizes_delete(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    rows = [
        {
            "path": "bad.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00001",
            "evidence": "CONTRACT_GRAPH_EDGE", "deletion_authorized": "False",
        },
        {
            **_q0("bad.tga"), "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "component_id": "URC-00001",
            "evidence": "CONTRACT_GRAPH_EDGE",
            "integrity_action": "INVALID_GRAPH_LINKED_ROOT_UNREACHABLE_QUARANTINE_REVIEW",
        },
        {
            "path": "ok.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00002",
            "evidence": "CONTRACT_GRAPH_EDGE", "deletion_authorized": "False",
        },
    ]
    components = [
        {"component_id": "URC-00001", "entry_count": 1, "entry_nodes": ["bad.smd"], "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0},
        {"component_id": "URC-00002", "entry_count": 1, "entry_nodes": ["ok.smd"], "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0},
    ]
    _write_retention(project, rows, components)
    build_quarantine_plan(project, client)
    result = quarantine_review_queue(project, band="A", limit=10)
    assert result["status"] == "PASS"
    assert result["total_rows"] == 1
    assert result["rows"][0]["component_id"] == "URC-00001"
    assert result["deletion_authorized"] is False
    assert result["policy"]["q1_is_review_only"] is True


def test_q1_manual_component_quarantine_requires_exact_confirm_hash_and_restore(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    smd = client / "Effect" / "AssaEffect" / "MonsterFury" / "m_fury.smd"
    tga = client / "Effect" / "AssaEffect" / "MonsterFury" / "m_fury.tga"
    smd.parent.mkdir(parents=True)
    smd.write_bytes(b"model-ref")
    tga.write_bytes(b"\x00" * 64)
    rows = [
        {
            "path": "Effect/AssaEffect/MonsterFury/m_fury.smd",
            "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False",
            "component_id": "URC-02537", "evidence": "CONTRACT_GRAPH_EDGE",
            "deletion_authorized": "False",
        },
        {
            **_q0("Effect/AssaEffect/MonsterFury/m_fury.tga"),
            "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE",
            "graph_linked": "True", "root_reachable": "False",
            "component_id": "URC-02537", "evidence": "CONTRACT_GRAPH_EDGE",
            "integrity_action": "INVALID_GRAPH_LINKED_ROOT_UNREACHABLE_QUARANTINE_REVIEW",
        },
    ]
    _write_retention(project, rows, [{
        "component_id": "URC-02537", "entry_count": 1,
        "entry_nodes": ["Effect/AssaEffect/MonsterFury/m_fury.smd"],
        "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0,
    }])
    plan = build_quarantine_plan(project, client)
    comp = plan["q1_components"][0]
    assert comp["manual_quarantine_eligible"] is True
    assert len(comp["member_manifest"]) == 2

    refused = apply_q1_component_quarantine(project, client, component_id="URC-02537", confirm="WRONG")
    assert refused["status"] == "REFUSED"
    applied = apply_q1_component_quarantine(project, client, component_id="URC-02537", confirm=Q1_COMPONENT_CONFIRM)
    assert applied["status"] == "QUARANTINED"
    assert applied["scope"] == "Q1_COMPONENT"
    assert applied["component_id"] == "URC-02537"
    assert applied["moved_count"] == 2
    assert not smd.exists() and not tga.exists()
    assert applied["delete_authorized"] is False

    restored = restore_quarantine_transaction(project, client, confirm=RESTORE_CONFIRM)
    assert restored["status"] == "RESTORED"
    assert smd.read_bytes() == b"model-ref"
    assert tga.read_bytes() == b"\x00" * 64
    assert restored["delete_authorized"] is False


def test_q1_manual_component_refuses_source_changed_after_plan(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    smd = client / "a.smd"; tga = client / "a.tga"
    smd.write_bytes(b"a"); tga.write_bytes(b"bad")
    rows = [
        {"path": "a.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE", "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00001", "evidence": "CONTRACT_GRAPH_EDGE", "deletion_authorized": "False"},
        {**_q0("a.tga"), "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE", "graph_linked": "True", "component_id": "URC-00001", "evidence": "CONTRACT_GRAPH_EDGE", "integrity_action": "INVALID_GRAPH_LINKED_ROOT_UNREACHABLE_QUARANTINE_REVIEW"},
    ]
    _write_retention(project, rows, [{"component_id": "URC-00001", "entry_count": 1, "entry_nodes": ["a.smd"], "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0}])
    plan = build_quarantine_plan(project, client)
    assert plan["q1_components"][0]["manual_quarantine_eligible"] is True
    tga.write_bytes(b"changed-after-plan")
    result = apply_q1_component_quarantine(project, client, component_id="URC-00001", confirm=Q1_COMPONENT_CONFIRM)
    assert result["status"] == "REFUSED"
    assert result["reason"].startswith("Q1_SOURCE_CHANGED_REBUILD_PLAN:")
    assert smd.is_file() and tga.is_file()


def test_q1_manual_component_refuses_non_a_component(tmp_path: Path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "a.smd").write_bytes(b"a")
    (client / "a.tga").write_bytes(b"valid")
    rows = [
        {"path": "a.smd", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE", "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00002", "evidence": "CONTRACT_GRAPH_EDGE", "deletion_authorized": "False"},
        {"path": "a.tga", "state": "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE", "graph_linked": "True", "root_reachable": "False", "component_id": "URC-00002", "evidence": "CONTRACT_GRAPH_EDGE", "cook_status": "up-to-date", "integrity_action": "GRAPH_LINKED_ROOT_UNREACHABLE_REVIEW", "deletion_authorized": "False"},
    ]
    _write_retention(project, rows, [{"component_id": "URC-00002", "entry_count": 1, "entry_nodes": ["a.smd"], "external_incoming_edge_count": 0, "external_outgoing_edge_count": 0}])
    plan = build_quarantine_plan(project, client)
    comp = plan["q1_components"][0]
    assert comp["review_band"] == "C"
    assert comp["manual_quarantine_eligible"] is False
    result = apply_q1_component_quarantine(project, client, component_id="URC-00002", confirm=Q1_COMPONENT_CONFIRM)
    assert result["status"] == "REFUSED"
    assert result["reason"] == "COMPONENT_NOT_MANUAL_QUARANTINE_ELIGIBLE"
