from __future__ import annotations

"""Operator-facing aggregation for the Python ports of historical Management tools.

This module deliberately exposes tasks, not EXE names.  reverse_manifest keeps
provenance, while this surface answers the operator questions: what can I do,
what do I need, what is ready on this server, and what confirmation is required.
"""

from pathlib import Path
from typing import Any
import sqlite3

from .reverse_manifest import reverse_status
from .server_admin import (
    local_runtime_policy, parse_restarter_config, restarter_launch_plan, bprank_sqlite_plan,
    plan_hotuk_updates,
)
from .sod_manager import SQLiteSodDataSource, plan_sod_updates
from .userdata_admin import (
    character_edit_capabilities, expert_character_edit_capabilities,
    controlleruser_reverse_artifacts,
    discover_xp_tables,
    inspect_character_info,
    inspect_account,
    level_edit_capability,
    plan_level_edit,
    plan_character_fields_update, plan_character_expert_fields_update,
    plan_character_rename,
    plan_account_rename, plan_account_graph_copy,
)
from .item_distributor import read_queue, plan_distribution, SPEC_NAMES
from .item_finder import scan_dataserver
from .controller_inventory import (
    inspect_fixed_inventory, plan_item_delete, plan_item_batch_delete,
    plan_inventory_scope_clear,
)
from .protector import load_rule_directory, analyze_log_lines, plan_account_block_sqlite

FORMAT = "PT_LEGACY_APPS_OPERATOR_WORKSPACE_V1"


def _find_existing(root: Path, *candidates: str) -> Path | None:
    for rel in candidates:
        p = root / rel
        if p.is_file():
            return p
    return None


def _sqlite_tables(path: Path) -> dict[str, list[str]]:
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
            names = [str(r[0]) for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            out: dict[str, list[str]] = {}
            for name in names:
                if not name or name.startswith("sqlite_"):
                    continue
                safe = name.replace('"', '""')
                try:
                    out[name] = [str(r[1]) for r in db.execute(f'PRAGMA table_info("{safe}")')]
                except sqlite3.Error:
                    out[name] = []
            return out
    except sqlite3.Error:
        return {}


def _database_status(server_root: Path) -> dict[str, Any]:
    root = Path(server_root).resolve()
    preferred = [
        root / "Database" / "summit.sqlite3",
        root / "database" / "summit.sqlite3",
        root / "summit.sqlite3",
    ]
    discovered: list[Path] = []
    seen: set[Path] = set()
    for p in preferred:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp); discovered.append(rp)
    for base in (root / "Database", root / "database", root):
        if not base.is_dir():
            continue
        try:
            rows = list(base.glob("*.sqlite3")) + list(base.glob("*.sqlite")) + list(base.glob("*.db"))
        except OSError:
            rows = []
        for p in rows:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp); discovered.append(rp)

    expected = {"RunLog", "UL", "CL", "GameRecordBPRank", "GameUser", "UserInfo"}
    candidates: list[dict[str, Any]] = []
    for p in discovered:
        if not p.is_file():
            continue
        tables = _sqlite_tables(p)
        matched = sorted(expected.intersection(tables))
        score = len(matched)
        candidates.append({
            "path": str(p),
            "tables": sorted(tables),
            "matched_tables": matched,
            "score": score,
            "capabilities": {
                "sod": all(x in tables for x in ("RunLog", "UL", "CL")),
                "bprank": "GameRecordBPRank" in tables,
                "account_block": "GameUser" in tables or "UserInfo" in tables,
            },
        })
    candidates.sort(key=lambda x: (-int(x["score"]), 0 if Path(x["path"]).name == "summit.sqlite3" else 1, x["path"].casefold()))
    selected = candidates[0] if candidates else None
    fallback = preferred[0]
    return {
        "backend": "SQLite",
        "network": "localhost",
        "path": str(selected["path"] if selected else fallback),
        "exists": bool(selected),
        "tables": list(selected.get("tables") or []) if selected else [],
        "capabilities": dict(selected.get("capabilities") or {}) if selected else {"sod": False, "bprank": False, "account_block": False},
        "candidates": candidates,
        "selection_basis": "SCHEMA_MATCH" if selected and selected.get("score") else ("FIRST_SQLITE_CANDIDATE" if selected else "DEFAULT_NOT_FOUND"),
        "required_for": ["SoD", "BPRank", "account protection/blocking"],
    }


def workspace_status(project_root: Path, server_root: Path | None) -> dict[str, Any]:
    reverse = reverse_status()
    if server_root is None:
        return {
            "format": FORMAT,
            "status": "BLOCKED",
            "reason": "SERVER_ROOT_NOT_CONFIGURED",
            "runtime": local_runtime_policy(),
            "reverse": reverse,
            "tasks": [],
        }
    root = Path(server_root).expanduser().resolve()
    data = root / "DataServer"
    userdata = data / "userdata"
    userinfo = data / "userinfo"
    warehouse = data / "warehouse"
    postbox = root / "Postbox"
    db = _database_status(root)
    xp = discover_xp_tables(root, root.parent)
    restarter_cfg = _find_existing(root, "ConfigRestarter.ini", "configrestarter.ini")
    hotuk = _find_existing(root, "hotuk.ini", "Hotuk.ini", "GameServer/hotuk.ini")
    rules = next((p for p in (root / "PTProtector", root / "PTprotector", root) if p.is_dir()), root)

    def req(label: str, ready: bool, detail: str) -> dict[str, Any]:
        return {"label": label, "ready": bool(ready), "detail": detail}

    tasks = [
        {
            "id": "character_account",
            "title": "Character / Account",
            "status": "READY" if userdata.is_dir() and userinfo.is_dir() else "BLOCKED",
            "summary": "Inspect character/account, edit primary stats and Level/XP, rename, and migrate/restore the account graph with backup.",
            "requirements": [
                req("DataServer/userdata", userdata.is_dir(), str(userdata)),
                req("DataServer/userinfo", userinfo.is_dir(), str(userinfo)),
                req("Monotonic XP table", bool(xp.get("recommended_path")), str(xp.get("recommended_path") or "not found")),
            ],
            "capabilities": character_edit_capabilities(),
            "expert_capabilities": expert_character_edit_capabilities(),
            "confirmations": {
                "fields": "APPLY CHARACTER FIELDS",
                "expert_fields": "APPLY EXPERT CHARACTER FIELDS",
                "level": "APPLY CHARACTER LEVEL",
                "rename_character": "APPLY CHARACTER RENAME",
                "rename_account": "APPLY ACCOUNT RENAME",
                "copy_account_graph": "COPY ACCOUNT GRAPH",
            },
        },
        {
            "id": "items_postbox",
            "title": "Items / Postbox",
            "status": "READY" if userdata.is_dir() else "BLOCKED",
            "summary": "Distribute items through Postbox, locate duplicates, and safely manage deletion of slots proven by ControllerUser.",
            "requirements": [
                req("DataServer/userdata", userdata.is_dir(), str(userdata)),
                req("Postbox", postbox.is_dir(), f"{postbox} (created on demand by the writer)"),
                req("DataServer/warehouse", warehouse.is_dir(), str(warehouse)),
            ],
            "spec_names": list(SPEC_NAMES),
            "confirmations": {"distribute": "APPLY ITEM DISTRIBUTION", "inventory_delete": "DELETE INVENTORY ITEM"},
            "inventory_write_scope": "DELETE_SELECTED_RECORD_ONLY",
        },
        {
            "id": "admin_local",
            "title": "Admin local",
            "status": "READY" if db["exists"] else "REVIEW",
            "summary": "SoD, BPRank, account protection, and server supervisor on localhost + SQLite.",
            "requirements": [
                req("SQLite local", bool(db["exists"]), f"{db['path']} · {db.get('selection_basis')}") ,
                req("ConfigRestarter.ini", bool(restarter_cfg), str(restarter_cfg or "optional / not found")),
                req("hotuk.ini", bool(hotuk), str(hotuk or "optional / not found")),
            ],
            "database": db,
            "restarter_config": str(restarter_cfg) if restarter_cfg else None,
            "hotuk_path": str(hotuk) if hotuk else None,
            "protector_rule_root": str(rules),
            "bprank": bprank_sqlite_plan(),
            "confirmations": {"block_account": "APPLY ACCOUNT BLOCK", "start_server": "START LOCAL SERVER"},
        },
    ]
    return {
        "format": FORMAT,
        "status": "PASS",
        "server_root": str(root),
        "runtime": local_runtime_policy(),
        "database": db,
        "xp_tables": xp,
        "controlleruser_artifacts": controlleruser_reverse_artifacts(),
        "tasks": tasks,
        "reverse": reverse,
        "operator_policy": {
            "exe_names_in_normal_ui": False,
            "legacy_exe_required": False,
            "firewall_or_sqlserver_required": False,
            "writes": "plan + explicit confirmation + backup + drift verification",
        },
    }


def inspect_character(server_root: Path, character: str) -> dict[str, Any]:
    base = inspect_character_info(server_root, character)
    base["level_capability"] = level_edit_capability(server_root, character)
    return base


def inspect_account_task(server_root: Path, account: str) -> dict[str, Any]:
    return inspect_account(server_root, account)


def queue_status(server_root: Path, account: str) -> dict[str, Any]:
    return read_queue(server_root, account)


def item_scan(server_root: Path, *, query: str = "", include_warehouse: bool = True) -> dict[str, Any]:
    return scan_dataserver(server_root, query=query, include_warehouse=include_warehouse)


def inventory_status(server_root: Path, *, store: str, key: str) -> dict[str, Any]:
    kind = str(store).lower()
    suffix = ".dat" if kind == "userdata" else ".war" if kind == "warehouse" else None
    if suffix is None:
        raise ValueError(f"STORE_INVALID:{store}")
    from .common import dataserver_path
    path = dataserver_path(Path(server_root).resolve(), kind, str(key), suffix)
    if not path.is_file():
        return {"format": FORMAT, "status": "BLOCKED", "reason": "STORE_FILE_NOT_FOUND", "store": kind, "key": str(key), "path": str(path)}
    return inspect_fixed_inventory(path, store=kind)


def admin_status(server_root: Path) -> dict[str, Any]:
    root = Path(server_root).resolve()
    db = _database_status(root)
    cfg = _find_existing(root, "ConfigRestarter.ini", "configrestarter.ini")
    launch = None
    if cfg:
        try:
            launch = restarter_launch_plan(cfg, server_root=root)
        except Exception as exc:
            launch = {"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
    rules = next((p for p in (root / "PTProtector", root / "PTprotector", root) if p.is_dir()), root)
    return {
        "format": FORMAT,
        "status": "PASS",
        "runtime": local_runtime_policy(),
        "database": db,
        "restarter": launch,
        "protector_rules": load_rule_directory(rules),
    }


def plan_operation(server_root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(server_root).resolve()
    op = str(operation or "").upper()

    def required(value: Any, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(code)
        return text
    if op == "CHARACTER_LEVEL":
        xp = payload.get("xp_table")
        return plan_level_edit(root, required(payload.get("character"), "CHARACTER_REQUIRED"), int(payload.get("level")), xphen_path=Path(xp) if xp else None)
    if op == "CHARACTER_FIELDS":
        updates = payload.get("updates") or {}
        if not isinstance(updates, dict):
            raise ValueError("CHARACTER_UPDATES_OBJECT_REQUIRED")
        return plan_character_fields_update(root, required(payload.get("character"), "CHARACTER_REQUIRED"), updates)
    if op == "CHARACTER_EXPERT_FIELDS":
        updates = payload.get("updates") or {}
        if not isinstance(updates, dict):
            raise ValueError("CHARACTER_EXPERT_UPDATES_OBJECT_REQUIRED")
        return plan_character_expert_fields_update(root, required(payload.get("character"), "CHARACTER_REQUIRED"), updates)
    if op == "CHARACTER_RENAME":
        return plan_character_rename(root, required(payload.get("old_name"), "CHARACTER_REQUIRED"), required(payload.get("new_name"), "NEW_CHARACTER_NAME_REQUIRED"))
    if op == "ACCOUNT_RENAME":
        return plan_account_rename(root, required(payload.get("old_account"), "ACCOUNT_REQUIRED"), required(payload.get("new_account"), "NEW_ACCOUNT_NAME_REQUIRED"))
    if op == "ACCOUNT_GRAPH_COPY":
        source_root = str(payload.get("source_server_root") or "").strip()
        if not source_root:
            raise ValueError("SOURCE_SERVER_ROOT_REQUIRED")
        return plan_account_graph_copy(
            Path(source_root), root, required(payload.get("account"), "ACCOUNT_REQUIRED"),
            allow_replace=bool(payload.get("allow_replace", False)),
        )
    if op == "ITEM_DISTRIBUTE":
        return plan_distribution(
            root,
            account=required(payload.get("account"), "ACCOUNT_REQUIRED"),
            character=required(payload.get("character"), "CHARACTER_REQUIRED"),
            item_code=required(payload.get("item_code"), "ITEM_CODE_REQUIRED"),
            spec_index=int(payload.get("spec_index") or 0),
            message=str(payload.get("message") or ""),
            quantity=int(payload.get("quantity") or 1),
            mode=str(payload.get("mode") or "append"),
        )
    if op == "INVENTORY_ITEM_DELETE":
        return plan_item_delete(
            root,
            store=str(payload.get("store") or ""),
            key=required(payload.get("key"), "INVENTORY_KEY_REQUIRED"),
            record_index=int(payload.get("record_index")),
        )
    if op == "INVENTORY_ITEM_BATCH_DELETE":
        raw_indices = payload.get("record_indices") or []
        if isinstance(raw_indices, str):
            raw_indices = [x.strip() for x in raw_indices.replace(";", ",").split(",") if x.strip()]
        if not isinstance(raw_indices, (list, tuple)):
            raise ValueError("RECORD_INDICES_LIST_REQUIRED")
        return plan_item_batch_delete(
            root,
            store=str(payload.get("store") or ""),
            key=required(payload.get("key"), "INVENTORY_KEY_REQUIRED"),
            record_indices=[int(x) for x in raw_indices],
        )
    if op == "INVENTORY_SCOPE_CLEAR":
        return plan_inventory_scope_clear(
            root,
            store=str(payload.get("store") or ""),
        )
    if op == "ACCOUNT_BLOCK":
        db = _database_status(root)
        db_path = Path(str(payload.get("db_path") or db["path"])).expanduser().resolve()
        if not db_path.is_file():
            return {"format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_BLOCK_SQLITE", "reason": "SQLITE_DATABASE_NOT_FOUND", "db_path": str(db_path)}
        table = str(payload.get("table") or "GameUser")
        account_column = str(payload.get("account_column") or "userid")
        block_column = str(payload.get("block_column") or "BlockChk")
        reason_column = str(payload.get("reason_column")) if payload.get("reason_column") else None
        tables = _sqlite_tables(db_path)
        actual = next((cols for name, cols in tables.items() if name.casefold() == table.casefold()), None)
        required_cols = [account_column, block_column] + ([reason_column] if reason_column else [])
        if actual is None or any(not any(c.casefold() == wanted.casefold() for c in actual) for wanted in required_cols):
            return {
                "format": FORMAT, "status": "BLOCKED", "operation": "ACCOUNT_BLOCK_SQLITE",
                "reason": "SQLITE_SCHEMA_MISMATCH", "db_path": str(db_path), "table": table,
                "required_columns": required_cols, "available_tables": sorted(tables),
                "available_columns": actual or [],
            }
        plan = plan_account_block_sqlite(
            table=table, account_column=account_column, account=required(payload.get("account"), "ACCOUNT_REQUIRED"),
            block_column=block_column,
            block_value=int(payload.get("block_value") if payload.get("block_value") is not None else 1),
            reason_column=reason_column, reason=str(payload.get("reason")) if payload.get("reason") is not None else None,
        )
        plan["db_path"] = str(db_path)
        plan["schema_verified"] = True
        return plan
    if op == "SOD_UPDATE":
        db = _database_status(root)
        db_path = Path(str(payload.get("db_path") or db["path"]))
        if not db_path.is_file():
            return {"format": FORMAT, "status": "BLOCKED", "operation": "SOD_UPDATE", "reason": "SQLITE_DATABASE_NOT_FOUND", "db_path": str(db_path)}
        table = str(payload.get("table") or "RunLog")
        minimum_players = int(payload.get("minimum_players") or 1)
        with SQLiteSodDataSource(db_path) as source:
            plan = plan_sod_updates(source, table, minimum_players=minimum_players)
        plan["db_path"] = str(db_path)
        plan["operation"] = "SOD_UPDATE"
        return plan
    if op == "BPRANK_MARK":
        db = _database_status(root)
        db_path = Path(str(payload.get("db_path") or db["path"]))
        char_name = str(payload.get("char_name") or "").strip()
        if not char_name:
            raise ValueError("BPRANK_CHARACTER_REQUIRED")
        if not db_path.is_file():
            return {"format": FORMAT, "status": "BLOCKED", "operation": "BPRANK_MARK", "reason": "SQLITE_DATABASE_NOT_FOUND", "db_path": str(db_path)}
        table = str(payload.get("table") or "GameRecordBPRank")
        bprank_sqlite_plan(table=table)  # identifier validation
        tables = _sqlite_tables(db_path)
        actual = next((cols for name, cols in tables.items() if name.casefold() == table.casefold()), None)
        required = ["CharName", "ok"]
        if actual is None or any(not any(c.casefold() == wanted.casefold() for c in actual) for wanted in required):
            return {"format": FORMAT, "status": "BLOCKED", "operation": "BPRANK_MARK", "reason": "SQLITE_SCHEMA_MISMATCH", "db_path": str(db_path), "table": table, "required_columns": required, "available_tables": sorted(tables), "available_columns": actual or []}
        return {"format": FORMAT, "status": "READY", "operation": "BPRANK_MARK", "db_path": str(db_path), "table": table, "char_name": char_name, "schema_verified": True, "write_authorized": False}
    if op == "HOTUK_UPDATE":
        raw_path = str(payload.get("path") or "").strip()
        if not raw_path:
            found = _find_existing(root, "hotuk.ini", "Hotuk.ini", "GameServer/hotuk.ini")
            if not found:
                return {"format": FORMAT, "status": "BLOCKED", "operation": "HOTUK_UPDATE", "reason": "HOTUK_NOT_FOUND"}
            raw_path = str(found)
        updates = payload.get("updates") or {}
        if not isinstance(updates, dict):
            raise ValueError("HOTUK_UPDATES_OBJECT_REQUIRED")
        plan = plan_hotuk_updates(Path(raw_path), {str(k): str(v) for k, v in updates.items()})
        plan["server_root"] = str(root)
        return plan
    if op == "SERVER_LAUNCH":
        cfg = str(payload.get("config_path") or "").strip()
        if not cfg:
            found = _find_existing(root, "ConfigRestarter.ini", "configrestarter.ini")
            if not found:
                return {"format": FORMAT, "status": "BLOCKED", "operation": "SERVER_LAUNCH_PLAN", "reason": "CONFIG_RESTARTER_NOT_FOUND"}
            cfg = str(found)
        return restarter_launch_plan(Path(cfg), server_root=root)
    raise ValueError(f"UNSUPPORTED_LEGACY_OPERATION:{op}")


def analyze_protector_log(server_root: Path, text: str) -> dict[str, Any]:
    root = Path(server_root).resolve()
    rules = next((p for p in (root / "PTProtector", root / "PTprotector", root) if p.is_dir()), root)
    return analyze_log_lines(text.splitlines(), rule_root=rules)


def _public_value(value: Any) -> Any:
    import hashlib
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return {"binary_payload": True, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if isinstance(value, dict):
        return {str(k): _public_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Browser-safe view: retain evidence/diffs but summarize binary payloads."""
    return _public_value(plan)
