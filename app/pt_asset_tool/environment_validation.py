from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

from .semantic_census import CERTIFIED_WRITERS

FORMAT = "PT_ASSET_ENVIRONMENT_AUTO_V1"
MIN_FREE_BYTES = 512 * 1024 * 1024
WARN_FREE_BYTES = 2 * 1024 * 1024 * 1024


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


def _smallest_record(registry, *, kind: str | None = None, extension: str | None = None) -> dict[str, Any] | None:
    rows = []
    for row in registry.records:
        if kind is not None and str(row.get("kind") or "") != kind:
            continue
        if extension is not None and str(row.get("extension") or "").casefold() != extension.casefold():
            continue
        rel = str(row.get("relative_path") or "")
        if not rel:
            continue
        try:
            size = int(row.get("size") or 0)
        except Exception:
            size = 0
        rows.append((size if size > 0 else 2**63 - 1, rel.casefold(), row))
    return min(rows, default=(0, "", None))[2]


def _select_physical_samples(settings, registry) -> list[dict[str, Any]]:
    specs = [
        ("MODEL062", "SMD_MODEL_062", None),
        ("STAGE072", "SMD_STAGE_072", None),
        ("INX", None, ".inx"),
        ("SMB", None, ".smb"),
        ("BMP", None, ".bmp"),
        ("TGA", None, ".tga"),
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, kind, ext in specs:
        row = _smallest_record(registry, kind=kind, extension=ext)
        if not row:
            out.append({"label": label, "status": "MISSING_IN_INVENTORY"})
            continue
        rel = str(row.get("relative_path") or "").replace("\\", "/")
        key = rel.casefold()
        if key in seen:
            continue
        seen.add(key)
        path = settings.client_root / pathlib.PurePosixPath(rel)
        out.append({
            "label": label,
            "relative_path": rel,
            "path": str(path),
            "inventory_size": int(row.get("size") or 0),
            "kind": row.get("kind"),
        })
    return out


def _blender_probe(settings, probe_path: pathlib.Path, client_sample: pathlib.Path, *, timeout_seconds: float) -> dict[str, Any]:
    command = list(settings.blender_command())
    expr = (
        "import bpy,hashlib,json,pathlib;"
        f"p=pathlib.Path({str(probe_path)!r});"
        f"c=pathlib.Path({str(client_sample)!r});"
        "d={'blender_version':bpy.app.version_string,"
        "'probe_exists':p.is_file(),'client_exists':c.is_file(),"
        "'probe_sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None,"
        "'client_sha256':hashlib.sha256(c.read_bytes()).hexdigest() if c.is_file() else None};"
        "print('PT_ENV_PROBE='+json.dumps(d,sort_keys=True))"
    )
    full = command + ["--background", "--factory-startup", "--python-expr", expr]
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=float(timeout_seconds), check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAIL",
            "error": f"BLENDER_TIMEOUT:{float(timeout_seconds):g}s",
            "command": command,
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }
    except OSError as exc:
        return {
            "status": "FAIL",
            "error": f"BLENDER_LAUNCH:{type(exc).__name__}:{exc}",
            "command": command,
            "stdout_tail": "",
            "stderr_tail": "",
        }
    payload = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("PT_ENV_PROBE="):
            try:
                payload = json.loads(line.split("=", 1)[1])
            except Exception:
                payload = None
    return {
        "status": "PASS" if proc.returncode == 0 and isinstance(payload, dict) else "FAIL",
        "returncode": proc.returncode,
        "command": command,
        "payload": payload,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-4000:],
    }


def run_environment_validation(settings, registry, resolver=None, *, blender_timeout_seconds: float = 60.0) -> dict[str, Any]:
    project_root = pathlib.Path(settings.project_root).resolve()
    client_root = pathlib.Path(settings.client_root).resolve()
    report_dir = project_root / "pt_build" / "devtest" / "environment_auto"
    report_path = report_dir / "result.json"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None, *, required: bool = True, status: str | None = None):
        st = status or ("PASS" if ok else "FAIL")
        checks.append({"name": name, "status": st, "required": bool(required), "detail": detail})

    add("project_root_exists", project_root.is_dir(), str(project_root))
    add("client_root_exists", client_root.is_dir(), str(client_root))
    add("client_root_readable", client_root.is_dir() and os.access(client_root, os.R_OK | os.X_OK), str(client_root))
    add("inventory_exists", pathlib.Path(settings.inventory).is_file(), str(settings.inventory))
    add("pairing_exists", pathlib.Path(settings.pairing).is_file(), str(settings.pairing))
    add("registry_loaded", bool(getattr(registry, "records", [])), {"records": len(getattr(registry, "records", [])), "assets": len(getattr(registry, "assets", []))})
    add("python_runtime", sys.version_info >= (3, 11), {"version": sys.version.split()[0], "executable": sys.executable})
    add("utf8_path_roundtrip", str(client_root).encode("utf-8").decode("utf-8") == str(client_root), str(client_root))

    work_safe = _within(report_dir, project_root) and not _within(report_dir, client_root)
    add("pt_build_isolated_from_client", work_safe, {"report_dir": str(report_dir), "client_root": str(client_root)})
    write_probe = report_dir / "ambiente_áé_ espaço.probe"
    probe_bytes = b"PT_ASSET_ENVIRONMENT_PROBE_V1\n"
    work_write_ok = False
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        write_probe.write_bytes(probe_bytes)
        work_write_ok = write_probe.read_bytes() == probe_bytes
    except Exception as exc:
        add("pt_build_writable", False, f"{type(exc).__name__}:{exc}")
    else:
        add("pt_build_writable", work_write_ok, str(write_probe))

    try:
        usage = shutil.disk_usage(report_dir if report_dir.exists() else project_root)
        free = int(usage.free)
        if free < MIN_FREE_BYTES:
            add("pt_build_free_space", False, {"free_bytes": free, "minimum_bytes": MIN_FREE_BYTES})
        elif free < WARN_FREE_BYTES:
            add("pt_build_free_space", True, {"free_bytes": free, "recommended_bytes": WARN_FREE_BYTES}, required=False, status="WARN")
        else:
            add("pt_build_free_space", True, {"free_bytes": free, "recommended_bytes": WARN_FREE_BYTES})
    except Exception as exc:
        add("pt_build_free_space", False, f"{type(exc).__name__}:{exc}")

    writer_rows = []
    writers_ok = True
    for rel, expected in CERTIFIED_WRITERS.items():
        p = project_root / rel
        actual = _sha256_file(p) if p.is_file() else None
        ok = actual == expected
        writers_ok &= ok
        writer_rows.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "status": "PASS" if ok else "FAIL"})
    add("certified_writer_hashes", writers_ok, writer_rows)

    samples = _select_physical_samples(settings, registry)
    sample_hashes_before: dict[str, str] = {}
    physical_ok = True
    for sample in samples:
        rel = sample.get("relative_path")
        if not rel:
            physical_ok = False
            continue
        p = pathlib.Path(sample["path"])
        exists = p.is_file()
        size_ok = exists and (int(sample.get("inventory_size") or 0) <= 0 or p.stat().st_size == int(sample["inventory_size"]))
        sample["exists"] = exists
        sample["physical_size"] = p.stat().st_size if exists else None
        sample["size_matches_inventory"] = bool(size_ok)
        if exists:
            sample["sha256_before"] = _sha256_file(p)
            sample_hashes_before[str(p)] = sample["sha256_before"]
        physical_ok &= bool(exists and size_ok)
    add("physical_inventory_samples", physical_ok, samples)

    blender_result: dict[str, Any] = {"status": "SKIP", "reason": "NO_PROBE_FILE_OR_CLIENT_SAMPLE"}
    client_sample_path = None
    for sample in samples:
        if sample.get("exists") and sample.get("label") in {"MODEL062", "STAGE072"}:
            client_sample_path = pathlib.Path(sample["path"])
            break
    if work_write_ok and client_sample_path is not None:
        blender_result = _blender_probe(settings, write_probe, client_sample_path, timeout_seconds=blender_timeout_seconds)
        payload = blender_result.get("payload") if isinstance(blender_result, dict) else None
        blender_ok = (
            blender_result.get("status") == "PASS"
            and isinstance(payload, dict)
            and payload.get("probe_exists") is True
            and payload.get("client_exists") is True
            and payload.get("probe_sha256") == hashlib.sha256(probe_bytes).hexdigest()
            and payload.get("client_sha256") == sample_hashes_before.get(str(client_sample_path))
        )
        add("blender_headless_filesystem_bridge", blender_ok, blender_result)
    else:
        add("blender_headless_filesystem_bridge", False, blender_result)

    client_unchanged = True
    changed = []
    for raw, before in sample_hashes_before.items():
        p = pathlib.Path(raw)
        after = _sha256_file(p) if p.is_file() else None
        if after != before:
            client_unchanged = False
            changed.append({"path": raw, "before": before, "after": after})
    add("client_samples_unchanged", client_unchanged, {"checked": len(sample_hashes_before), "changed": changed})

    try:
        if write_probe.is_file():
            write_probe.unlink()
        cleanup_ok = not write_probe.exists()
    except Exception as exc:
        cleanup_ok = False
        add("pt_build_probe_cleanup", False, f"{type(exc).__name__}:{exc}")
    else:
        add("pt_build_probe_cleanup", cleanup_ok, str(write_probe))

    required_failures = [c for c in checks if c.get("required") and c.get("status") != "PASS"]
    status = "PASS" if not required_failures else "FAIL"
    result = {
        "format": FORMAT,
        "status": status,
        "environment_ready": status == "PASS",
        "project_root": str(project_root),
        "client_root": str(client_root),
        "checks": checks,
        "required_failure_count": len(required_failures),
        "required_failures": [c["name"] for c in required_failures],
        "blender": blender_result,
        "physical_samples": samples,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": not client_unchanged,
        "policy": {
            "client_source_write_attempted": False,
            "temporary_writes_only_under_pt_build": True,
            "release_1_auto_may_run": status == "PASS",
        },
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
