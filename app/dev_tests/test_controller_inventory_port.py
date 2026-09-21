from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pt_asset_tool.legacy_apps.common import legacy_bucket
from pt_asset_tool.legacy_apps.controller_inventory import (
    DELETE_CONFIRM,
    USERDATA_SIZE,
    USER_ITEM_COUNT_OFFSET,
    USER_ITEM_PAYLOAD_OFFSET,
    USER_ITEM_STRUCT_SIZE,
    USER_HEAD_OFFSET,
    USER_CHECKSUM_OFFSET,
    USER_CODE_OFFSET,
    WAREHOUSE_SIZE,
    WAREHOUSE_HEADER_SIZE,
    WAREHOUSE_RECORD_COUNT,
    WAREHOUSE_RECORD_SIZE,
    WAREHOUSE_HEAD_OFFSET,
    WAREHOUSE_CHECKSUM_OFFSET,
    WAREHOUSE_CODE_OFFSET,
    apply_item_delete,
    inspect_fixed_inventory,
    legacy_zero_rle_compress,
    legacy_zero_rle_decompress,
    plan_item_delete,
)


def _put_u32(buf: bytearray, off: int, value: int) -> None:
    buf[off:off+4] = int(value).to_bytes(4, "little")


def _record(size: int, *, head_off: int, checksum_off: int, seed: int, code_off: int | None = None) -> bytes:
    raw = bytearray(size)
    # Mix literals, isolated zeros and long zero runs.
    raw[0:12] = bytes(((seed + i) & 0xFF) or 1 for i in range(12))
    raw[80:92] = b"HELLO-ITEM!!"
    _put_u32(raw, head_off, 0x11000000 + seed)
    _put_u32(raw, checksum_off, 0x22000000 + seed)
    if code_off is not None:
        _put_u32(raw, code_off, 0x33000000 + seed)
    raw[-1] = seed & 0xFF or 1
    return bytes(raw)


def test_controller_zero_rle_roundtrip_edge_cases():
    samples = [
        b"",
        b"abc",
        b"a\x00b",
        b"a\x00\x00b",
        b"\x00" * 400,
        bytes(range(1, 128)) + b"\x00\x00" + bytes(range(127, 0, -1)),
    ]
    for raw in samples:
        encoded = legacy_zero_rle_compress(raw)
        assert int.from_bytes(encoded[:4], "little") == len(encoded)
        assert legacy_zero_rle_decompress(encoded, expected_size=len(raw)) == raw


def _write_userdata(path: Path, records: list[bytes]) -> bytes:
    raw = bytearray(USERDATA_SIZE)
    raw[:64] = bytes(range(64))
    _put_u32(raw, USER_ITEM_COUNT_OFFSET, len(records))
    payload = b"".join(legacy_zero_rle_compress(r) for r in records)
    raw[USER_ITEM_PAYLOAD_OFFSET:USER_ITEM_PAYLOAD_OFFSET+len(payload)] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return bytes(raw)


def _write_warehouse(path: Path, records: list[bytes]) -> bytes:
    assert len(records) == WAREHOUSE_RECORD_COUNT
    raw = bytearray(WAREHOUSE_SIZE)
    # Header deliberately non-zero; the Python writer must preserve it.
    raw[:WAREHOUSE_HEADER_SIZE] = bytes((0xA0 + i) & 0xFF for i in range(WAREHOUSE_HEADER_SIZE))
    blob = legacy_zero_rle_compress(b"".join(records))
    raw[WAREHOUSE_HEADER_SIZE:WAREHOUSE_HEADER_SIZE+len(blob)] = blob
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return bytes(raw)


def test_userdata_delete_is_guarded_backed_up_and_keeps_other_records(tmp_path):
    root = tmp_path / "server"
    key = "Hero"
    p = root / "DataServer" / "userdata" / str(legacy_bucket(key)) / f"{key}.dat"
    r0 = _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, code_off=USER_CODE_OFFSET, seed=1)
    r1 = _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, code_off=USER_CODE_OFFSET, seed=2)
    _write_userdata(p, [r0, r1])

    state = inspect_fixed_inventory(p, store="userdata")
    assert state["record_count"] == 2
    assert state["records"][1]["head"] == 0x11000002
    assert state["records"][1]["code"] == 0x33000002
    plan = plan_item_delete(root, store="userdata", key=key, record_index=1)
    assert plan["status"] == "READY"
    assert plan["guard"]["checksum"] == 0x22000002
    assert plan["guard"]["code"] == 0x33000002
    before_sha = hashlib.sha256(p.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        apply_item_delete(plan, confirmation="wrong", backup_root=tmp_path / "backup")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before_sha

    result = apply_item_delete(plan, confirmation=DELETE_CONFIRM, backup_root=tmp_path / "backup")
    assert result["status"] == "PASS"
    assert Path(result["backup"]).is_file()
    after = inspect_fixed_inventory(p, store="userdata")
    assert after["records"][0]["sha256"] == hashlib.sha256(r0).hexdigest()
    assert after["records"][1]["empty"] is True


def test_userdata_delete_refuses_source_drift(tmp_path):
    root = tmp_path / "server"; key = "Hero"
    p = root / "DataServer" / "userdata" / str(legacy_bucket(key)) / f"{key}.dat"
    record = _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, seed=3)
    _write_userdata(p, [record])
    plan = plan_item_delete(root, store="userdata", key=key, record_index=0)
    raw = bytearray(p.read_bytes()); raw[0] ^= 1; p.write_bytes(raw)
    with pytest.raises(ValueError, match="SOURCE_DRIFTED"):
        apply_item_delete(plan, confirmation=DELETE_CONFIRM, backup_root=tmp_path / "backup")


def test_warehouse_delete_preserves_header_and_other_records(tmp_path):
    root = tmp_path / "server"; key = "Account"
    p = root / "DataServer" / "warehouse" / str(legacy_bucket(key)) / f"{key}.war"
    records = [bytes(WAREHOUSE_RECORD_SIZE) for _ in range(WAREHOUSE_RECORD_COUNT)]
    records[4] = _record(WAREHOUSE_RECORD_SIZE, head_off=WAREHOUSE_HEAD_OFFSET, checksum_off=WAREHOUSE_CHECKSUM_OFFSET, code_off=WAREHOUSE_CODE_OFFSET, seed=4)
    records[5] = _record(WAREHOUSE_RECORD_SIZE, head_off=WAREHOUSE_HEAD_OFFSET, checksum_off=WAREHOUSE_CHECKSUM_OFFSET, code_off=WAREHOUSE_CODE_OFFSET, seed=5)
    original = _write_warehouse(p, records)
    header = original[:WAREHOUSE_HEADER_SIZE]

    plan = plan_item_delete(root, store="warehouse", key=key, record_index=4)
    assert plan["status"] == "READY"
    assert plan["safety"]["warehouse_header_preserved"] is True
    apply_item_delete(plan, confirmation=DELETE_CONFIRM, backup_root=tmp_path / "backup")
    written = p.read_bytes()
    assert written[:WAREHOUSE_HEADER_SIZE] == header
    state = inspect_fixed_inventory(p, store="warehouse")
    assert state["records"][4]["empty"] is True
    assert state["records"][5]["sha256"] == hashlib.sha256(records[5]).hexdigest()


def test_plan_blocks_empty_record(tmp_path):
    root = tmp_path / "server"; key = "Account"
    p = root / "DataServer" / "warehouse" / str(legacy_bucket(key)) / f"{key}.war"
    _write_warehouse(p, [bytes(WAREHOUSE_RECORD_SIZE) for _ in range(WAREHOUSE_RECORD_COUNT)])
    plan = plan_item_delete(root, store="warehouse", key=key, record_index=0)
    assert plan["status"] == "BLOCKED"
    assert plan["reason"] == "RECORD_ALREADY_EMPTY"


def test_inventory_delete_is_wired_to_workspace_plan_store_and_ui():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    py = (root / "pt_asset_tool/ui_app.py").read_text(encoding="utf-8")
    workspace = (root / "pt_asset_tool/legacy_apps/workspace.py").read_text(encoding="utf-8")
    store = (root / "pt_asset_tool/legacy_apps/plan_store.py").read_text(encoding="utf-8")
    apply_py = (root / "pt_asset_tool/legacy_apps/apply.py").read_text(encoding="utf-8")
    for element_id in ("legacyInventoryStore", "legacyInventoryKey", "legacyInventoryRecordIndex", "legacyInventoryInspectBtn", "legacyInventoryDeletePlanBtn"):
        assert f'id="{element_id}"' in html
        assert f"$('#{element_id}')" in js
    assert "/api/legacy-ops/inventory?" in js
    assert 'path == "/api/legacy-ops/inventory"' in py
    assert "INVENTORY_ITEM_DELETE" in workspace
    assert '"INVENTORY_ITEM_DELETE": {"required_confirmation": "DELETE INVENTORY ITEM"' in store
    assert 'elif op == "INVENTORY_ITEM_DELETE"' in apply_py
    assert "não editar Code/Head/CheckSum arbitrariamente" in html


def test_userdata_batch_delete_is_explicit_guarded_and_single_rewrite(tmp_path):
    from pt_asset_tool.legacy_apps.controller_inventory import (
        BATCH_DELETE_CONFIRM, apply_item_batch_delete, plan_item_batch_delete,
    )
    root = tmp_path / "server"; key = "Hero"
    p = root / "DataServer" / "userdata" / str(legacy_bucket(key)) / f"{key}.dat"
    records = [
        _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, code_off=USER_CODE_OFFSET, seed=i)
        for i in (1, 2, 3, 4)
    ]
    _write_userdata(p, records)
    plan = plan_item_batch_delete(root, store="userdata", key=key, record_indices=[3, 1, 3])
    assert plan["status"] == "READY"
    assert plan["record_indices"] == [1, 3]
    assert len(plan["guards"]) == 2
    assert plan["safety"]["single_rewrite"] is True
    assert plan["safety"]["native_equivalence"].startswith("ControllerUser AllDelete")
    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        apply_item_batch_delete(plan, confirmation="wrong", backup_root=tmp_path / "backup")
    result = apply_item_batch_delete(plan, confirmation=BATCH_DELETE_CONFIRM, backup_root=tmp_path / "backup")
    assert result["deleted_count"] == 2
    state = inspect_fixed_inventory(p, store="userdata")
    assert state["records"][0]["sha256"] == hashlib.sha256(records[0]).hexdigest()
    assert state["records"][1]["empty"] is True
    assert state["records"][2]["sha256"] == hashlib.sha256(records[2]).hexdigest()
    assert state["records"][3]["empty"] is True


def test_batch_delete_blocks_empty_and_out_of_range_before_write(tmp_path):
    from pt_asset_tool.legacy_apps.controller_inventory import plan_item_batch_delete
    root = tmp_path / "server"; key = "Account"
    p = root / "DataServer" / "warehouse" / str(legacy_bucket(key)) / f"{key}.war"
    records = [bytes(WAREHOUSE_RECORD_SIZE) for _ in range(WAREHOUSE_RECORD_COUNT)]
    records[2] = _record(WAREHOUSE_RECORD_SIZE, head_off=WAREHOUSE_HEAD_OFFSET, checksum_off=WAREHOUSE_CHECKSUM_OFFSET, code_off=WAREHOUSE_CODE_OFFSET, seed=9)
    _write_warehouse(p, records)
    blocked = plan_item_batch_delete(root, store="warehouse", key=key, record_indices=[2, 3])
    assert blocked["status"] == "BLOCKED" and blocked["reason"] == "RECORD_ALREADY_EMPTY"
    blocked = plan_item_batch_delete(root, store="warehouse", key=key, record_indices=[100])
    assert blocked["status"] == "BLOCKED" and blocked["reason"] == "RECORD_INDEX_OUT_OF_RANGE"


def test_inventory_batch_delete_is_wired_to_workspace_plan_store_and_ui():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    workspace = (root / "pt_asset_tool/legacy_apps/workspace.py").read_text(encoding="utf-8")
    store = (root / "pt_asset_tool/legacy_apps/plan_store.py").read_text(encoding="utf-8")
    apply_py = (root / "pt_asset_tool/legacy_apps/apply.py").read_text(encoding="utf-8")
    assert 'id="legacyInventoryBatchIndices"' in html
    assert 'id="legacyInventoryBatchDeletePlanBtn"' in html
    assert "$('#legacyInventoryBatchDeletePlanBtn')" in js
    assert "INVENTORY_ITEM_BATCH_DELETE" in workspace
    assert '"INVENTORY_ITEM_BATCH_DELETE": {"required_confirmation": "DELETE INVENTORY ITEMS"' in store
    assert 'elif op == "INVENTORY_ITEM_BATCH_DELETE"' in apply_py



def test_scope_clear_userdata_plans_all_files_backs_up_then_clears(tmp_path):
    from pt_asset_tool.legacy_apps.controller_inventory import (
        SCOPE_CLEAR_CONFIRM, apply_inventory_scope_clear, plan_inventory_scope_clear,
    )
    root = tmp_path / "server"
    originals = {}
    for key, seed in (("HeroA", 10), ("HeroB", 20)):
        path = root / "DataServer" / "userdata" / str(legacy_bucket(key)) / f"{key}.dat"
        records = [
            _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, code_off=USER_CODE_OFFSET, seed=seed),
            bytes(USER_ITEM_STRUCT_SIZE),
        ]
        originals[path] = _write_userdata(path, records)
    plan = plan_inventory_scope_clear(root, store="userdata")
    assert plan["status"] == "READY"
    assert plan["target_count"] == 2
    assert plan["nonempty_item_count"] == 2
    assert plan["required_confirmation"] == "CLEAR ALL USERDATA ITEMS"
    assert all("new_bytes" not in t for t in plan["targets"])

    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        apply_inventory_scope_clear(plan, confirmation="wrong", backup_root=tmp_path / "backups")
    for path, raw in originals.items():
        assert path.read_bytes() == raw

    result = apply_inventory_scope_clear(
        plan,
        confirmation=SCOPE_CLEAR_CONFIRM["userdata"],
        backup_root=tmp_path / "backups",
    )
    assert result["status"] == "PASS"
    assert result["deleted_item_count"] == 2
    for path, raw in originals.items():
        state = inspect_fixed_inventory(path, store="userdata")
        assert state["nonempty_count"] == 0
        rel = path.relative_to(root)
        backup = Path(result["backup_root"]) / rel
        assert backup.read_bytes() == raw


def test_scope_clear_warehouse_preserves_headers_and_global_preflight_prevents_partial_write(tmp_path):
    from pt_asset_tool.legacy_apps.controller_inventory import (
        SCOPE_CLEAR_CONFIRM, apply_inventory_scope_clear, plan_inventory_scope_clear,
    )
    root = tmp_path / "server"
    paths = []
    for key, slot, seed in (("AccA", 2, 31), ("AccB", 7, 32)):
        path = root / "DataServer" / "warehouse" / str(legacy_bucket(key)) / f"{key}.war"
        records = [bytes(WAREHOUSE_RECORD_SIZE) for _ in range(WAREHOUSE_RECORD_COUNT)]
        records[slot] = _record(WAREHOUSE_RECORD_SIZE, head_off=WAREHOUSE_HEAD_OFFSET, checksum_off=WAREHOUSE_CHECKSUM_OFFSET, code_off=WAREHOUSE_CODE_OFFSET, seed=seed)
        original = _write_warehouse(path, records)
        paths.append((path, original))
    plan = plan_inventory_scope_clear(root, store="warehouse")
    assert plan["status"] == "READY" and plan["target_count"] == 2

    # Drift only the second file. Global preflight must stop before the first write.
    second, raw_second = paths[1]
    drift = bytearray(raw_second); drift[0] ^= 1; second.write_bytes(drift)
    first_before = paths[0][0].read_bytes()
    with pytest.raises(ValueError, match="SOURCE_DRIFTED"):
        apply_inventory_scope_clear(
            plan,
            confirmation=SCOPE_CLEAR_CONFIRM["warehouse"],
            backup_root=tmp_path / "backups",
        )
    assert paths[0][0].read_bytes() == first_before

    # Restore and apply the reviewed plan. Headers must survive byte-for-byte.
    second.write_bytes(raw_second)
    result = apply_inventory_scope_clear(
        plan,
        confirmation=SCOPE_CLEAR_CONFIRM["warehouse"],
        backup_root=tmp_path / "backups2",
    )
    assert result["deleted_item_count"] == 2
    for path, original in paths:
        assert path.read_bytes()[:WAREHOUSE_HEADER_SIZE] == original[:WAREHOUSE_HEADER_SIZE]
        assert inspect_fixed_inventory(path, store="warehouse")["nonempty_count"] == 0


def test_scope_clear_rolls_back_already_written_targets_on_late_failure(tmp_path, monkeypatch):
    import pt_asset_tool.legacy_apps.controller_inventory as ci
    root = tmp_path / "server"
    originals = {}
    for key, seed in (("HeroA", 41), ("HeroB", 42)):
        path = root / "DataServer" / "userdata" / str(legacy_bucket(key)) / f"{key}.dat"
        originals[path] = _write_userdata(path, [
            _record(USER_ITEM_STRUCT_SIZE, head_off=USER_HEAD_OFFSET, checksum_off=USER_CHECKSUM_OFFSET, code_off=USER_CODE_OFFSET, seed=seed)
        ])
    plan = ci.plan_inventory_scope_clear(root, store="userdata")
    real_atomic = ci.atomic_write_bytes
    calls = {"n": 0}

    def fail_second(path, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("synthetic second-write failure")
        return real_atomic(path, data)

    monkeypatch.setattr(ci, "atomic_write_bytes", fail_second)
    with pytest.raises(OSError, match="synthetic"):
        ci.apply_inventory_scope_clear(
            plan,
            confirmation=ci.SCOPE_CLEAR_CONFIRM["userdata"],
            backup_root=tmp_path / "backups",
        )
    for path, raw in originals.items():
        assert path.read_bytes() == raw


def test_inventory_scope_clear_is_wired_and_explicitly_labeled_destructive():
    root = Path(__file__).resolve().parents[1]
    html = (root / "pt_asset_tool/ui_static/index.html").read_text(encoding="utf-8")
    js = (root / "pt_asset_tool/ui_static/app.js").read_text(encoding="utf-8")
    workspace = (root / "pt_asset_tool/legacy_apps/workspace.py").read_text(encoding="utf-8")
    store = (root / "pt_asset_tool/legacy_apps/plan_store.py").read_text(encoding="utf-8")
    apply_py = (root / "pt_asset_tool/legacy_apps/apply.py").read_text(encoding="utf-8")
    assert "Operações destrutivas globais" in html
    assert "não são limpeza de cache" in html.lower()
    for element_id in ("legacyInventoryClearUserdataPlanBtn", "legacyInventoryClearWarehousePlanBtn"):
        assert f'id="{element_id}"' in html
        assert f"$('#{element_id}')" in js
    assert "INVENTORY_SCOPE_CLEAR" in workspace
    assert '"INVENTORY_SCOPE_CLEAR": {"required_confirmation": None, "apply_supported": True}' in store
    assert 'elif op == "INVENTORY_SCOPE_CLEAR"' in apply_py
    assert "CLEAR ALL USERDATA ITEMS" in (root / "pt_asset_tool/legacy_apps/controller_inventory.py").read_text(encoding="utf-8")
    assert "CLEAR ALL WAREHOUSE ITEMS" in (root / "pt_asset_tool/legacy_apps/controller_inventory.py").read_text(encoding="utf-8")
