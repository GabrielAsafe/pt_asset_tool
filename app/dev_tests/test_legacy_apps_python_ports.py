from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from pt_asset_tool.legacy_apps.common import legacy_bucket
from pt_asset_tool.legacy_apps.protector import (
    BLOCK_CONFIRM,
    apply_account_block_sqlite,
    plan_account_block_sqlite,
)
from pt_asset_tool.legacy_apps.server_admin import (
    bprank_sqlite_plan,
    fetch_next_bprank,
    firewall_plan,
    local_runtime_policy,
    mark_bprank_processed,
)
from pt_asset_tool.legacy_apps.sod_manager import (
    APPLY_CONFIRM,
    SQLiteSodDataSource,
    apply_sod_updates,
    plan_sod_updates,
)
from pt_asset_tool.legacy_apps.userdata_admin import (
    LEVEL_EDIT_CONFIRM,
    USERDATA_SIZE,
    apply_level_edit,
    inspect_character_level,
    plan_level_edit,
)


def test_local_runtime_policy_retires_windows_firewall_sql_stack():
    policy = local_runtime_policy()
    assert policy["database"] == "SQLite"
    assert policy["network_mode"] == "LOCALHOST_ONLY"
    assert policy["firewall_required"] is False
    assert policy["sql_server_required"] is False
    compat = firewall_plan()
    assert compat["status"] == "NOT_APPLICABLE"
    assert compat["commands"] == []


def _create_sod_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE RunLog(CharName TEXT, ServerTime INTEGER, TotalPoint INTEGER, SuccessUser INTEGER, Point INTEGER);
            CREATE TABLE UL(ChName TEXT PRIMARY KEY, ClanName TEXT);
            CREATE TABLE CL(ClanName TEXT PRIMARY KEY, Cpoint INTEGER, ClanMoney INTEGER);
            INSERT INTO UL VALUES ('Alice','Red'),('Bob','Red'),('Eve','Blue');
            INSERT INTO CL VALUES ('Red',10,50),('Blue',20,70);
            INSERT INTO RunLog VALUES
              ('Alice',100,1000,3,500),
              ('Bob',100,1000,3,300),
              ('Eve',100,1000,3,200);
            """
        )


def test_sod_workflow_runs_entirely_on_local_sqlite(tmp_path: Path):
    db_path = tmp_path / "game.sqlite3"
    _create_sod_db(db_path)
    with SQLiteSodDataSource(db_path) as source:
        plan = plan_sod_updates(source, "RunLog", minimum_players=2)
        assert plan["status"] == "READY"
        assert len(plan["updates"]) == 1
        assert plan["updates"][0]["clan_name"] == "Red"
        assert plan["updates"][0]["new_point"] == 800
        out = apply_sod_updates(source, plan, confirmation=APPLY_CONFIRM)
        assert out["status"] == "PASS"
        assert source.clan_point("Red") == 800
        assert source.top_clan() == "Red"
        assert source.clan_money("Red") == 50


def test_bprank_uses_sqlite_limit_and_marks_row(tmp_path: Path):
    db_path = tmp_path / "rank.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE GameRecordBPRank(CharName TEXT, BP INTEGER, DP INTEGER, ok INTEGER)")
        db.executemany("INSERT INTO GameRecordBPRank VALUES (?,?,?,?)", [("A",10,2,0),("B",30,4,0)])
    plan = bprank_sqlite_plan()
    assert "LIMIT 1" in plan["select_sql"]
    assert "TOP 1" not in plan["select_sql"]
    first = fetch_next_bprank(db_path)
    assert first["row"]["char_name"] == "B"
    marked = mark_bprank_processed(db_path, "B")
    assert marked["status"] == "PASS"
    assert fetch_next_bprank(db_path)["row"]["char_name"] == "A"


def test_protector_account_block_is_local_sqlite(tmp_path: Path):
    db_path = tmp_path / "account.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE GameUser(userid TEXT PRIMARY KEY, BlockChk INTEGER, reason TEXT)")
        db.execute("INSERT INTO GameUser VALUES ('gabriel',0,'')")
    plan = plan_account_block_sqlite(
        table="GameUser",
        account_column="userid",
        account="gabriel",
        reason_column="reason",
        reason="test",
    )
    assert plan["database"] == "SQLite"
    out = apply_account_block_sqlite(plan, db_path=db_path, confirmation=BLOCK_CONFIRM)
    assert out["status"] == "PASS"
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT BlockChk, reason FROM GameUser WHERE userid='gabriel'").fetchone() == (1, "test")


def test_level_editor_exact_offsets_with_supplied_xphex(tmp_path: Path):
    server = tmp_path / "server"
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    raw = bytearray(USERDATA_SIZE)
    # Start at level 300 to exercise the corrected stale-high-byte case.
    raw[0xC8:0xCA] = (299).to_bytes(2, "little")
    user.write_bytes(raw)
    xphex = tmp_path / "XPHex.txt"
    xphex.write_text("0000000000000001\n0000000000000102\n", encoding="ascii")

    plan = plan_level_edit(server, char, 2, xphen_path=xphex)
    assert plan["status"] == "READY"
    assert plan["level_before"] == 300
    assert plan["level_after"] == 2
    out = apply_level_edit(plan, confirmation=LEVEL_EDIT_CONFIRM, backup_root=tmp_path / "backups")
    assert out["status"] == "PASS"
    after = inspect_character_level(server, char)
    assert after["level"] == 2
    assert user.read_bytes()[0xC8:0xCA] == b"\x01\x00"
    assert after["xp_value"] == 0x102


def test_controlleruser_smchar_info_source_abi_crosscheck(tmp_path):
    from pt_asset_tool.legacy_apps.common import legacy_bucket
    from pt_asset_tool.legacy_apps.userdata_admin import inspect_character_info, USERDATA_SIZE
    import struct
    root = tmp_path / "server"
    name = "Hero"
    p = root / "DataServer" / "userdata" / str(legacy_bucket(name)) / f"{name}.dat"
    p.parent.mkdir(parents=True)
    raw = bytearray(USERDATA_SIZE)
    raw[0x10:0x10+32] = b"Hero\0" + b"\0" * (32-5)
    raw[0xC8:0xCC] = (123).to_bytes(4, "little", signed=True)
    raw[0xCC:0xD0] = (321).to_bytes(4, "little", signed=True)  # Strength
    raw[0x14C:0x150] = (0x11223344).to_bytes(4, "little", signed=True)
    raw[0x194:0x198] = (0x556677).to_bytes(4, "little", signed=True)
    raw[0x154:0x158] = (99999).to_bytes(4, "little", signed=True)  # Money: 0x10+324
    raw[0x140:0x144] = struct.pack("<f", 1.25)  # Life_Regen: 0x10+304
    p.write_bytes(raw)
    got = inspect_character_info(root, name)
    assert got["status"] == "PASS"
    assert got["fields"]["szName"] == "Hero"
    assert got["fields"]["Level"] == 123
    assert got["fields"]["Strength"] == 321
    assert got["fields"]["Exp"] == 0x11223344
    assert got["fields"]["Exp_High"] == 0x556677
    assert got["fields"]["Money"] == 99999
    assert got["absolute_offsets"]["Level"] == "0xc8"


def test_xp_table_audit_rejects_non_monotonic_and_parses_c_initializer(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import audit_xphex, discover_xp_tables
    bad = tmp_path / "XPHex.txt"
    bad.write_text("0010\n0001\n", encoding="ascii")
    original = tmp_path / "XPHexOriginal.txt"
    original.write_text("0000\n03E8\n09C4\n", encoding="ascii")
    current = tmp_path / "XPHex2.txt"
    current.write_text("0x0,\n0x1F4,\n0x5DC,\n/*0x1194,\n0x2134,*/\n", encoding="ascii")
    assert audit_xphex(bad)["write_usable"] is False
    assert audit_xphex(current)["levels"] == 3
    found = discover_xp_tables(tmp_path)
    assert found["status"] == "PASS"
    assert Path(found["recommended_path"]).name == "XPHex2.txt"
    assert found["recommended_levels"] == 3


def test_level_edit_can_autodiscover_xphex2(tmp_path: Path):
    from pt_asset_tool.legacy_apps.common import legacy_bucket
    from pt_asset_tool.legacy_apps.userdata_admin import plan_level_edit, USERDATA_SIZE
    server = tmp_path / "server"
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    user.write_bytes(bytes(USERDATA_SIZE))
    (server / "XPHex2.txt").write_text("0x0,\n0x1F4,\n0x5DC,\n/*0x1194,*/\n", encoding="ascii")
    plan = plan_level_edit(server, char, 3)
    assert plan["status"] == "READY"
    assert plan["level_after"] == 3
    assert plan["xp_after"] == 0x5DC
    assert Path(plan["xphex_path"]).name == "XPHex2.txt"


def test_controlleruser_sumfiles_are_generated_scratch_not_dependencies():
    from pt_asset_tool.legacy_apps.userdata_admin import controlleruser_reverse_artifacts
    info = controlleruser_reverse_artifacts()
    assert info["status"] == "PASS"
    assert info["runtime_dependencies"] == []
    rows = {x["name"]: x for x in info["generated_legacy_artifacts"]}
    assert rows["SumFile.dat"]["required"] is False
    assert rows["CompyItem.dat"]["required"] is False
    assert rows["<target>cp.dat"]["required"] is False
    assert "GENERIC_WRITE" in info["evidence"]["SumFile.dat"]


def test_level_capability_uses_discovered_valid_table_without_named_dependency(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import level_edit_capability
    server = tmp_path / "server"
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    user.write_bytes(bytes(USERDATA_SIZE))
    (server / "XPHex2.txt").write_text("0x0,\n0x1F4,\n0x5DC,\n", encoding="ascii")
    cap = level_edit_capability(server, char)
    assert cap["status"] == "READY"
    assert Path(cap["xp_table_path"]).name == "XPHex2.txt"
    assert cap["xp_table_audit"]["write_usable"] is True


def test_character_primary_stats_can_be_updated_without_legacy_scratch_files(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import (
        CHARACTER_FIELDS_CONFIRM,
        apply_character_fields_update,
        character_edit_capabilities,
        inspect_character_info,
        plan_character_fields_update,
    )
    server = tmp_path / "server"
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    raw = bytearray(USERDATA_SIZE)
    raw[0x10:0x10+32] = b"Hero\0" + b"\0" * (32-5)
    user.write_bytes(raw)
    cap = character_edit_capabilities()
    assert "Strength" in cap["safe_edit_fields"]
    assert cap["legacy_scratch_files_required"] is False
    plan = plan_character_fields_update(server, char, {"Strength": 99, "Money": 123456})
    assert plan["status"] == "READY"
    assert plan["safety"]["scratch_dat_dependencies"] is False
    out = apply_character_fields_update(plan, confirmation=CHARACTER_FIELDS_CONFIRM, backup_root=tmp_path / "backups")
    assert out["status"] == "PASS"
    info = inspect_character_info(server, char)
    assert info["fields"]["Strength"] == 99
    assert info["fields"]["Money"] == 123456
    assert not (server / "SumFile.dat").exists()
    assert not (server / "CompyItem.dat").exists()


def test_restarter_plan_targets_local_wine_server_without_network_stack(tmp_path: Path):
    from pt_asset_tool.legacy_apps.server_admin import restarter_launch_plan, bounded_restart_policy
    server = tmp_path / "Servidor"
    server.mkdir()
    exe = server / "Server.exe"
    exe.write_bytes(b"MZ")
    cfg = tmp_path / "ConfigRestarter.ini"
    cfg.write_text("[PT Restarter]\nNomeEXE=Server.exe\nMensagem=Servidor iniciou\n", encoding="latin-1")
    plan = restarter_launch_plan(cfg, server_root=server, wine_command="/usr/bin/true")
    assert plan["status"] == "READY"
    assert plan["runtime"] == "WINE"
    assert plan["command"] == ["/usr/bin/true", str(exe.resolve())]
    assert plan["database_mode"] == "SQLite/local"
    assert plan["network_mode"] == "LOCALHOST_ONLY"
    pol = bounded_restart_policy(max_restarts=3, delay_seconds=1.5)
    assert pol["max_restarts"] == 3


def test_character_expert_source_backed_fields_are_schema_gated_and_verified(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import (
        EXPERT_CHARACTER_FIELDS_CONFIRM,
        USERDATA_SIZE,
        apply_character_expert_fields_update,
        inspect_character_info,
        plan_character_expert_fields_update,
    )
    server = tmp_path / "server"
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    raw = bytearray(USERDATA_SIZE)
    raw[0x10:0x10+32] = b"Hero\0" + b"\0" * (32 - 5)
    user.write_bytes(raw)

    plan = plan_character_expert_fields_update(server, char, {
        "JOB_CODE": 7,
        "Attack_Damage": [123, 456],
        "szModelName": "char\\tmABCD.ini",
    })
    assert plan["status"] == "READY"
    assert plan["safety"]["arbitrary_offsets"] is False
    assert plan["safety"]["inventory_or_item_serials_modified"] is False
    out = apply_character_expert_fields_update(
        plan,
        confirmation=EXPERT_CHARACTER_FIELDS_CONFIRM,
        backup_root=tmp_path / "backups",
    )
    assert out["status"] == "PASS"
    info = inspect_character_info(server, char)
    assert info["fields"]["JOB_CODE"] == 7
    assert info["fields"]["Attack_Damage"] == [123, 456]
    assert info["fields"]["szModelName"] == "char\\tmABCD.ini"

    try:
        plan_character_expert_fields_update(server, char, {"dwLoginServerSafeKey": 1})
    except ValueError as exc:
        assert "BLOCKED_OR_UNKNOWN" in str(exc)
    else:
        raise AssertionError("runtime login/security field must remain blocked")


def test_expert_character_operation_is_wired_through_plan_store_workspace_and_apply(tmp_path: Path):
    from pt_asset_tool.legacy_apps.apply import apply_saved_plan
    from pt_asset_tool.legacy_apps.plan_store import save_plan
    from pt_asset_tool.legacy_apps.userdata_admin import USERDATA_SIZE
    from pt_asset_tool.legacy_apps.workspace import plan_operation
    server = tmp_path / "server"
    project = tmp_path / "project"
    project.mkdir()
    char = "Hero"
    user = server / "DataServer" / "userdata" / str(legacy_bucket(char)) / f"{char}.dat"
    user.parent.mkdir(parents=True)
    raw = bytearray(USERDATA_SIZE)
    raw[0x10:0x10+32] = b"Hero\0" + b"\0" * (32 - 5)
    user.write_bytes(raw)

    plan = plan_operation(server, "CHARACTER_EXPERT_FIELDS", {"character": char, "updates": {"JOB_CODE": 3}})
    saved = save_plan(project, "CHARACTER_EXPERT_FIELDS", plan)
    assert saved["required_confirmation"] == "APPLY EXPERT CHARACTER FIELDS"
    assert saved["apply_supported"] is True
    result = apply_saved_plan(project, server, saved["plan_id"], "APPLY EXPERT CHARACTER FIELDS")
    assert result["status"] == "PASS"
    assert result["result"]["verified"]["JOB_CODE"] == 3


def test_ptprotector_proven_action_prefix_is_parsed_without_auto_execution(tmp_path: Path):
    from pt_asset_tool.legacy_apps.protector import analyze_log_lines, parse_error_rule, protector_capabilities
    rules = tmp_path / "PTProtector"
    rules.mkdir()
    (rules / "error_library.txt").write_text(":ban CHEAT %id %ip\n:skip KNOWN_NOISE\n:dc SPEED %id\n", encoding="latin-1")
    (rules / "excluded_account.txt").write_text("Trusted\n", encoding="latin-1")
    (rules / "excluded_ip.txt").write_text("127.0.0.2\n", encoding="latin-1")
    (rules / "error_alias.txt").write_text("CHEAT=Anti-hack\n", encoding="latin-1")

    parsed = parse_error_rule(":ban CHEAT %id %ip")
    assert parsed["action"] == "ban"
    assert parsed["required_identifiers"] == ["id", "ip"]
    assert parsed["literal_skeleton"] == "CHEAT"
    caps = protector_capabilities()
    assert caps["runtime"] == "localhost + SQLite"
    assert "ban" in caps["not_auto_executed"]

    result = analyze_log_lines([
        "CHEAT account=BadGuy 127.0.0.1",
        "CHEAT account=Trusted 127.0.0.1",
        "SPEED account=FastGuy",
        "KNOWN_NOISE",
    ], rule_root=rules)
    assert result["event_count"] == 4
    assert result["events"][0]["recommended_action"] == "PLAN_BAN"
    assert result["events"][0]["automatic_action_executed"] is False
    assert result["events"][1]["recommended_action"] == "IGNORE_EXCEPTION"
    assert result["events"][2]["recommended_action"] == "PLAN_DISCONNECT"
    assert result["events"][3]["recommended_action"] == "SKIP"


def test_ptprotector_missing_proven_identifier_degrades_to_review(tmp_path: Path):
    from pt_asset_tool.legacy_apps.protector import analyze_log_lines
    rules = tmp_path / "rules"; rules.mkdir()
    (rules / "error_library.txt").write_text(":ban CHEAT %id %ip\n", encoding="latin-1")
    result = analyze_log_lines(["CHEAT account=OnlyId"], rule_root=rules)
    assert result["events"][0]["recommended_action"] == "REVIEW"
    assert result["events"][0]["actions"][0]["reason"] == "REQUIRED_IDENTIFIER_MISSING"
    assert result["events"][0]["actions"][0]["missing"] == ["ip"]


def test_pritator_exp_formula_and_bulk_plan_are_reimplemented_without_datatable(tmp_path: Path):
    from pt_asset_tool.legacy_apps.pritator_bulk import evaluate_formula, plan_bulk_experience
    from pt_asset_tool.asset_compiler import _source_token
    server=tmp_path/"server"
    monster=server/"GameServer"/"Monster"/"Wolf.inf"
    monster.parent.mkdir(parents=True)
    level=_source_token("character_tokens","Level")
    exp=_source_token("character_tokens","Experience")
    name=_source_token("character_tokens","Name")
    monster.write_text(f'{name} "Wolf"\n{level} 10\n{exp} 1000\n',encoding="utf-8")
    calc=evaluate_formula("EXP * 2 + LVL * 100",exp=1000,level=10)
    assert calc["integer"]==3000
    plan=plan_bulk_experience(server,["GameServer/Monster/Wolf.inf"],"EXP * 2 + LVL * 100",max_exp=5000)
    assert plan["status"]=="READY"
    assert plan["rows"][0]["new_experience"]==3000
    assert plan["warning_count"]==0
    assert "DataTable.Compute" in plan["legacy_evidence"]["formula_engine"]


def test_pritator_formula_blocks_code_and_unknown_identifiers():
    from pt_asset_tool.legacy_apps.pritator_bulk import evaluate_formula
    for bad in ("__import__('os')", "EXP + GOLD", "(1).__class__"):
        try:
            evaluate_formula(bad,exp=10,level=2)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)


def test_management_archive_every_unique_exe_hash_has_reverse_manifest_entry():
    import hashlib, zipfile
    from pt_asset_tool.legacy_apps.reverse_manifest import apps, reverse_status
    archive = Path("/mnt/data/Management(2).zip")
    if not archive.is_file():
        import pytest
        pytest.skip("Management(2).zip not mounted in this test environment")
    with zipfile.ZipFile(archive) as zf:
        archive_hashes = {
            hashlib.sha256(zf.read(name)).hexdigest()
            for name in zf.namelist() if name.lower().endswith(".exe")
        }
    manifest_hashes = {
        h for app in apps() for h in (app.sha256, *app.alternate_hashes) if len(h) == 64
    }
    assert len(archive_hashes) == 13
    assert archive_hashes == manifest_hashes
    assert reverse_status()["unique_binary_hashes"] == 13


def test_pritator_gold_formula_preserves_money_drop_shape_and_percentage(tmp_path: Path):
    from pt_asset_tool.legacy_apps.pritator_bulk import evaluate_gold_formula, plan_bulk_gold
    from pt_asset_tool.asset_compiler import _source_token
    server = tmp_path / "server"
    monster = server / "GameServer" / "Monster" / "GoldWolf.inf"
    monster.parent.mkdir(parents=True)
    name = _source_token("character_tokens", "Name")
    level = _source_token("character_tokens", "Level")
    fall = _source_token("character_tokens", "FallItem")
    money = _source_token("character_tokens", "Money")
    monster.write_text(
        f'{name} "GoldWolf"\n{level} 20\n{fall} 35 {money} 100 200\n{fall} 65 WA101\n',
        encoding="utf-8",
    )
    calc = evaluate_gold_formula("GOLD * 2 + LVL", gold=100, level=20)
    assert calc["integer"] == 220
    plan = plan_bulk_gold(server, ["GameServer/Monster/GoldWolf.inf"], "GOLD * 2 + LVL", max_gold=500)
    assert plan["status"] == "READY"
    row = plan["rows"][0]
    assert row["gold_values"] == [100, 200]
    assert row["new_gold_values"] == [220, 420]
    assert row["new_drops"][0] == {"percentage": 35, "money": [220, 420]}
    assert row["new_drops"][1] == {"percentage": 65, "items": ["WA101"]}
    assert plan["warning_count"] == 0


def test_pritator_gold_single_value_is_supported_like_legacy_form3(tmp_path: Path):
    from pt_asset_tool.legacy_apps.pritator_bulk import plan_bulk_gold
    from pt_asset_tool.asset_compiler import _source_token
    server = tmp_path / "server"
    monster = server / "GameServer" / "Monster" / "SingleGold.inf"
    monster.parent.mkdir(parents=True)
    level = _source_token("character_tokens", "Level")
    fall = _source_token("character_tokens", "FallItem")
    money = _source_token("character_tokens", "Money")
    monster.write_text(f'{level} 5\n{fall} 100 {money} 77\n', encoding="utf-8")
    plan = plan_bulk_gold(server, ["GameServer/Monster/SingleGold.inf"], "GOLD + LVL")
    assert plan["rows"][0]["gold_values"] == [77]
    assert plan["rows"][0]["new_gold_values"] == [82]
    assert plan["rows"][0]["new_drops"][0] == {"percentage": 100, "money": [82]}


def test_userinfo_supports_six_character_slots_and_rename_sixth_slot(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import (
        USERINFO_CHARACTER_COUNT, USERINFO_SIZE, USERDATA_SIZE,
        inspect_userinfo, plan_character_rename,
    )
    assert USERINFO_CHARACTER_COUNT == 6
    server = tmp_path / "server"
    account = "acct"
    chars = ["One", "Two", "Three", "Four", "Five", "Six"]
    info = server / "DataServer" / "userinfo" / str(legacy_bucket(account)) / f"{account}.dat"
    info.parent.mkdir(parents=True)
    raw = bytearray(USERINFO_SIZE)
    raw[0x10:0x10+32] = account.encode() + b"\0" * (32-len(account))
    for i, name in enumerate(chars):
        off = 0x30 + i * 0x20
        raw[off:off+32] = name.encode() + b"\0" * (32-len(name))
    info.write_bytes(raw)
    for name in chars:
        user = server / "DataServer" / "userdata" / str(legacy_bucket(name)) / f"{name}.dat"
        user.parent.mkdir(parents=True, exist_ok=True)
        u = bytearray(USERDATA_SIZE)
        u[0x10:0x10+32] = name.encode() + b"\0" * (32-len(name))
        u[0x2C0:0x2C0+32] = account.encode() + b"\0" * (32-len(account))
        user.write_bytes(u)
    got = inspect_userinfo(info)
    assert got["characters"] == chars
    plan = plan_character_rename(server, "Six", "SixRenamed")
    assert plan["status"] == "READY"
    assert plan["userinfo_slot"] == 5
    assert plan["new_userinfo"][0xD0:0xD0+32].split(b"\0",1)[0] == b"SixRenamed"


def _write_account_graph_fixture(server: Path, account: str, characters: list[str], *, warehouse: bytes | None = None) -> None:
    from pt_asset_tool.legacy_apps.userdata_admin import USERINFO_SIZE, USERDATA_SIZE
    info = server / "DataServer" / "userinfo" / str(legacy_bucket(account)) / f"{account}.dat"
    info.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray(USERINFO_SIZE)
    raw[0x10:0x10+32] = account.encode("latin-1") + b"\0" * (32-len(account.encode("latin-1")))
    for i, name in enumerate(characters):
        off = 0x30 + i * 0x20
        enc = name.encode("latin-1")
        raw[off:off+32] = enc + b"\0" * (32-len(enc))
    info.write_bytes(raw)
    for name in characters:
        user = server / "DataServer" / "userdata" / str(legacy_bucket(name)) / f"{name}.dat"
        user.parent.mkdir(parents=True, exist_ok=True)
        u = bytearray(USERDATA_SIZE)
        n = name.encode("latin-1"); a = account.encode("latin-1")
        u[0x10:0x10+32] = n + b"\0" * (32-len(n))
        u[0x2C0:0x2C0+32] = a + b"\0" * (32-len(a))
        user.write_bytes(u)
    if warehouse is not None:
        wh = server / "DataServer" / "warehouse" / str(legacy_bucket(account)) / f"{account}.war"
        wh.parent.mkdir(parents=True, exist_ok=True)
        wh.write_bytes(warehouse)


def test_controlleruser_copy_is_replaced_by_explicit_account_graph_copy_with_six_slots(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import (
        ACCOUNT_GRAPH_COPY_CONFIRM, apply_account_graph_copy, plan_account_graph_copy,
    )
    from pt_asset_tool.legacy_apps.common import sha256_file
    source = tmp_path / "source_server"
    dest = tmp_path / "dest_server"
    chars = ["One", "Two", "Three", "Four", "Five", "Six"]
    _write_account_graph_fixture(source, "acct", chars, warehouse=b"warehouse-bytes")

    plan = plan_account_graph_copy(source, dest, "acct")
    assert plan["status"] == "READY"
    assert plan["characters"] == chars
    assert plan["target_count"] == 8  # userinfo + warehouse + six userdata
    assert plan["required_confirmation"] == ACCOUNT_GRAPH_COPY_CONFIRM
    assert "DataServer1" in plan["legacy_evidence"]["ControllerUser.Copy"]
    source_hashes = {row["role"]: row["source_sha256"] for row in plan["targets"]}

    result = apply_account_graph_copy(
        plan, confirmation=ACCOUNT_GRAPH_COPY_CONFIRM, backup_root=tmp_path / "backups"
    )
    assert result["status"] == "PASS"
    assert len(result["written"]) == 8
    for row in plan["targets"]:
        assert sha256_file(Path(row["destination"])) == source_hashes[row["role"]]
    # The sixth slot is part of the migrated graph, not silently dropped.
    assert any(row["role"] == "userdata:Six" for row in plan["targets"])


def test_account_graph_copy_blocks_collision_by_default_and_guards_destination_drift(tmp_path: Path):
    from pt_asset_tool.legacy_apps.userdata_admin import (
        ACCOUNT_GRAPH_COPY_CONFIRM, apply_account_graph_copy, plan_account_graph_copy,
    )
    source = tmp_path / "source_server"; dest = tmp_path / "dest_server"
    _write_account_graph_fixture(source, "acct", ["Hero"])
    _write_account_graph_fixture(dest, "acct", ["Hero"])
    blocked = plan_account_graph_copy(source, dest, "acct")
    assert blocked["status"] == "BLOCKED"
    assert blocked["reason"] == "DESTINATION_GRAPH_EXISTS"

    plan = plan_account_graph_copy(source, dest, "acct", allow_replace=True)
    assert plan["status"] == "READY"
    # Mutating a reviewed destination invalidates the plan before any write.
    info = dest / "DataServer" / "userinfo" / str(legacy_bucket("acct")) / "acct.dat"
    info.write_bytes(info.read_bytes()[:-1] + b"X")
    try:
        apply_account_graph_copy(plan, confirmation=ACCOUNT_GRAPH_COPY_CONFIRM, backup_root=tmp_path / "backups")
    except ValueError as exc:
        assert "ACCOUNT_GRAPH_DESTINATION_DRIFTED" in str(exc)
    else:
        raise AssertionError("destination drift must block account graph copy")


def test_account_graph_copy_is_wired_through_workspace_plan_store_and_apply(tmp_path: Path):
    from pt_asset_tool.legacy_apps.apply import apply_saved_plan
    from pt_asset_tool.legacy_apps.plan_store import save_plan
    from pt_asset_tool.legacy_apps.workspace import plan_operation
    source = tmp_path / "source_server"; dest = tmp_path / "dest_server"; project = tmp_path / "project"
    project.mkdir()
    _write_account_graph_fixture(source, "acct", ["Hero"])
    plan = plan_operation(dest, "ACCOUNT_GRAPH_COPY", {
        "source_server_root": str(source), "account": "acct", "allow_replace": False,
    })
    assert plan["status"] == "READY"
    saved = save_plan(project, "ACCOUNT_GRAPH_COPY", plan)
    assert saved["required_confirmation"] == "COPY ACCOUNT GRAPH"
    assert saved["apply_supported"] is True
    result = apply_saved_plan(project, dest, saved["plan_id"], "COPY ACCOUNT GRAPH")
    assert result["status"] == "PASS"
    assert result["result"]["operation"] == "ACCOUNT_GRAPH_COPY"


def test_reverse_manifest_has_complete_management_pe_decision_coverage_without_fake_gaps():
    from pt_asset_tool.legacy_apps.reverse_manifest import reverse_status
    status = reverse_status()
    assert status["format"] == "PT_LEGACY_APPS_REVERSE_STATUS_V3"
    assert status["coverage"]["management_unique_pe_expected"] == 13
    assert status["coverage"]["management_unique_pe_mapped"] == 13
    assert status["coverage"]["management_unique_pe_unmapped"] == 0
    assert status["coverage"]["applications_with_remaining_operational_gaps"] == 0
    for row in status["applications"]:
        assert isinstance(row["corrections"], (list, tuple))
        assert isinstance(row["remaining_gaps"], (list, tuple))
