from __future__ import annotations

import json
from pathlib import Path

import pt_asset_tool.donor_recovery_explorer as dre


def test_same_donor_label_pairs_client_and_server_roots(monkeypatch, tmp_path):
    c1 = tmp_path / "d1c"; s1 = tmp_path / "d1s"; c2 = tmp_path / "d2c"; s2 = tmp_path / "d2s"
    for p in (c1, s1, c2, s2): p.mkdir()
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={c1}", f"DONOR2={c2}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={s1}", f"DONOR2={s2}"])
    pairs = dre.donor_pairs(tmp_path)
    assert [x["label"] for x in pairs] == ["DONOR1", "DONOR2"]
    assert pairs[0]["client"]["root"] == str(c1.resolve())
    assert pairs[0]["server"]["root"] == str(s1.resolve())


def test_explorer_exposes_server_spawn_and_client_effect_under_one_logical_donor(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_s = tmp_path / "donor_server"
    (donor_c / "Effect/Test").mkdir(parents=True); (donor_c / "Effect/Test/a.part").write_text("x")
    (donor_s / "GameServer/Field").mkdir(parents=True); (donor_s / "GameServer/Field/lost3.ASE.spm").write_text("*ACTOR Foo 1")
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, donor="DONOR1", limit=50)
    assert len(result["donors"]) == 1
    row = result["donors"][0]
    assert row["label"] == "DONOR1"
    assert any(x["relative_path"].casefold().endswith("lost3.ase.spm") for x in row["domains"]["MAP_FIELD"]["nodes"])
    assert any(x["relative_path"].casefold().endswith("a.part") for x in row["domains"]["EFFECT"]["nodes"])


def test_index_merge_adds_new_spawn_without_replacing_unrelated_entries():
    old = {"schema": "summit.stage-spawn-index/v1", "documents": [{"id": "spawn.a", "logical_path": "GameServer/Field/a.ASE.spm", "json_path": "spawns/a.json"}]}
    entry = {"id": "spawn.b", "logical_path": "GameServer/Field/b.ASE.spm", "json_path": "spawns/b.json"}
    merged = dre._merge_index(old, entry, path_key="logical_path")
    assert [x["id"] for x in merged["documents"]] == ["spawn.a", "spawn.b"]
    assert old["documents"] == [{"id": "spawn.a", "logical_path": "GameServer/Field/a.ASE.spm", "json_path": "spawns/a.json"}]


def test_server_logical_path_accepts_game_server_root_or_gameserver_subtree():
    assert dre._server_logical_path(Path("GameServer/Field/x.spm")).as_posix() == "GameServer/Field/x.spm"
    assert dre._server_logical_path(Path("Field/x.spm")).as_posix() == "GameServer/Field/x.spm"
    assert dre._server_logical_path(Path("prefix/GameServer/Monster/x.inf")).as_posix() == "GameServer/Monster/x.inf"


def test_donor_recovery_ui_and_api_are_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert 'id="donorRecoveryPanel"' in html and 'id="donorRecoveryTree"' in html
    assert 'Stage SPM → canonical' in js
    assert '/api/donor-recovery/explorer' in py
    assert '/api/donor-recovery/stage' in py
    assert '/api/canonical/deploy-runtime' in py
    assert '/api/donor-recovery/apply-physical' in py and '/api/donor-recovery/restore-physical' in py
    assert 'canonicalV211DeployRuntime' in html and 'deploy-runtime' in js


def test_explorer_builds_cross_donor_entity_tree(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"
    donor_c = tmp_path / "donor_client"; donor_s = tmp_path / "donor_server"
    for p in (target_c, target_s, donor_c, donor_s): p.mkdir()
    (target_s / "GameServer/Field").mkdir(parents=True)
    (target_s / "GameServer/Field/lost3.ASE.spp").write_text("target")
    (donor_s / "GameServer/Field").mkdir(parents=True)
    (donor_s / "GameServer/Field/lost3.ASE.spm").write_text("*ACTOR Foo 1")
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", limit=50)
    entities = result["entity_tree"]["MAP_FIELD"]["entities"]
    lost = next(x for x in entities if x["entity_key"] == "lost3")
    assert lost["has_target"] is True
    assert lost["donor_labels"] == ["DONOR1", "SUMMIT"]
    assert {x["field_kind"] for x in lost["variants"]} == {"SPM", "SPP"}


def test_index_merge_rejects_same_id_at_different_runtime_path():
    old = {"schema": "summit.stage-spawn-index/v1", "documents": [{"id": "spawn.a", "logical_path": "GameServer/Field/a.ASE.spm", "json_path": "spawns/a.json"}]}
    entry = {"id": "spawn.a", "logical_path": "GameServer/Field/b.ASE.spm", "json_path": "spawns/b.json"}
    try:
        dre._merge_index(old, entry, path_key="logical_path")
    except ValueError as exc:
        assert "CANONICAL_INDEX_ID_RELOCATED" in str(exc)
    else:
        raise AssertionError("same canonical id at another runtime path must fail closed")


def test_dependency_filename_candidates_keep_paired_donor_identity(monkeypatch, tmp_path):
    d1s = tmp_path / "d1s"; d2s = tmp_path / "d2s"
    d1c = tmp_path / "d1c"; d2c = tmp_path / "d2c"
    for p in (d1s, d2s, d1c, d2c): p.mkdir()
    (d1s / "GameServer/Monster").mkdir(parents=True)
    (d2s / "GameServer/Monster").mkdir(parents=True)
    (d1s / "GameServer/Monster/Chefe_64_Rosa Sangrenta.inf").write_text("x")
    (d2s / "GameServer/Monster/Rosa_Sangrenta_Copy.inf").write_text("x")
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={d1c}", f"DONOR2={d2c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={d1s}", f"DONOR2={d2s}"])
    rows = dre._monster_dependency_candidates(tmp_path, [{"role":"actor","name":"Rosa Sangrenta","resolution":"legacy_skip_if_missing"}], preferred_donor="DONOR1")
    assert rows[0]["candidates"][0]["donor_label"] == "DONOR1"
    assert rows[0]["candidates"][0]["action"] == "MONSTER"


def _write_closed_bundle(project: Path, donor: str, side: str, root_path: str):
    out = project / "pt_build/general_asset_census"
    out.mkdir(parents=True, exist_ok=True)
    (out / "recovery_bundles.json").write_text(json.dumps({
        "format":"PT_ASSET_GENERAL_RECOVERY_BUNDLES_V1","rows":[{
            "status":"CLOSED","side":side,"root_path":root_path,"donor_label":donor,"selected_source":donor,"members":[]
        }]
    }), encoding="utf-8")


def test_physical_apply_writes_restorable_transaction_and_restore_is_hash_guarded(monkeypatch, tmp_path):
    project=tmp_path/"project"; client=tmp_path/"client"; server=tmp_path/"server"
    for p in (project,client,server): p.mkdir()
    root_path="Effect/Test/a.tga"; _write_closed_bundle(project,"DONOR1","CLIENT",root_path)
    target=client/root_path; target.parent.mkdir(parents=True); target.write_bytes(b"recovered")
    sha=dre.sha256_file(target)
    fake={
        "status":"PASS","state":"APPLIED_VERIFIED","client_root":str(client.resolve()),"server_root":str(server.resolve()),
        "scope_roots":[f"CLIENT:{root_path}"],"transactions":[{
            "side":"CLIENT","relative_path":root_path,"target_path":str(target),"sha256":sha,"size":len(b"recovered"),
            "donor_label":"DONOR1","source_path":str(tmp_path/"donor/a.tga"),"written":True,
        }]
    }
    monkeypatch.setattr(dre,"recover_closed_general_asset_bundles",lambda *a,**k: fake)
    applied=dre.apply_physical_closed_bundle(project,client,server,source_root=None,reference_source_root=None,donor_label="DONOR1",expected_side="CLIENT",expected_root=root_path,confirm=dre.PHYSICAL_APPLY_CONFIRM)
    assert applied["status"]=="APPLIED_VERIFIED"
    tx=Path(applied["transaction"]); assert tx.is_file()
    restored=dre.restore_physical_recovery(project,client,server,transaction=tx,confirm=dre.PHYSICAL_RESTORE_CONFIRM)
    assert restored["status"]=="RESTORED" and not target.exists()
    assert json.loads(tx.read_text())["state"]=="RESTORED"


def test_physical_restore_refuses_drift_before_deleting_anything(monkeypatch, tmp_path):
    project=tmp_path/"project"; client=tmp_path/"client"; server=tmp_path/"server"
    for p in (project,client,server): p.mkdir()
    root_path="Effect/Test/a.tga"; _write_closed_bundle(project,"DONOR1","CLIENT",root_path)
    target=client/root_path; target.parent.mkdir(parents=True); target.write_bytes(b"recovered")
    sha=dre.sha256_file(target)
    fake={"status":"PASS","state":"APPLIED_VERIFIED","client_root":str(client.resolve()),"server_root":str(server.resolve()),"scope_roots":[f"CLIENT:{root_path}"],"transactions":[{"side":"CLIENT","relative_path":root_path,"target_path":str(target),"sha256":sha,"size":9,"donor_label":"DONOR1","source_path":"x","written":True}]}
    monkeypatch.setattr(dre,"recover_closed_general_asset_bundles",lambda *a,**k: fake)
    applied=dre.apply_physical_closed_bundle(project,client,server,source_root=None,reference_source_root=None,donor_label="DONOR1",expected_side="CLIENT",expected_root=root_path,confirm=dre.PHYSICAL_APPLY_CONFIRM)
    target.write_bytes(b"changed")
    try:
        dre.restore_physical_recovery(project,client,server,transaction=applied["transaction"],confirm=dre.PHYSICAL_RESTORE_CONFIRM)
    except ValueError as exc:
        assert "TARGET_DRIFT" in str(exc)
    else:
        raise AssertionError("drift must block restore")
    assert target.read_bytes()==b"changed"


def test_explorer_accepts_configured_server_root_that_is_already_game_server(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "game-server"; (donor_s / "Field").mkdir(parents=True)
    (donor_s / "Field/lost3.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    entities = result["entity_tree"]["MAP_FIELD"]["entities"]
    lost = next(x for x in entities if x["entity_key"] == "lost3")
    assert any(x["donor"] == "DONOR1" and x["field_kind"] == "SPM" for x in lost["variants"])
    diag = result["donors"][1]["scan_diagnostics"]["MAP_FIELD"]["SERVER"]
    assert diag["state"] == "READY"
    assert any(Path(x).name.casefold() == "field" for x in diag["resolved_scan_roots"])


def test_map_field_identity_merges_client_map_assets_with_server_spawn(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"
    donor_c = tmp_path / "donor_client"; donor_s = tmp_path / "donor_server"
    for pth in (target_c, target_s, donor_c, donor_s): pth.mkdir()
    (target_c / "Field/Lost").mkdir(parents=True); (target_c / "Field/Lost/lost3.smd").write_text("x")
    (target_c / "Field/map").mkdir(parents=True); (target_c / "Field/map/lost3.tga").write_text("x")
    (target_c / "Field/Title").mkdir(parents=True); (target_c / "Field/Title/lost3t.tga").write_text("x")
    (donor_s / "GameServer/Field").mkdir(parents=True); (donor_s / "GameServer/Field/lost3.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    entities = result["entity_tree"]["MAP_FIELD"]["entities"]
    assert [x["entity_key"] for x in entities] == ["lost3"]
    lost = entities[0]
    assert lost["variant_count"] == 4
    assert lost["donor_labels"] == ["DONOR1", "SUMMIT"]


def test_map_field_server_signature_discovery_finds_nested_field_tree(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "donor_server"; donor_s.mkdir()
    nested = donor_s / "runtime/data/maps/Field"
    nested.mkdir(parents=True)
    (nested / "lost3.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    lost = next(x for x in result["entity_tree"]["MAP_FIELD"]["entities"] if x["entity_key"] == "lost3")
    row = next(x for x in lost["variants"] if x["donor"] == "DONOR1" and x["side"] == "SERVER")
    assert row["field_kind"] == "SPM"
    assert row["relative_path"].endswith("runtime/data/maps/Field/lost3.ASE.spm")
    assert dre._server_logical_path(Path(row["relative_path"])).as_posix() == "GameServer/Field/lost3.ASE.spm"
    diag = result["donors"][1]["scan_diagnostics"]["MAP_FIELD"]["SERVER"]
    assert diag["state"] == "READY"
    assert any(Path(x).name.casefold() == "field" for x in diag["signature_scan_roots"])


def test_map_field_server_scan_rejects_client_geometry_and_textures(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    # A misleading server/Field mirror contains client assets; only SPM/SPP/SPC
    # are legitimate SERVER MAP_FIELD variants.
    (target_s / "Field/Lost").mkdir(parents=True)
    (target_s / "Field/Lost/lost3.smd").write_text("x")
    (target_s / "Field/map").mkdir(parents=True)
    (target_s / "Field/map/lost3.tga").write_text("x")
    (target_s / "deep/GameServer/Field").mkdir(parents=True)
    (target_s / "deep/GameServer/Field/lost3.ASE.spp").write_text("server")
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    lost = next(x for x in result["entity_tree"]["MAP_FIELD"]["entities"] if x["entity_key"] == "lost3")
    server_rows = [x for x in lost["variants"] if x["donor"] == "SUMMIT" and x["side"] == "SERVER"]
    assert [x["field_kind"] for x in server_rows] == ["SPP"]
    assert server_rows[0]["relative_path"].endswith("deep/GameServer/Field/lost3.ASE.spp")


def test_map_field_deep_fallback_finds_signature_beyond_inference_depth(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "game-server"; donor_s.mkdir()
    deep = donor_s
    # Deeper than _signature_domain_roots(max_depth=8), forcing the exhaustive
    # configured-root fallback instead of inferred Field-root discovery.
    for i in range(11):
        deep = deep / f"wrapper{i}"
    deep = deep / "Field"
    deep.mkdir(parents=True)
    (deep / "lost3.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    lost = next(x for x in result["entity_tree"]["MAP_FIELD"]["entities"] if x["entity_key"] == "lost3")
    row = next(x for x in lost["variants"] if x["donor"] == "DONOR1" and x["side"] == "SERVER")
    assert row["field_kind"] == "SPM"
    diag = result["donors"][1]["scan_diagnostics"]["MAP_FIELD"]["SERVER"]
    assert diag["state"] == "READY_FALLBACK_RECURSIVE"
    assert diag["fallback_recursive_scan"]["query_matches"] == 1
    assert diag["fallback_recursive_scan"]["signature_files_seen"] == 1


def test_map_field_deep_fallback_distinguishes_no_signature_files(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "game-server"; donor_s.mkdir()
    (donor_s / "misc").mkdir()
    (donor_s / "misc/lost3.txt").write_text("not field metadata")
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    diag = result["donors"][1]["scan_diagnostics"]["MAP_FIELD"]["SERVER"]
    assert diag["state"] == "NO_SIGNATURE_FILES_ANYWHERE"
    assert diag["fallback_recursive_scan"]["signature_files_seen"] == 0
    assert diag["fallback_recursive_scan"]["directories_scanned"] >= 2


def test_map_field_deep_fallback_reports_signatures_but_no_query_match(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "game-server"; donor_s.mkdir()
    deep = donor_s
    for i in range(10):
        deep = deep / f"wrap{i}"
    deep.mkdir(parents=True)
    (deep / "other.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR1={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MAP_FIELD", query="lost3", limit=50)
    diag = result["donors"][1]["scan_diagnostics"]["MAP_FIELD"]["SERVER"]
    assert diag["state"] == "SIGNATURE_FILES_PRESENT_NO_QUERY_MATCH"
    assert diag["fallback_recursive_scan"]["signature_files_seen"] == 1
    assert diag["fallback_recursive_scan"]["query_matches"] == 0


def _write_canonical_maps(source_root: Path):
    path = source_root / "Content/canonical/maps/server.maps.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema":"summit.maps/v1","profile":"server","map_count":4,
        "maps":[
            {"id":"map.ruin_4","legacy_field_code":4,"stage":"Ruin//ruin-4.ase","map_image_id":"ruin-4"},
            {"id":"map.lost","legacy_field_code":37,"stage":"lost//lostisland.ASE","map_image_id":"lost"},
            {"id":"map.losttemple","legacy_field_code":38,"stage":"Losttemple//lost_temple.ASE","map_image_id":"Losttemple"},
            {"id":"map.lost3","legacy_field_code":51,"stage":"lost//lost3.ASE","map_image_id":"lost3"},
        ]
    }), encoding="utf-8")


def test_map_field_recovery_is_certified_only_by_exact_canonical_stage_identity(monkeypatch, tmp_path):
    project=tmp_path/"project"; project.mkdir()
    source=tmp_path/"source"; _write_canonical_maps(source)
    target_c=tmp_path/"client"; target_s=tmp_path/"server"; donor_c=tmp_path/"dc"; donor_s=tmp_path/"ds"
    for p in (target_c,target_s,donor_c,donor_s): p.mkdir()
    (target_c/"Field/Lost").mkdir(parents=True); (target_c/"Field/Lost/lost3.smd").write_text("x")
    (donor_s/"GameServer/Field").mkdir(parents=True)
    (donor_s/"GameServer/Field/lost3.ASE.spm").write_text('*ACTOR "Foo" 100\n')
    (donor_s/"GameServer/Field/lostisland.ASE.spm").write_text('*ACTOR "Bar" 100\n')
    monkeypatch.setattr(dre,"configured_contract_donor_clients",lambda _p:[f"DONOR1={donor_c}"])
    monkeypatch.setattr(dre,"configured_contract_donor_servers",lambda _p:[f"DONOR1={donor_s}"])
    result=dre.build_donor_explorer(project,target_c,target_s,source_root=source,domain="MAP_FIELD",query="lost",limit=50)
    rows=[x for x in result["donors"][1]["domains"]["MAP_FIELD"]["nodes"] if x["field_kind"]=="SPM"]
    by_key={x["entity_key"]:x for x in rows}
    assert by_key["lost3"]["spawn_recovery_certified"] is True
    assert by_key["lost3"]["canonical_field_identity"]["legacy_field_code"]==51
    assert by_key["lostisland"]["spawn_recovery_certified"] is True
    assert by_key["lostisland"]["canonical_field_identity"]["legacy_field_code"]==37
    # Similar names remain different certified identities, never aliases.
    assert by_key["lost3"]["canonical_field_identity"]["map_id"] != by_key["lostisland"]["canonical_field_identity"]["map_id"]


def test_map_field_query_identity_exposes_field_code_and_exact_stage(tmp_path):
    source=tmp_path/"source"; _write_canonical_maps(source)
    c=tmp_path/"client"; s=tmp_path/"server"; p=tmp_path/"project"
    for x in (c,s,p): x.mkdir()
    result=dre.build_donor_explorer(p,c,s,source_root=source,domain="MAP_FIELD",query="lost3",limit=10)
    ident=result["map_field_query_identity"]
    assert ident["legacy_field_code"]==51
    assert ident["map_id"]=="map.lost3"
    assert ident["canonical_stage"]=="lost//lost3.ASE"
    assert result["policy"]["fuzzy_map_name_similarity_never_certifies_spawn_recovery"] is True


def test_map_field_unknown_spawn_has_no_certified_action(monkeypatch,tmp_path):
    project=tmp_path/"project"; project.mkdir(); source=tmp_path/"source"; _write_canonical_maps(source)
    c=tmp_path/"client"; s=tmp_path/"server"; dc=tmp_path/"dc"; ds=tmp_path/"ds"
    for x in (c,s,dc,ds): x.mkdir()
    (ds/"GameServer/Field").mkdir(parents=True); (ds/"GameServer/Field/mystery.ASE.spm").write_text("x")
    monkeypatch.setattr(dre,"configured_contract_donor_clients",lambda _p:[f"DONOR1={dc}"])
    monkeypatch.setattr(dre,"configured_contract_donor_servers",lambda _p:[f"DONOR1={ds}"])
    result=dre.build_donor_explorer(project,c,s,source_root=source,domain="MAP_FIELD",query="mystery",limit=10)
    row=result["donors"][1]["domains"]["MAP_FIELD"]["nodes"][0]
    assert row["spawn_recovery_certified"] is False
    assert row["canonical_field_identity"]["match_basis"]=="NO_EXACT_CANONICAL_STAGE_IDENTITY"


def test_stage_spawn_rejects_uncertified_field_identity_before_conversion(monkeypatch,tmp_path):
    from types import SimpleNamespace
    project=tmp_path/"project"; project.mkdir(); source=tmp_path/"source"; _write_canonical_maps(source)
    canonical=source/"Content/canonical"; donor=tmp_path/"donor"; donor.mkdir()
    (donor/"GameServer/Field").mkdir(parents=True); (donor/"GameServer/Field/mystery.ASE.spm").write_text("x")
    monkeypatch.setattr(dre,"configured_contract_donor_clients",lambda _p:[])
    monkeypatch.setattr(dre,"configured_contract_donor_servers",lambda _p:[f"DONOR1={donor}"])
    provider=SimpleNamespace(source_root=source,canonical_root=canonical)
    try:
        dre.stage_spawn_from_donor(project,provider,donor_label="DONOR1",relative_path="GameServer/Field/mystery.ASE.spm")
    except ValueError as exc:
        assert "DONOR_STAGE_SPAWN_IDENTITY_NOT_CERTIFIED" in str(exc)
    else:
        raise AssertionError("uncertified donor SPM identity must fail before conversion")


def test_monster_explorer_deep_scans_cp949_definition_name_when_filename_differs(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    target_c = tmp_path / "client"; target_s = tmp_path / "server"; target_c.mkdir(); target_s.mkdir()
    donor_c = tmp_path / "donor_client"; donor_c.mkdir()
    donor_s = tmp_path / "donor_server"; donor_s.mkdir()
    deep = donor_s / "wrapper" / "legacy" / "defs"
    deep.mkdir(parents=True)
    name = "연구소 엔지니어"
    (deep / "Engineer42.inf").write_bytes(f'*J_NAME "{name}"\r\n*LEVEL 100\r\n'.encode("cp949"))
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR2={donor_c}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR2={donor_s}"])
    result = dre.build_donor_explorer(project, target_c, target_s, domain="MONSTER", query=name, donor="DONOR2", limit=50)
    entities = result["entity_tree"]["MONSTER"]["entities"]
    assert len(entities) == 1
    row = entities[0]["variants"][0]
    assert row["relative_path"].endswith("Engineer42.inf")
    assert row["query_match"]["match_basis"] == "LEGACY_CP949_BYTES_EXACT"
    assert name in row["definition_name_evidence"]
    diag = result["donors"][0]["scan_diagnostics"]["MONSTER"]["SERVER"]
    assert diag["state"] in {"READY", "READY_FALLBACK_RECURSIVE"}
    if diag["state"] == "READY_FALLBACK_RECURSIVE":
        assert diag["fallback_recursive_scan"]["signature_files_seen"] == 1


def test_monster_dependency_candidates_prefer_exact_legacy_name_bytes_over_filename(monkeypatch, tmp_path):
    project = tmp_path / "project"; project.mkdir()
    dc = tmp_path / "dc"; ds = tmp_path / "ds"; dc.mkdir(); ds.mkdir()
    deep = ds / "odd" / "layout" / "defs"; deep.mkdir(parents=True)
    name = "드락소스"
    payload = f'*J_NAME "{name}"\r\n*LEVEL 120\r\n'.encode("cp949")
    (deep / "Boss42.inf").write_bytes(payload)
    monkeypatch.setattr(dre, "configured_contract_donor_clients", lambda _p: [f"DONOR2={dc}"])
    monkeypatch.setattr(dre, "configured_contract_donor_servers", lambda _p: [f"DONOR2={ds}"])
    rows = dre._monster_dependency_candidates(
        project,
        [{"role": "boss_master", "name": name, "legacy_name_bytes_hex": name.encode("cp949").hex(), "resolution": "legacy_skip_if_missing"}],
        preferred_donor="DONOR2",
    )
    assert rows[0]["candidates"]
    cand = rows[0]["candidates"][0]
    assert cand["relative_path"].endswith("Boss42.inf")
    assert cand["match_basis"] == "LEGACY_NAME_BYTES_EXACT"
    assert cand["donor_label"] == "DONOR2"


def test_general_census_query_accepts_component_filter_even_before_report(tmp_path):
    from pt_asset_tool.general_asset_census import query_general_asset_census
    out = query_general_asset_census(tmp_path, component="cmp-123")
    assert out["status"] == "NOT_RUN"


def test_spawn_dependency_batch_autostages_only_unique_exact_same_donor_and_preserves_ambiguity(monkeypatch, tmp_path):
    from types import SimpleNamespace
    source = tmp_path / "source"
    canonical = source / "Content/canonical"
    text_root = canonical / "text"
    text_root.mkdir(parents=True)
    (text_root / "index.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
    provider = SimpleNamespace(source_root=source, canonical_root=canonical, content_root=source / "Content")
    project = tmp_path / "project"; project.mkdir()

    blocked = {
        "format": dre.FORMAT,
        "status": "BLOCKED_DEPENDENCIES",
        "donor_label": "DONOR2",
        "donor_relative_path": "GameServer/Field/Slab.ASE.spm",
        "donor_sha256": "abc",
        "logical_path": "GameServer/Field/Slab.ASE.spm",
        "converted_preview": {"id": "spawn.slab"},
        "dependency_gate": {"status": "BLOCKED", "unresolved": [
            {"role": "actor", "name": "Unique", "candidates": [
                {"donor_label": "DONOR2", "relative_path": "GameServer/Monster/A.inf", "match_basis": "LEGACY_NAME_BYTES_EXACT"}
            ]},
            {"role": "actor", "name": "Ambiguous", "candidates": [
                {"donor_label": "DONOR2", "relative_path": "GameServer/Monster/B.inf", "match_basis": "LEGACY_NAME_BYTES_EXACT"},
                {"donor_label": "DONOR2", "relative_path": "GameServer/Monster/B2.inf", "match_basis": "LEGACY_NAME_BYTES_EXACT"},
            ]},
            # B.inf must not be auto-staged here merely because another role is unique.
            {"role": "boss_slave", "name": "SharesAmbiguousFile", "candidates": [
                {"donor_label": "DONOR2", "relative_path": "GameServer/Monster/B.inf", "match_basis": "LEGACY_NAME_BYTES_EXACT"}
            ]},
            # Cross-donor evidence is review-only for a DONOR2 SPM.
            {"role": "actor", "name": "OtherDonor", "candidates": [
                {"donor_label": "DONOR3", "relative_path": "GameServer/Monster/C.inf", "match_basis": "LEGACY_NAME_BYTES_EXACT"}
            ]},
        ]},
    }
    monkeypatch.setattr(dre, "stage_spawn_from_donor", lambda *a, **k: blocked)

    def prepare(_project, _provider, *, donor_label, relative_path, kind):
        assert donor_label == "DONOR2" and relative_path.endswith("A.inf") and kind == "MONSTER"
        entry = {"id": "monster.unique", "kind": "monster_definition", "legacy_path": "GameServer/Monster/A.inf", "json_path": "resources/server/GameServer/Monster/A.inf.json"}
        return {
            "kind": "MONSTER", "entry": entry, "document": {"schema": "summit.canonical-text-resource/v1", "id": "monster.unique"},
            "target_rel": Path("canonical/text/resources/server/GameServer/Monster/A.inf.json"),
            "donor_root": tmp_path, "source": tmp_path / "A.inf", "relative_path": Path("GameServer/Monster/A.inf"),
            "logical_path": Path("GameServer/Monster/A.inf"), "converter_logs": [],
        }
    (tmp_path / "A.inf").write_bytes('*E_NAME "Unique Monster"\r\n*J_NAME "연구소 엔지니어"\r\n'.encode("cp949"))
    monkeypatch.setattr(dre, "_prepare_definition_import", prepare)
    monkeypatch.setattr(
        dre, "_definition_ptbr_localization_delta",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("batch must not edit materialized localization directly")),
    )
    captured = {}
    def stage(_project, _provider, changes, **kwargs):
        captured["changes"] = changes; captured["kwargs"] = kwargs
        return {"format": "X", "status": "STAGED", "manifest": {"manifest": "/tmp/manifest.json"}}
    monkeypatch.setattr(dre, "stage_canonical_document_set", stage)

    result = dre.stage_unique_spawn_dependencies_from_donor(
        project, provider, donor_label="DONOR2", relative_path="GameServer/Field/Slab.ASE.spm",
        run_validation=False, run_build=False,
    )
    assert result["status"] == "STAGED"
    assert [x["relative_path"] for x in result["dependency_batch"]["auto_staged"]] == ["GameServer/Monster/A.inf"]
    assert {x["name"] for x in result["dependency_batch"]["ambiguous"]} == {"Ambiguous"}
    assert {x["name"] for x in result["dependency_batch"]["withheld_due_to_ambiguity"]} == {"SharesAmbiguousFile"}
    assert {x["name"] for x in result["dependency_batch"]["missing"]} == {"OtherDonor"}
    assert len(captured["changes"]) == 2  # one monster document + canonical/text/index.json
    assert all(x["relative_path"] != "canonical/text/localization/pt-BR.json" for x in captured["changes"])
    assert captured["kwargs"]["kind"] == "MONSTER_DEPENDENCY_SET"
    assert captured["kwargs"]["localization_fallback_names"] == {"monster.unique": "Unique Monster"}




def test_existing_monster_semantic_alias_reuses_reverse_engineered_ptbr_overlay():
    from types import SimpleNamespace

    expected_id = "monster.slab_114_engenheiro_do_laborat_u00f3rio"
    model = r"char\monster\LEngineer\LEngineer.ini"
    canonical_doc = SimpleNamespace(
        data={"semantic": {"fields": {"model_file": model, "name": "Engenheiro do Laboratório"}}},
        relative_path="canonical/text/resources/Servidor/GameServer/Monster/Slab_114_Engenheiro.inf.json",
        sha256="abc123",
    )

    class Provider:
        def find_definition(self, canonical_id):
            assert canonical_id == expected_id
            return canonical_doc

    donor_doc = {
        "id": "monster.114_lengineer",
        "kind": "monster_definition",
        "semantic": {"fields": {"model_file": model, "name": "연구소 엔지니어"}},
    }
    match = dre._existing_monster_semantic_alias(Provider(), donor_doc)
    assert match is not None
    assert match["canonical_id"] == expected_id
    assert match["display_name"] == "Engenheiro do Laboratório"
    assert match["match_basis"] == "LEGACY_PT_BR_ALIAS_MODEL_EXACT_UNIQUE"


def test_spawn_semantic_reconciliation_maps_unique_exact_donor_name_to_existing_canonical(monkeypatch, tmp_path):
    from types import SimpleNamespace

    model = r"char\monster\LEngineer\LEngineer.ini"
    canonical_id = "monster.slab_114_engenheiro_do_laborat_u00f3rio"
    provider = SimpleNamespace(
        find_definition=lambda cid: SimpleNamespace(
            data={"semantic": {"fields": {"model_file": model, "name": "Engenheiro do Laboratório"}}},
            relative_path="canonical/text/resources/Servidor/GameServer/Monster/Slab_114_Engenheiro.inf.json",
            sha256="abc123",
        ) if cid == canonical_id else (_ for _ in ()).throw(KeyError(cid))
    )
    name = "연구소 엔지니어"
    doc = {
        "actors": [{
            "monster_id": None, "legacy_name": name,
            "legacy_name_bytes_hex": name.encode("cp949").hex(),
            "resolution": "legacy_skip_if_missing", "weight": 15,
        }],
        "bosses": [],
    }
    monkeypatch.setattr(dre, "_monster_dependency_candidates", lambda *a, **k: [{
        "role": "actor", "name": name, "legacy_name_bytes_hex": name.encode("cp949").hex(),
        "_slot_index": 0, "candidates": [{
            "donor_label": "DONOR2",
            "relative_path": "GameServer/Monster/114_LEngineer.inf",
            "match_basis": "LEGACY_NAME_BYTES_EXACT",
        }],
    }])
    monkeypatch.setattr(dre, "_prepare_definition_import", lambda *a, **k: {
        "document": {
            "id": "monster.114_lengineer", "kind": "monster_definition",
            "semantic": {"fields": {"model_file": model, "name": name}},
        }
    })

    rows = dre._apply_spawn_semantic_reconciliation(
        tmp_path, provider, doc, preferred_donor="DONOR2",
    )
    assert len(rows) == 1
    assert rows[0]["canonical_id"] == canonical_id
    assert doc["actors"][0]["monster_id"] == canonical_id
    assert doc["actors"][0]["resolution"] == "asset_tool_semantic_alias_model_exact"
    assert dre._spawn_unresolved_slots(doc) == []

def test_spawn_dependency_batch_ui_and_route_are_exposed():
    root = Path(__file__).resolve().parents[1]
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    assert "Stage unique exact monster dependencies" in html
    assert "STAGE_SPAWN_DEPENDENCIES" in js
    assert "stage_unique_spawn_dependencies_from_donor" in py


def test_definition_ptbr_bridge_adds_missing_runtime_name_without_overwriting_translation(tmp_path):
    from types import SimpleNamespace
    canonical = tmp_path / "Content/canonical"
    loc = canonical / "text/localization/pt-BR.json"
    loc.parent.mkdir(parents=True)
    loc.write_text(json.dumps({
        "schema": "summit.localization-catalog/v1", "schema_version": 1,
        "locale": "pt-BR", "fallback_locale": "en", "entries": [
            {"key": "monster.existing.name", "text": "Tradução aprovada", "quality": "translated", "source": "monster.existing"}
        ],
    }, ensure_ascii=False), encoding="utf-8")
    provider = SimpleNamespace(canonical_root=canonical)
    new_doc = {"id": "monster.114_lengineer", "semantic": {"fields": {"name": "연구소 엔지니어"}}}
    existing_doc = {"id": "monster.existing", "semantic": {"fields": {"name": "Legacy Existing"}}}
    catalog, added = dre._definition_ptbr_localization_delta(
        provider, [new_doc, existing_doc],
        fallback_names={"monster.114_lengineer": "Lab Engineer"},
    )
    assert [x["key"] for x in added] == ["monster.114_lengineer.name"]
    row = next(x for x in catalog["entries"] if x["key"] == "monster.114_lengineer.name")
    assert row == {
        "key": "monster.114_lengineer.name", "text": "Lab Engineer",
        "quality": "legacy_fallback", "source": "monster.114_lengineer",
    }
    preserved = next(x for x in catalog["entries"] if x["key"] == "monster.existing.name")
    assert preserved["text"] == "Tradução aprovada"


def test_stage_definition_includes_ptbr_override_in_same_atomic_transaction(monkeypatch, tmp_path):
    from types import SimpleNamespace
    source = tmp_path / "source"; content = source / "Content"; canonical = content / "canonical"
    (canonical / "text/localization").mkdir(parents=True)
    (canonical / "text/index.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
    (canonical / "text/localization/pt-BR.json").write_text(json.dumps({
        "schema": "summit.localization-catalog/v1", "schema_version": 1,
        "locale": "pt-BR", "fallback_locale": "en", "entries": [],
    }), encoding="utf-8")
    provider = SimpleNamespace(source_root=source, content_root=content, canonical_root=canonical)
    donor_source = tmp_path / "114_LEngineer.inf"
    donor_source.write_bytes(
        '*E_NAME "Lab Engineer"\r\n*J_NAME "연구소 엔지니어"\r\n'.encode("cp949")
    )
    prepared = {
        "kind": "MONSTER",
        "entry": {"id": "monster.114_lengineer", "kind": "monster_definition", "legacy_path": "GameServer/Monster/114_LEngineer.inf", "json_path": "resources/Servidor/GameServer/Monster/114_LEngineer.inf.json"},
        "document": {"id": "monster.114_lengineer", "kind": "monster_definition", "semantic": {"fields": {"name": "연구소 엔지니어"}}},
        "target_rel": Path("canonical/text/resources/Servidor/GameServer/Monster/114_LEngineer.inf.json"),
        "donor_root": tmp_path, "source": donor_source,
        "relative_path": Path("GameServer/Monster/114_LEngineer.inf"),
        "logical_path": Path("GameServer/Monster/114_LEngineer.inf"), "converter_logs": [],
    }
    monkeypatch.setattr(dre, "_prepare_definition_import", lambda *a, **k: prepared)
    monkeypatch.setattr(
        dre, "_definition_ptbr_localization_delta",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not edit materialized localization directly")),
    )
    captured = {}
    def stage(_project, _provider, changes, **kwargs):
        captured["changes"] = changes; captured["kwargs"] = kwargs
        return {"format": "X", "status": "STAGED"}
    monkeypatch.setattr(dre, "stage_canonical_document_set", stage)
    result = dre.stage_definition_from_donor(tmp_path / "project", provider, donor_label="DONOR2", relative_path="GameServer/Monster/114_LEngineer.inf", kind="MONSTER", run_validation=False, run_build=False)
    assert result["status"] == "STAGED"
    paths = [x["relative_path"] for x in captured["changes"]]
    assert paths == [
        "canonical/text/resources/Servidor/GameServer/Monster/114_LEngineer.inf.json",
        "canonical/text/index.json",
    ]
    assert captured["kwargs"]["localization_fallback_names"] == {"monster.114_lengineer": "Lab Engineer"}
    bridge = captured["kwargs"]["provenance"]["localization_bridge"]
    assert bridge == {"locale": "pt-BR", "mode": "STAGED_DELTA_OVERRIDE_BRIDGE"}


def test_definition_primary_legacy_name_prefers_cp949_j_name(tmp_path):
    source = tmp_path / "114_LEngineer.inf"
    source.write_bytes(
        '*E_NAME "Lab Engineer"\r\n*J_NAME "연구소 엔지니어"\r\n*LEVEL 100\r\n'.encode("cp949")
    )
    assert dre._definition_primary_legacy_name(source, "MONSTER") == "연구소 엔지니어"
    assert dre._definition_ptbr_fallback_name(source, "MONSTER") == "Lab Engineer"


def test_stage_definition_ptbr_bridge_uses_cp1252_safe_donor_name_when_j_name_is_korean(monkeypatch, tmp_path):
    from types import SimpleNamespace
    source_root = tmp_path / "source"; content = source_root / "Content"; canonical = content / "canonical"
    (canonical / "text/localization").mkdir(parents=True)
    (canonical / "text/index.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
    (canonical / "text/localization/pt-BR.json").write_text(json.dumps({
        "schema": "summit.localization-catalog/v1", "schema_version": 1,
        "locale": "pt-BR", "fallback_locale": "en", "entries": [],
    }), encoding="utf-8")
    provider = SimpleNamespace(source_root=source_root, content_root=content, canonical_root=canonical)
    donor_source = tmp_path / "114_LEngineer.inf"
    donor_source.write_bytes('*E_NAME "Lab Engineer"\r\n*J_NAME "연구소 엔지니어"\r\n*LEVEL 100\r\n'.encode("cp949"))
    prepared = {
        "kind": "MONSTER",
        "entry": {"id": "monster.114_lengineer", "kind": "monster_definition", "legacy_path": "GameServer/Monster/114_LEngineer.inf", "json_path": "resources/Servidor/GameServer/Monster/114_LEngineer.inf.json"},
        # Reproduce the live failure: canonicalizer output does not expose semantic.fields.name.
        "document": {"id": "monster.114_lengineer", "kind": "monster_definition", "payload": {"directives": []}},
        "target_rel": Path("canonical/text/resources/Servidor/GameServer/Monster/114_LEngineer.inf.json"),
        "donor_root": tmp_path, "source": donor_source,
        "relative_path": Path("GameServer/Monster/114_LEngineer.inf"),
        "logical_path": Path("GameServer/Monster/114_LEngineer.inf"), "converter_logs": [],
    }
    monkeypatch.setattr(dre, "_prepare_definition_import", lambda *a, **k: prepared)
    captured = {}
    def stage(_project, _provider, changes, **kwargs):
        captured["changes"] = changes; captured["kwargs"] = kwargs
        return {"format": "X", "status": "STAGED"}
    monkeypatch.setattr(dre, "stage_canonical_document_set", stage)

    result = dre.stage_definition_from_donor(
        tmp_path / "project", provider, donor_label="DONOR2",
        relative_path="GameServer/Monster/114_LEngineer.inf", kind="MONSTER",
        run_validation=False, run_build=False,
    )
    assert result["status"] == "STAGED"
    assert [x["relative_path"] for x in captured["changes"]] == [
        "canonical/text/resources/Servidor/GameServer/Monster/114_LEngineer.inf.json",
        "canonical/text/index.json",
    ]
    assert captured["kwargs"]["localization_fallback_names"] == {"monster.114_lengineer": "Lab Engineer"}
