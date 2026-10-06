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
