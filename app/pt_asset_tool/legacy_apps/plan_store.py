from __future__ import annotations

"""Persist reviewed legacy-operation plans without pickle/code execution."""

from pathlib import Path
from typing import Any
import base64
import hashlib
import json
import secrets

from .common import atomic_write_bytes, sha256_file
from .workspace import public_plan

FORMAT = "PT_LEGACY_APPS_PLAN_STORE_V1"

_OPERATION_META = {
    "CHARACTER_LEVEL": {"required_confirmation": "APPLY CHARACTER LEVEL", "apply_supported": True},
    "CHARACTER_FIELDS": {"required_confirmation": "APPLY CHARACTER FIELDS", "apply_supported": True},
    "CHARACTER_EXPERT_FIELDS": {"required_confirmation": "APPLY EXPERT CHARACTER FIELDS", "apply_supported": True},
    "CHARACTER_RENAME": {"required_confirmation": "APPLY CHARACTER RENAME", "apply_supported": True},
    "ACCOUNT_RENAME": {"required_confirmation": "APPLY ACCOUNT RENAME", "apply_supported": True},
    "ACCOUNT_GRAPH_COPY": {"required_confirmation": "COPY ACCOUNT GRAPH", "apply_supported": True},
    "ITEM_DISTRIBUTE": {"required_confirmation": "APPLY ITEM DISTRIBUTION", "apply_supported": True},
    "INVENTORY_ITEM_DELETE": {"required_confirmation": "DELETE INVENTORY ITEM", "apply_supported": True},
    "INVENTORY_ITEM_BATCH_DELETE": {"required_confirmation": "DELETE INVENTORY ITEMS", "apply_supported": True},
    "INVENTORY_SCOPE_CLEAR": {"required_confirmation": None, "apply_supported": True},
    "ACCOUNT_BLOCK": {"required_confirmation": "APPLY ACCOUNT BLOCK", "apply_supported": True},
    "SOD_UPDATE": {"required_confirmation": "APPLY SOD CLAN UPDATE", "apply_supported": True},
    "BPRANK_MARK": {"required_confirmation": "MARK BPRANK PROCESSED", "apply_supported": True},
    "HOTUK_UPDATE": {"required_confirmation": "APPLY HOTUK CONFIG", "apply_supported": True},
    # Starting Server.exe is intentionally not executed inside the HTTP request.
    # The UI may review this command, while a bounded supervisor/job owns process lifetime.
    "SERVER_LAUNCH": {"required_confirmation": "START LOCAL SERVER", "apply_supported": False},
}


def operation_meta(operation: str, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    op = str(operation or "").upper()
    meta = dict(_OPERATION_META.get(op, {"required_confirmation": None, "apply_supported": False}))
    if op == "INVENTORY_SCOPE_CLEAR" and plan is not None:
        meta["required_confirmation"] = str(plan.get("required_confirmation") or "") or None
    if plan is not None and str(plan.get("status") or "").upper() != "READY":
        meta["apply_supported"] = False
    return meta


def _encode(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, Path):
        return {"__path__": str(value)}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__bytes_b64__"}:
            return base64.b64decode(value["__bytes_b64__"], validate=True)
        if set(value) == {"__path__"}:
            return Path(value["__path__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _root(project_root: Path) -> Path:
    return Path(project_root).resolve() / "app" / "pt_build" / "legacy_apps" / "plans"


def save_plan(project_root: Path, operation: str, plan: dict[str, Any]) -> dict[str, Any]:
    plan_id = secrets.token_hex(12)
    root = _root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": FORMAT,
        "plan_id": plan_id,
        "operation_request": str(operation).upper(),
        "plan": _encode(plan),
    }
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = root / f"{plan_id}.json"
    atomic_write_bytes(path, raw)
    meta = operation_meta(operation, plan)
    return {
        "format": FORMAT,
        "status": "PASS",
        "plan_id": plan_id,
        "operation_request": str(operation).upper(),
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "required_confirmation": meta["required_confirmation"],
        "apply_supported": bool(meta["apply_supported"]),
        "plan": public_plan(plan),
    }


def load_plan(project_root: Path, plan_id: str) -> dict[str, Any]:
    if not plan_id or any(ch not in "0123456789abcdef" for ch in plan_id) or len(plan_id) != 24:
        raise ValueError("INVALID_LEGACY_PLAN_ID")
    path = _root(project_root) / f"{plan_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"LEGACY_PLAN_NOT_FOUND:{plan_id}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("format") != FORMAT or obj.get("plan_id") != plan_id:
        raise ValueError("LEGACY_PLAN_FORMAT_INVALID")
    plan = _decode(obj.get("plan") or {})
    return {
        "format": FORMAT,
        "status": "PASS",
        "plan_id": plan_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "operation_request": obj.get("operation_request"),
        "plan": plan,
        "public_plan": public_plan(plan),
    }
