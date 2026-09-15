from __future__ import annotations

import hashlib
import json
import os
import pathlib
from typing import Any

from .server_lifecycle import (
    ASSET_SHARED_3D,
    ASSET_STATIC,
    CONFIG_REVIEW,
    LOG_FORENSICS_EXCLUDED,
    PERSISTENCE_BLOCKED,
    RUNTIME_INTEGRITY_BLOCKED,
    SECURITY_STATE_BLOCKED,
    classify_server_path,
)

FORMAT = "PT_ASSET_SERVER_ENVIRONMENT_AUTO_V1"


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _first_file(root: pathlib.Path, *, suffixes: set[str] | None = None, direct: bool = False) -> pathlib.Path | None:
    if not root.is_dir():
        return None
    suffixes = {s.casefold() for s in (suffixes or set())}
    try:
        if direct:
            rows = sorted((p for p in root.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
            for p in rows:
                if not suffixes or p.suffix.casefold() in suffixes:
                    return p
            return None
        for base, dirs, files in os.walk(root):
            dirs.sort(key=str.casefold)
            files.sort(key=str.casefold)
            for name in files:
                p = pathlib.Path(base) / name
                if not suffixes or p.suffix.casefold() in suffixes:
                    return p
    except OSError:
        return None
    return None


def _sample(server_root: pathlib.Path, rel_dir: str, suffixes: set[str], label: str, *, direct: bool = False) -> dict[str, Any]:
    base = server_root / pathlib.PurePosixPath(rel_dir)
    p = _first_file(base, suffixes=suffixes, direct=direct)
    if p is None:
        return {"label": label, "status": "NOT_PRESENT", "search_root": str(base)}
    rel = p.relative_to(server_root).as_posix()
    c = classify_server_path(rel)
    payload_read = c.asset_candidate or c.design_visible
    out = {
        "label": label,
        "status": "FOUND",
        "relative_path": rel,
        "path": str(p),
        "size": p.stat().st_size,
        "classification": c.as_dict(),
        "payload_read": bool(payload_read),
    }
    if payload_read:
        out["sha256_before"] = _sha256_file(p)
    return out


def _shared_cross_root_samples(server_root: pathlib.Path, client_root: pathlib.Path, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Prefer char then Field: this mirrors the two server-side 3D loading paths
    # without scanning logs/persistence trees.
    for sub in ("char", "Field"):
        base = server_root / sub
        if not base.is_dir():
            continue
        for walk_base, dirs, files in os.walk(base):
            dirs.sort(key=str.casefold)
            files.sort(key=str.casefold)
            for name in files:
                if pathlib.PurePosixPath(name).suffix.casefold() not in {".inx", ".smd", ".smb", ".ase"}:
                    continue
                sp = pathlib.Path(walk_base) / name
                rel = sp.relative_to(server_root).as_posix()
                cp = client_root / pathlib.PurePosixPath(rel)
                if not cp.is_file():
                    continue
                s_size = sp.stat().st_size
                c_size = cp.stat().st_size
                row = {
                    "relative_path": rel,
                    "server_size": s_size,
                    "client_size": c_size,
                    "size_equal": s_size == c_size,
                }
                if s_size == c_size:
                    s_hash = _sha256_file(sp)
                    c_hash = _sha256_file(cp)
                    row.update({"server_sha256": s_hash, "client_sha256": c_hash, "byte_identical": s_hash == c_hash})
                else:
                    row["byte_identical"] = False
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def run_server_environment_validation(settings, *, server_root: str | pathlib.Path | None = None) -> dict[str, Any]:
    project_root = pathlib.Path(settings.project_root).resolve()
    client_root = pathlib.Path(settings.client_root).resolve()
    raw_server = server_root if server_root is not None else getattr(settings, "server_root", None)
    server = pathlib.Path(raw_server).expanduser().resolve() if raw_server else None
    report_dir = project_root / "pt_build" / "devtest" / "server_environment_auto"
    report_path = report_dir / "result.json"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None, *, required: bool = True, status: str | None = None):
        checks.append({"name": name, "status": status or ("PASS" if ok else "FAIL"), "required": bool(required), "detail": detail})

    add("server_root_configured", server is not None, str(server) if server else None)
    exists = bool(server and server.is_dir())
    add("server_root_exists", exists, str(server) if server else None)
    readable = bool(exists and os.access(server, os.R_OK | os.X_OK))
    add("server_root_readable", readable, str(server) if server else None)
    add("utf8_server_path_roundtrip", bool(server and str(server).encode("utf-8").decode("utf-8") == str(server)), str(server) if server else None)

    isolated = bool(server and not _within(report_dir, server) and not _within(report_dir, client_root))
    add("pt_build_isolated_from_server_and_client", isolated, {"report_dir": str(report_dir), "server_root": str(server) if server else None, "client_root": str(client_root)})

    core_roots = {}
    if server:
        for rel in ("GameServer", "char", "Field", "Configs", "DataServer", "PostBox", "LogItemData", "FuncBox"):
            core_roots[rel] = (server / rel).is_dir()
    add("server_core_asset_root", bool(core_roots.get("GameServer")), core_roots)

    samples: list[dict[str, Any]] = []
    if exists and server is not None:
        specs = [
            ("GameServer/monster", {".inf"}, "MONSTER_INF", False),
            ("GameServer/npc", {".npc"}, "NPC_DEF", False),
            ("GameServer/OpenItem", {".txt"}, "OPENITEM", False),
            ("GameServer/Field", {".spm"}, "FIELD_SPM", False),
            ("GameServer/Field", {".spp"}, "FIELD_SPP", False),
            ("GameServer/Field", {".spc"}, "FIELD_SPC", False),
            ("char", {".inx"}, "SERVER_INX", False),
            ("char", {".smd"}, "SERVER_MODEL_SMD", False),
            ("char", {".smb"}, "SERVER_SMB", False),
            ("Field", {".smd", ".ase"}, "SERVER_FIELD_3D", False),
            ("LogItemData", {".itm"}, "LOGITEMDATA_ITM", True),
        ]
        samples = [_sample(server, spec[0], spec[1], spec[2], direct=spec[3]) for spec in specs]

    static_found = any((r.get("classification") or {}).get("lifecycle") == ASSET_STATIC for r in samples)
    shared3d_found = any((r.get("classification") or {}).get("lifecycle") == ASSET_SHARED_3D for r in samples)
    add("server_static_gameplay_sample", static_found, [r for r in samples if r.get("label") in {"MONSTER_INF", "NPC_DEF", "OPENITEM", "FIELD_SPM"}])
    add("server_shared_3d_sample", shared3d_found, [r for r in samples if r.get("label") in {"SERVER_INX", "SERVER_MODEL_SMD", "SERVER_SMB", "SERVER_FIELD_3D"}])

    itm = next((r for r in samples if r.get("label") == "LOGITEMDATA_ITM"), None)
    itm_class = ((itm or {}).get("classification") or {}).get("lifecycle")
    if itm and itm.get("status") == "FOUND":
        add("logitemdata_is_not_asset", itm_class == LOG_FORENSICS_EXCLUDED, itm)
    else:
        add("logitemdata_is_not_asset", True, itm, required=False, status="NOT_PRESENT")

    # Assert the design policy itself, independent of physical presence.
    policy_cases = {
        "DataServer/account.dat": PERSISTENCE_BLOCKED,
        "PostBox/00/account.dat": PERSISTENCE_BLOCKED,
        "LogItemData/1@2.itm": LOG_FORENSICS_EXCLUDED,
        "BlackUser/1.bur": SECURITY_STATE_BLOCKED,
        "FuncBox/123.dat": RUNTIME_INTEGRITY_BLOCKED,
        "Configs/hotuk.ini": CONFIG_REVIEW,
        "char/monster/Foo/Foo.smd": ASSET_SHARED_3D,
        "GameServer/monster/Foo.inf": ASSET_STATIC,
    }
    policy_rows = []
    policy_ok = True
    for rel, expected in policy_cases.items():
        actual = classify_server_path(rel).lifecycle
        ok = actual == expected
        policy_ok &= ok
        policy_rows.append({"path": rel, "expected": expected, "actual": actual, "status": "PASS" if ok else "FAIL"})
    add("server_lifecycle_policy", policy_ok, policy_rows)

    shared = _shared_cross_root_samples(server, client_root) if server and client_root.is_dir() else []
    add("client_server_shared_path_samples", True, {"count": len(shared), "samples": shared}, required=False, status="PASS" if shared else "NOT_OBSERVED")

    # Read-only witness: the exact sampled server bytes must remain unchanged.
    changed = []
    for row in samples:
        if row.get("status") != "FOUND" or not row.get("sha256_before"):
            continue
        p = pathlib.Path(row["path"])
        after = _sha256_file(p) if p.is_file() else None
        if after != row["sha256_before"]:
            changed.append({"path": str(p), "before": row["sha256_before"], "after": after})
    add("server_samples_unchanged", not changed, {"checked": sum(1 for r in samples if r.get("status") == "FOUND"), "changed": changed})

    required_failures = [c for c in checks if c.get("required") and c.get("status") != "PASS"]
    status = "PASS" if not required_failures else "FAIL"
    result = {
        "format": FORMAT,
        "status": status,
        "server_environment_ready": status == "PASS",
        "project_root": str(project_root),
        "client_root": str(client_root),
        "server_root": str(server) if server else None,
        "checks": checks,
        "samples": samples,
        "client_server_shared_samples": shared,
        "required_failure_count": len(required_failures),
        "required_failures": [c["name"] for c in required_failures],
        "server_write_authorized": False,
        "persistence_write_authorized": False,
        "client_write_authorized": False,
        "server_modified": bool(changed),
        "policy": {
            "server_source_write_attempted": False,
            "temporary_writes_only_under_pt_build": True,
            "persistence_and_logs_excluded_from_asset_catalog": True,
            "shared_3d_requires_pt_asset_pipeline": True,
            "configs_require_review": True,
        },
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
