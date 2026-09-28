from __future__ import annotations

import json

from pt_asset_tool.asset_retention import audit_asset_retention


def test_retention_protects_transitive_and_monster_bundle_but_not_zero_link_ui(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    monster = client / "char" / "monster" / "TestMob"; monster.mkdir(parents=True)
    (monster / "test.inx").write_bytes(b"inx")
    (monster / "test.smd").write_bytes(b"smd")
    (monster / "skin.tga").write_bytes(b"tga")  # no direct graph edge: protected by entity bundle guard
    ui = client / "game" / "UI"; ui.mkdir(parents=True)
    (ui / "unused.png").write_bytes(b"png")
    (client / "cooked").mkdir(); (client / "cooked" / "generated.dds").write_bytes(b"DDS ")

    graph_dir = project / "pt_build" / "enrichment_vendor" / "dependency_graph"; graph_dir.mkdir(parents=True)
    graph = {
        "nodes": [],
        "edges": [{
            "src": "client:char/monster/TestMob/test.inx",
            "dst": "client:char/monster/TestMob/test.smd",
            "relation": "client_asset_reference", "evidence": "test.inx", "target_exists": "True",
        }],
    }
    graph_path = graph_dir / "graph.json"; graph_path.write_text(json.dumps(graph), encoding="utf-8")

    report = audit_asset_retention(
        project, client,
        strong_paths={"char/monster/testmob/test.inx": {"TEST_ROOT"}},
        review_paths={}, manifest_exact={}, source_literal_paths=set(),
        cooked_by_source={"char/monster/testmob/skin.tga": {
            "status": "error", "failure_class": "UNRECOGNIZED_LEGACY_IMAGE_ENCODING", "failure_stage": "decode",
            "error_message": "cannot identify image",
        }},
        graph_path=graph_path,
    )
    rows = {x["path"].casefold(): x for x in report["orphan_candidates"]}
    assert "game/ui/unused.png" in rows
    assert report["policy"]["delete_authorized"] is False

    # Read full TSV-derived JSON sample via state counts: only the UI file should be an orphan here.
    assert report["orphan_candidate_count"] == 1
    assert report["state_counts"]["PROTECTED_REACHABLE_ROOT"] == 1
    assert report["state_counts"]["PROTECTED_ROOT_REACHABLE"] == 1
    assert report["state_counts"]["PROTECTED_ENTITY_BUNDLE_ROOT_REACHABLE"] == 1
    assert report["state_counts"]["GENERATED_OUTPUT"] == 1

    tsv = (project / "pt_build" / "asset_retention" / "assets.tsv").read_text(encoding="utf-8")
    assert "skin.tga\tPROTECTED_ENTITY_BUNDLE_ROOT_REACHABLE" in tsv
    assert "UNRECOGNIZED_LEGACY_IMAGE_ENCODING" in tsv


def test_manifest_and_source_evidence_protect_zero_degree_files(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "a.png").write_bytes(b"a")
    (client / "b.png").write_bytes(b"b")
    graph = project / "graph.json"; graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    report = audit_asset_retention(
        project, client,
        strong_paths={}, review_paths={},
        manifest_exact={"a.png": ["setfile.lst"]},
        source_literal_paths={"b.png"}, graph_path=graph,
    )
    assert report["orphan_candidate_count"] == 0
    assert report["state_counts"]["PROTECTED_MANIFEST_EVIDENCE"] == 1
    assert report["state_counts"]["PROTECTED_SOURCE_EVIDENCE"] == 1


def test_entity_catalog_membership_protects_monster_bundle_without_graph_edge(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    monster = client / "char" / "monster" / "CatalogMob"; monster.mkdir(parents=True)
    (monster / "CatalogMob.inx").write_bytes(b"inx")
    (monster / "CatalogMob.smd").write_bytes(b"smd")
    (monster / "CatalogMob.tga").write_bytes(b"tga")
    catalog_dir = project / "data" / "reference" / "entity_catalog"; catalog_dir.mkdir(parents=True)
    (catalog_dir / "monster_npc_entities_v1.json").write_text(json.dumps({
        "format": "PT_ENTITY_CATALOG_SEED_V1",
        "entities": [{"folder_root": "char/monster/CatalogMob"}],
    }), encoding="utf-8")
    graph = project / "graph.json"; graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    report = audit_asset_retention(
        project, client, strong_paths={}, review_paths={}, manifest_exact={},
        source_literal_paths=set(), graph_path=graph,
    )
    assert report["orphan_candidate_count"] == 0
    assert report["state_counts"]["PROTECTED_ENTITY_CATALOG"] == 3
    assert report["policy"]["monster_npc_catalog_membership_protects_bundle"] is True
    tsv = (project / "pt_build" / "asset_retention" / "assets.tsv").read_text(encoding="utf-8")
    assert "ENTITY_CATALOG:char/monster/catalogmob" in tsv


def test_retention_query_is_read_only_and_filterable(tmp_path):
    from pt_asset_tool.asset_retention import query_asset_retention

    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "unused.png").write_bytes(b"x")
    (client / "protected.png").write_bytes(b"y")
    graph = project / "graph.json"; graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    audit_asset_retention(
        project, client, strong_paths={"protected.png": {"TEST"}}, review_paths={},
        manifest_exact={}, source_literal_paths=set(), graph_path=graph,
    )
    result = query_asset_retention(project, state="ORPHAN_CANDIDATE", query="unused")
    assert result["status"] == "PASS"
    assert result["filtered_rows"] == 1
    assert result["rows"][0]["path"] == "unused.png"
    assert result["deletion_authorized"] is False
    exact = query_asset_retention(project, path="protected.png")
    assert exact["filtered_rows"] == 1
    assert exact["rows"][0]["path"] == "protected.png"


def test_cooker_integrity_is_combined_with_reachability_without_overriding_it(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "linked.tga").write_bytes(b"bad")
    (client / "orphan.tga").write_bytes(b"bad")
    graph = project / "graph.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    cooked = {
        "linked.tga": {
            "status": "error", "failure_class": "UNRECOGNIZED_LEGACY_IMAGE_ENCODING",
            "documented_outlier": "True", "asset_integrity_state": "KNOWN_INVALID_OR_NON_IMAGE",
            "asset_classification": "NON_IMAGE_TEST", "cook_policy": "DO_NOT_FORCE_DDS",
        },
        "orphan.tga": {
            "status": "error", "failure_class": "HEADER_TOO_SHORT",
            "documented_outlier": "False", "asset_integrity_state": "UNRESOLVED_DECODE_FAILURE",
        },
    }
    report = audit_asset_retention(
        project, client,
        strong_paths={"linked.tga": {"TEST_ROOT"}}, review_paths={}, manifest_exact={},
        source_literal_paths=set(), cooked_by_source=cooked, graph_path=graph,
    )
    rows = {}
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rows[row["path"]] = row
    assert rows["linked.tga"]["state"] == "PROTECTED_REACHABLE_ROOT"
    assert rows["linked.tga"]["integrity_action"] == "INVALID_REFERENCED_NEEDS_RECOVERY_OR_RUNTIME_PROOF"
    assert rows["orphan.tga"]["state"] == "ORPHAN_CANDIDATE"
    assert rows["orphan.tga"]["integrity_action"] == "DECODE_FAILURE_UNREACHABLE_REVIEW"
    assert rows["orphan.tga"]["deletion_authorized"] == "False"
    assert report["policy"]["cooker_integrity_evidence_does_not_override_reachability"] is True


def test_graph_edge_without_strong_root_is_review_not_protection(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "dead_a.part").write_bytes(b"a")
    (client / "dead_b.tga").write_bytes(b"b")
    graph = project / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [],
        "edges": [{
            "src": "client:dead_a.part",
            "dst": "client:dead_b.tga",
            "relation": "client_asset_reference",
            "evidence": "dead_a.part",
        }],
    }), encoding="utf-8")
    report = audit_asset_retention(
        project, client, strong_paths={}, review_paths={}, manifest_exact={},
        source_literal_paths=set(), graph_path=graph,
    )
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        rows = {row["path"]: row for row in csv.DictReader(f, delimiter="\t")}
    assert rows["dead_a.part"]["state"] == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
    assert rows["dead_b.tga"]["state"] == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
    assert rows["dead_b.tga"]["graph_linked"] == "True"
    assert rows["dead_b.tga"]["root_reachable"] == "False"
    assert rows["dead_b.tga"]["incoming_edge_sources"] == "client:dead_a.part"
    assert report["policy"]["contract_graph_edge_alone_is_review_not_runtime_protection"] is True
    assert report["graph_linked_root_unreachable_review_count"] == 2


def test_root_reachability_records_distance_source_and_edge_details(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    for name in ("root.inx", "mid.smd", "leaf.tga"):
        (client / name).write_bytes(name.encode())
    graph = project / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [],
        "edges": [
            {"src": "client:root.inx", "dst": "client:mid.smd", "relation": "USES_MODEL", "evidence": "root"},
            {"src": "client:mid.smd", "dst": "client:leaf.tga", "relation": "USES_TEXTURE", "evidence": "material"},
        ],
    }), encoding="utf-8")
    audit_asset_retention(
        project, client, strong_paths={"root.inx": {"TEST_RUNTIME_ROOT"}}, review_paths={},
        manifest_exact={}, source_literal_paths=set(), graph_path=graph,
    )
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        rows = {row["path"]: row for row in csv.DictReader(f, delimiter="\t")}
    assert rows["root.inx"]["root_reachable"] == "True"
    assert rows["root.inx"]["root_distance"] == "0"
    assert rows["mid.smd"]["state"] == "PROTECTED_ROOT_REACHABLE"
    assert rows["mid.smd"]["root_distance"] == "1"
    assert rows["leaf.tga"]["root_distance"] == "2"
    assert rows["leaf.tga"]["root_sources"] == "root.inx"
    assert "client:mid.smd --USES_TEXTURE--> client:leaf.tga [material]" in rows["leaf.tga"]["incoming_edge_details"]


def test_manifest_and_source_literal_protect_but_do_not_become_runtime_roots(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    for name in ("manifest.part", "manifest_child.tga", "source.part", "source_child.tga"):
        (client / name).write_bytes(b"x")
    graph = project / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [],
        "edges": [
            {"src": "client:manifest.part", "dst": "client:manifest_child.tga", "relation": "REF"},
            {"src": "client:source.part", "dst": "client:source_child.tga", "relation": "REF"},
        ],
    }), encoding="utf-8")
    audit_asset_retention(
        project, client, strong_paths={}, review_paths={},
        manifest_exact={"manifest.part": ["setfile.lst"]}, source_literal_paths={"source.part"}, graph_path=graph,
    )
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        rows = {row["path"]: row for row in csv.DictReader(f, delimiter="\t")}
    assert rows["manifest.part"]["state"] == "PROTECTED_MANIFEST_EVIDENCE"
    assert rows["manifest.part"]["root_reachable"] == "False"
    assert rows["manifest_child.tga"]["state"] == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"
    assert rows["source.part"]["state"] == "PROTECTED_SOURCE_EVIDENCE"
    assert rows["source.part"]["root_reachable"] == "False"
    assert rows["source_child.tga"]["state"] == "REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE"


def test_monster_bundle_keeps_fail_closed_guard_when_only_graph_linked(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    monster = client / "char" / "monster" / "DeadButLinked"; monster.mkdir(parents=True)
    (monster / "a.smd").write_bytes(b"smd")
    (monster / "skin.tga").write_bytes(b"tga")
    graph = project / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [],
        "edges": [{
            "src": "client:char/monster/DeadButLinked/a.smd",
            "dst": "client:char/monster/DeadButLinked/skin.tga",
            "relation": "MODEL_USES_TEXTURE",
        }],
    }), encoding="utf-8")
    audit_asset_retention(
        project, client, strong_paths={}, review_paths={}, manifest_exact={},
        source_literal_paths=set(), graph_path=graph,
    )
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        rows = {row["path"]: row for row in csv.DictReader(f, delimiter="\t")}
    assert rows["char/monster/DeadButLinked/a.smd"]["state"] == "PROTECTED_ENTITY_BUNDLE_LINKED"
    assert rows["char/monster/DeadButLinked/skin.tga"]["state"] == "PROTECTED_ENTITY_BUNDLE_LINKED"
    assert rows["char/monster/DeadButLinked/skin.tga"]["root_reachable"] == "False"


def test_root_unreachable_graph_is_grouped_into_components(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    for name in ("a.ini", "b.smd", "c.tga", "solo.tga"):
        (client / name).write_bytes(b"x")
    graph = project / "graph.json"
    graph.write_text(json.dumps({
        "nodes": [],
        "edges": [
            {"src": "client:a.ini", "dst": "client:b.smd", "relation": "REF"},
            {"src": "client:b.smd", "dst": "client:c.tga", "relation": "REF"},
        ],
    }), encoding="utf-8")
    report = audit_asset_retention(
        project, client, strong_paths={}, review_paths={}, manifest_exact={},
        source_literal_paths=set(), graph_path=graph,
    )
    import csv
    with (project / "pt_build" / "asset_retention" / "assets.tsv").open(encoding="utf-8", newline="") as f:
        rows = {row["path"]: row for row in csv.DictReader(f, delimiter="\t")}
    cid = rows["a.ini"]["component_id"]
    assert cid.startswith("URC-")
    assert rows["b.smd"]["component_id"] == cid
    assert rows["c.tga"]["component_id"] == cid
    assert rows["a.ini"]["component_size"] == "3"
    assert rows["solo.tga"]["component_id"] == ""
    assert report["root_unreachable_component_count"] == 1
    components = json.loads((project / "pt_build" / "asset_retention" / "components.json").read_text(encoding="utf-8"))
    assert components["component_count"] == 1
    assert components["components"][0]["deletion_authorized"] is False


def test_retention_query_can_filter_component(tmp_path):
    from pt_asset_tool.asset_retention import query_asset_retention
    project = tmp_path / "project"; client = tmp_path / "client"
    project.mkdir(); client.mkdir()
    (client / "a.ini").write_bytes(b"x"); (client / "b.tga").write_bytes(b"x")
    graph = project / "graph.json"
    graph.write_text(json.dumps({"nodes": [], "edges": [{"src": "client:a.ini", "dst": "client:b.tga", "relation": "REF"}]}), encoding="utf-8")
    audit_asset_retention(project, client, strong_paths={}, review_paths={}, manifest_exact={}, source_literal_paths=set(), graph_path=graph)
    first = query_asset_retention(project, path="a.ini")
    cid = first["rows"][0]["component_id"]
    result = query_asset_retention(project, component=cid)
    assert result["filtered_rows"] == 2
    assert {x["path"] for x in result["rows"]} == {"a.ini", "b.tga"}
