from __future__ import annotations

import json
from pathlib import Path

import pt_asset_tool.general_asset_recovery as gar


def _pre(root_count=1):
    return {
        "status": "PASS",
        "census_state": "REVIEW_REQUIRED",
        "candidate_count": 10,
        "recoverable_reachable_candidate_count": root_count,
        "reachable_donor_conflict_count": 0,
        "reachable_hard_conflict_count": 0,
        "missing_reachable_no_donor_count": 2,
        "recovery_bundle_root_count": root_count,
        "recovery_bundle_closed_root_count": root_count,
        "recovery_bundle_review_root_count": 0,
        "recovery_bundle_incomplete_root_count": 0,
        "strong_client_path_count": 1,
        "strong_server_path_count": 0,
    }


def _post_ok():
    d = _pre(0)
    d["candidate_count"] = 9
    return d


def _bundle(source: Path, root_path="char/monster/foo/foo.inx"):
    return {
        "format": "PT_ASSET_GENERAL_RECOVERY_BUNDLES_V1",
        "status": "PASS",
        "root_count": 1,
        "status_counts": {"CLOSED": 1},
        "rows": [{
            "side": "CLIENT",
            "root_path": root_path,
            "status": "CLOSED",
            "reason": "ALL_DEPENDENCIES_TARGET_OR_SAME_LINEAGE",
            "selected_source": "D1",
            "donor_label": "D1",
            "selected_path": str(source),
            "selected_relative_path": root_path,
            "member_count": 1,
            "recover_member_count": 1,
            "missing_count": 0,
            "review_count": 0,
            "members": [{
                "logical_path": root_path,
                "physical_path": str(source),
                "state": "ROOT",
                "extension": ".inx",
            }],
            "issues": [],
        }],
    }


def _fake_audit_writer(project: Path, bundle: dict, post=None):
    calls = {"n": 0}
    def fake(*args, **kwargs):
        calls["n"] += 1
        out = project / "pt_build" / "general_asset_census"
        out.mkdir(parents=True, exist_ok=True)
        if calls["n"] == 1:
            (out / "recovery_bundles.json").write_text(json.dumps(bundle), encoding="utf-8")
            return _pre(int(bundle.get("root_count") or len(bundle.get("rows") or [])))
        (out / "recovery_bundles.json").write_text(json.dumps({
            "format": "PT_ASSET_GENERAL_RECOVERY_BUNDLES_V1",
            "status": "PASS", "root_count": 0, "status_counts": {}, "rows": [],
        }), encoding="utf-8")
        return post if post is not None else _post_ok()
    return fake


def test_closed_bundle_recovery_plan_stages_without_target_write(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"inx-data")
    bundle = _bundle(source)
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle))

    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"D1={donor}"], donor_servers=[],
        expected_roots=["CLIENT:char/monster/foo/foo.inx"], apply=False,
    )
    assert result["status"] == "PASS"
    assert result["state"] == "STAGED_ONLY"
    assert result["staged_member_count"] == 1
    assert not (client / "char/monster/foo/foo.inx").exists()
    staged = Path(result["transactions"][0]["staged_path"])
    assert staged.read_bytes() == b"inx-data"


def test_closed_bundle_recovery_apply_is_create_only_and_post_census_verified(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"verified")
    bundle = _bundle(source)
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle))

    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"D1={donor}"], donor_servers=[],
        expected_roots=["CLIENT:char/monster/foo/foo.inx"], apply=True,
    )
    assert result["status"] == "PASS"
    assert result["state"] == "APPLIED_VERIFIED"
    assert result["written_member_count"] == 1
    assert result["target_client_modified"] is True
    assert (client / "char/monster/foo/foo.inx").read_bytes() == b"verified"
    assert result["post_census"]["recoverable_reachable_candidate_count"] == 0


def test_closed_bundle_recovery_refuses_scope_change_before_write(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"x")
    bundle = _bundle(source)
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle))

    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"D1={donor}"], donor_servers=[],
        expected_roots=["CLIENT:char/monster/other/other.inx"], apply=True,
    )
    assert result["status"] == "FAIL"
    assert result["state"] == "ABORTED_NO_WRITE"
    assert "RECOVERY_SCOPE_CHANGED" in result["error"]
    assert not (client / "char/monster/foo/foo.inx").exists()


def test_closed_bundle_recovery_rolls_back_when_post_census_does_not_clear_scope(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"x")
    bundle = _bundle(source)
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle, post=_pre(1)))

    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"D1={donor}"], donor_servers=[],
        expected_roots=["CLIENT:char/monster/foo/foo.inx"], apply=True,
    )
    assert result["status"] == "FAIL"
    assert result["state"] == "ROLLED_BACK"
    assert result["rollback_performed"] is True
    assert not (client / "char/monster/foo/foo.inx").exists()


def test_three_bundle_mixed_client_server_shape_recovers_five_members(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"
    dc = tmp_path / "official"; ds = tmp_path / "exmachina"
    for p in (project, client, server, dc, ds): p.mkdir()
    # Real-target shape: both case variants may coexist on a case-sensitive host.
    # The requested exact GameServer spelling must win without weakening create-only.
    (server / "GameServer").mkdir()
    (server / "gameserver").mkdir()
    client_files = {
        "char/monster/G_Wolverin/Wolverin_A.inx": b"inx",
        "char/monster/G_Wolverin/wolverin_A.smd": b"smd",
        "char/monster/G_Wolverin/Wolverin_A.tga": b"tga",
    }
    for rel, data in client_files.items():
        p = dc / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    server_files = {
        "GameServer/Monster/name/31_BronzeWolverine.zhoon": b"bronze",
        "GameServer/Monster/name/s_FireElemental.zhoon": b"fire",
    }
    for rel, data in server_files.items():
        p = ds / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    bundle = {
        "format": "PT_ASSET_GENERAL_RECOVERY_BUNDLES_V1", "status": "PASS",
        "root_count": 3, "status_counts": {"CLOSED": 3},
        "rows": [
            {
                "side": "CLIENT", "root_path": "char/monster/G_Wolverin/Wolverin_A.inx", "status": "CLOSED",
                "donor_label": "OFFICIAL", "selected_source": "OFFICIAL",
                "members": [
                    {"logical_path": "char/monster/G_Wolverin/Wolverin_A.inx", "physical_path": str(dc / "char/monster/G_Wolverin/Wolverin_A.inx"), "state": "ROOT"},
                    {"logical_path": "Char/monster/G_Wolverin/wolverin_A.smd", "physical_path": str(dc / "char/monster/G_Wolverin/wolverin_A.smd"), "state": "RECOVER_SAME_DONOR"},
                    {"logical_path": "Char/monster/G_Wolverin/Wolverin_A.tga", "physical_path": str(dc / "char/monster/G_Wolverin/Wolverin_A.tga"), "state": "RECOVER_SAME_DONOR"},
                ],
            },
            {
                "side": "SERVER", "root_path": "GameServer/Monster/name/31_BronzeWolverine.zhoon", "status": "CLOSED",
                "donor_label": "EXMACHINA_SERVER", "selected_source": "EXMACHINA_SERVER",
                "members": [{"logical_path": "GameServer/Monster/name/31_BronzeWolverine.zhoon", "physical_path": str(ds / "GameServer/Monster/name/31_BronzeWolverine.zhoon"), "state": "ROOT"}],
            },
            {
                "side": "SERVER", "root_path": "GameServer/Monster/name/s_FireElemental.zhoon", "status": "CLOSED",
                "donor_label": "EXMACHINA_SERVER", "selected_source": "EXMACHINA_SERVER",
                "members": [{"logical_path": "GameServer/Monster/name/s_FireElemental.zhoon", "physical_path": str(ds / "GameServer/Monster/name/s_FireElemental.zhoon"), "state": "ROOT"}],
            },
        ],
    }
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle))
    expected = [
        "CLIENT:char/monster/G_Wolverin/Wolverin_A.inx",
        "SERVER:GameServer/Monster/name/31_BronzeWolverine.zhoon",
        "SERVER:GameServer/Monster/name/s_FireElemental.zhoon",
    ]
    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"OFFICIAL={dc}"], donor_servers=[f"EXMACHINA_SERVER={ds}"],
        expected_roots=expected, apply=True,
    )
    assert result["status"] == "PASS" and result["state"] == "APPLIED_VERIFIED"
    assert result["written_member_count"] == 5
    assert result["planned_client_member_count"] == 3
    assert result["planned_server_member_count"] == 2
    assert (client / "char/monster/G_Wolverin/Wolverin_A.inx").read_bytes() == b"inx"
    assert (client / "char/monster/G_Wolverin/wolverin_A.smd").read_bytes() == b"smd"
    assert (client / "char/monster/G_Wolverin/Wolverin_A.tga").read_bytes() == b"tga"
    assert not (client / "Char").exists()
    assert (server / "GameServer/Monster/name/31_BronzeWolverine.zhoon").read_bytes() == b"bronze"
    assert (server / "GameServer/Monster/name/s_FireElemental.zhoon").read_bytes() == b"fire"


def test_destination_prefers_exact_directory_spelling_amid_case_aliases(tmp_path):
    root = tmp_path / "server"; root.mkdir()
    exact = root / "GameServer"; alias = root / "gameserver"
    exact.mkdir(); alias.mkdir()
    rel = gar.pathlib.PurePosixPath("GameServer/Monster/name/new.zhoon")
    dest = gar._case_preserving_destination(root, rel)
    assert dest == exact / "Monster/name/new.zhoon"


def test_destination_still_aborts_when_case_aliases_have_no_exact_spelling(tmp_path):
    root = tmp_path / "server"; root.mkdir()
    (root / "gameserver").mkdir(); (root / "GAMESERVER").mkdir()
    rel = gar.pathlib.PurePosixPath("GameServer/Monster/name/new.zhoon")
    try:
        gar._case_preserving_destination(root, rel)
    except RuntimeError as exc:
        assert "TARGET_CASE_COLLISION_DIR" in str(exc)
    else:
        raise AssertionError("ambiguous case aliases must abort")


def test_create_only_detects_existing_file_under_alternate_case_branch(tmp_path):
    root = tmp_path / "server"; root.mkdir()
    (root / "GameServer/Monster/name").mkdir(parents=True)
    other = root / "gameserver/monster/name"; other.mkdir(parents=True)
    existing = other / "31_bronzewolverine.ZHOON"; existing.write_bytes(b"already-there")
    rel = gar.pathlib.PurePosixPath("GameServer/Monster/name/31_BronzeWolverine.zhoon")
    assert gar._casefold_existing_file(root, rel) == existing


def test_apply_preflights_all_target_parent_permissions_before_first_write(monkeypatch, tmp_path):
    client = tmp_path / "client"; server = tmp_path / "server"; stage = tmp_path / "stage"
    client_parent = client / "char/monster/foo"; server_parent = server / "GameServer/Monster/Name"
    client_parent.mkdir(parents=True); server_parent.mkdir(parents=True); stage.mkdir()
    cstage = stage / "client.inx"; sstage = stage / "server.zhoon"
    cstage.write_bytes(b"client"); sstage.write_bytes(b"server")
    tx = [
        {
            "side": "CLIENT", "target_path": str(client_parent / "foo.inx"),
            "relative_path": "char/monster/foo/foo.inx", "staged_path": str(cstage),
            "size": len(b"client"), "sha256": gar._sha256(cstage),
            "written": False, "postwrite_verified": False,
        },
        {
            "side": "SERVER", "target_path": str(server_parent / "x.zhoon"),
            "relative_path": "GameServer/Monster/Name/x.zhoon", "staged_path": str(sstage),
            "size": len(b"server"), "sha256": gar._sha256(sstage),
            "written": False, "postwrite_verified": False,
        },
    ]
    real_access = gar.os.access
    def fake_access(path, mode):
        if Path(path) == server_parent:
            return False
        return real_access(path, mode)
    monkeypatch.setattr(gar.os, "access", fake_access)

    try:
        gar._apply_transactions(tx, client, server)
    except PermissionError as exc:
        assert "RECOVERY_TARGET_PARENT_NOT_WRITABLE" in str(exc)
        assert str(server_parent) in str(exc)
    else:
        raise AssertionError("unwritable server parent must abort before any target write")
    assert not (client_parent / "foo.inx").exists()
    assert not (server_parent / "x.zhoon").exists()
    assert all(row["written"] is False for row in tx)


def test_apply_partial_failure_rolls_back_and_resets_transaction_flags(monkeypatch, tmp_path):
    client = tmp_path / "client"; server = tmp_path / "server"; stage = tmp_path / "stage"
    parent = client / "char/monster/foo"; parent.mkdir(parents=True); server.mkdir(); stage.mkdir()
    s1 = stage / "one.inx"; s2 = stage / "two.smd"
    s1.write_bytes(b"one"); s2.write_bytes(b"two")
    tx = [
        {
            "side": "CLIENT", "target_path": str(parent / "one.inx"),
            "relative_path": "char/monster/foo/one.inx", "staged_path": str(s1),
            "size": 3, "sha256": gar._sha256(s1), "written": False, "postwrite_verified": False,
        },
        {
            "side": "CLIENT", "target_path": str(parent / "two.smd"),
            "relative_path": "char/monster/foo/two.smd", "staged_path": str(s2),
            "size": 3, "sha256": gar._sha256(s2), "written": False, "postwrite_verified": False,
        },
    ]
    real_copyfile = gar.shutil.copyfile
    def fail_second(src, dst, *args, **kwargs):
        if Path(src) == s2:
            raise PermissionError("synthetic second write failure")
        return real_copyfile(src, dst, *args, **kwargs)
    monkeypatch.setattr(gar.shutil, "copyfile", fail_second)

    try:
        gar._apply_transactions(tx, client, server)
    except gar.RecoveryApplyRolledBackError as exc:
        assert exc.rolled_back_member_count == 1
        assert "synthetic second write failure" in str(exc)
    else:
        raise AssertionError("partial write failure must surface rolled-back telemetry")
    assert not (parent / "one.inx").exists()
    assert not (parent / "two.smd").exists()
    assert tx[0]["written"] is False and tx[0]["postwrite_verified"] is False
    assert tx[1]["written"] is False and tx[1]["postwrite_verified"] is False


def test_recover_reports_inner_apply_rollback_truthfully(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"x")
    bundle = _bundle(source)
    monkeypatch.setattr(gar, "audit_general_asset_census", _fake_audit_writer(project, bundle))

    def fake_apply(tx, client_root, server_root):
        tx[0]["written"] = False
        tx[0]["postwrite_verified"] = False
        raise gar.RecoveryApplyRolledBackError("synthetic apply failure", 1)
    monkeypatch.setattr(gar, "_apply_transactions", fake_apply)

    result = gar.recover_closed_general_asset_bundles(
        project, client, server,
        donor_clients=[f"D1={donor}"], donor_servers=[],
        expected_roots=["CLIENT:char/monster/foo/foo.inx"], apply=True,
    )
    assert result["status"] == "FAIL"
    assert result["state"] == "ROLLED_BACK"
    assert result["rollback_performed"] is True
    assert result["rolled_back_member_count"] == 1
    assert result["written_member_count"] == 0
    assert result["target_client_modified"] is False
    assert result["target_server_modified"] is False


def test_targeted_closed_bundle_recovery_never_calls_general_census(monkeypatch, tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; server = tmp_path / "server"; donor = tmp_path / "donor"
    for p in (project, client, server, donor): p.mkdir()
    source = donor / "char/monster/foo/foo.inx"; source.parent.mkdir(parents=True); source.write_bytes(b"targeted")
    bundle = _bundle(source)["rows"][0]
    monkeypatch.setattr(gar, "audit_general_asset_census", lambda *a, **k: (_ for _ in ()).throw(AssertionError("general census forbidden")))
    result = gar.recover_targeted_closed_asset_bundles(
        project, client, server, bundle_rows=[bundle], donor_clients=[f"D1={donor}"], donor_servers=[], apply=False,
    )
    assert result["status"] == "PASS"
    assert result["state"] == "STAGED_ONLY"
    assert result["policy"]["general_census_required"] is False
    assert result["planned_member_count"] == 1
    assert not (client / "char/monster/foo/foo.inx").exists()
