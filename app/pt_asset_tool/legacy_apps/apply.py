from __future__ import annotations

from pathlib import Path
from typing import Any

from .plan_store import load_plan
from .common import legacy_build_root
from .userdata_admin import (
    apply_character_fields_update, apply_character_expert_fields_update, apply_level_edit,
    apply_character_rename, apply_account_rename, apply_account_graph_copy,
)
from .item_distributor import apply_distribution
from .controller_inventory import apply_item_delete, apply_item_batch_delete, apply_inventory_scope_clear
from .protector import apply_account_block_sqlite
from .sod_manager import SQLiteSodDataSource, apply_sod_updates
from .server_admin import mark_bprank_processed, apply_hotuk_updates

FORMAT = "PT_LEGACY_APPS_APPLY_V1"


def apply_saved_plan(project_root: Path, server_root: Path, plan_id: str, confirmation: str) -> dict[str, Any]:
    loaded = load_plan(project_root, plan_id)
    plan = loaded["plan"]
    op = str(loaded.get("operation_request") or "").upper()
    backup_root = legacy_build_root(project_root) / "legacy_apps" / "backups" / plan_id
    backup_root.mkdir(parents=True, exist_ok=True)

    # All filesystem plans were created for a concrete server root/path.  Do not
    # let a UI root switch redirect a reviewed plan to another server.
    expected_root = plan.get("server_root")
    if expected_root and Path(str(expected_root)).resolve() != Path(server_root).resolve():
        raise ValueError("LEGACY_PLAN_SERVER_ROOT_CHANGED")

    if op == "CHARACTER_LEVEL":
        result = apply_level_edit(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "CHARACTER_FIELDS":
        result = apply_character_fields_update(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "CHARACTER_EXPERT_FIELDS":
        result = apply_character_expert_fields_update(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "CHARACTER_RENAME":
        result = apply_character_rename(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "ACCOUNT_RENAME":
        result = apply_account_rename(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "ACCOUNT_GRAPH_COPY":
        result = apply_account_graph_copy(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "ITEM_DISTRIBUTE":
        result = apply_distribution(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "INVENTORY_ITEM_DELETE":
        result = apply_item_delete(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "INVENTORY_ITEM_BATCH_DELETE":
        result = apply_item_batch_delete(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "INVENTORY_SCOPE_CLEAR":
        result = apply_inventory_scope_clear(plan, confirmation=confirmation, backup_root=backup_root)
    elif op == "ACCOUNT_BLOCK":
        db_path = Path(str(plan.get("db_path") or ""))
        if not db_path.is_file():
            raise FileNotFoundError(f"SQLITE_DATABASE_NOT_FOUND:{db_path}")
        result = apply_account_block_sqlite(plan, db_path=db_path, confirmation=confirmation)
    elif op == "SOD_UPDATE":
        if confirmation != "APPLY SOD CLAN UPDATE":
            raise ValueError("CONFIRMATION_REQUIRED:APPLY SOD CLAN UPDATE")
        db_path = Path(str(plan.get("db_path") or ""))
        if not db_path.is_file():
            raise FileNotFoundError(f"SQLITE_DATABASE_NOT_FOUND:{db_path}")
        with SQLiteSodDataSource(db_path) as source:
            result = apply_sod_updates(source, plan, confirmation=confirmation)
    elif op == "BPRANK_MARK":
        if confirmation != "MARK BPRANK PROCESSED":
            raise ValueError("CONFIRMATION_REQUIRED:MARK BPRANK PROCESSED")
        db_path = Path(str(plan.get("db_path") or ""))
        if not db_path.is_file():
            raise FileNotFoundError(f"SQLITE_DATABASE_NOT_FOUND:{db_path}")
        result = mark_bprank_processed(db_path, str(plan.get("char_name") or ""), table=str(plan.get("table") or "GameRecordBPRank"))
    elif op == "HOTUK_UPDATE":
        result = apply_hotuk_updates(plan, confirmation=confirmation, backup_root=backup_root)
    else:
        raise ValueError(f"LEGACY_PLAN_APPLY_NOT_SUPPORTED:{op}")
    return {
        "format": FORMAT,
        "status": "PASS",
        "plan_id": plan_id,
        "operation_request": op,
        "backup_root": str(backup_root),
        "result": result,
    }
