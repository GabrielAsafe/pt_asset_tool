from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any, Callable

FORMAT_PLAN = "PT_ASSET_ENRICHMENT_VENDOR_PLAN_V1"
FORMAT_GRAPH = "PT_ASSET_ENRICHMENT_VENDOR_GRAPH_V1"


def _vendor_root(project_root: pathlib.Path) -> pathlib.Path:
    vendor_base = pathlib.Path(project_root).resolve().parent / "vendor"
    root = vendor_base / "summit_asset_enrichment_v9"
    if (root / "PACKAGE_MANIFEST.json").is_file():
        return root
    raise FileNotFoundError(f"Active Summit Asset Enrichment v9 vendor not found: {root}")


def _current_config(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
) -> tuple[pathlib.Path, list[dict[str, Any]], list[dict[str, Any]]]:
    project = pathlib.Path(project_root).resolve()
    client = pathlib.Path(client_root).resolve()
    server = pathlib.Path(server_root).resolve()
    vendor = _vendor_root(project)
    raw = json.loads((vendor / "summit_paths.json").read_text(encoding="utf-8"))
    available: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for donor in raw.get("donors") or []:
        if not isinstance(donor, dict):
            continue
        row = dict(donor)
        donor_path = pathlib.Path(str(row.get("root") or "")).expanduser()
        if donor_path.is_dir():
            row["root"] = str(donor_path.resolve())
            available.append(row)
        else:
            missing.append(row)
    config = {
        "target_client": str(client),
        "target_server": str(server),
        "donors": available,
    }
    out_dir = project / "pt_build" / "enrichment_vendor"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = out_dir / "current_paths.json"
    cfg.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg, available, missing


def _run(cmd: list[str], *, timeout: float, progress: Callable[[str], None] | None = None) -> subprocess.CompletedProcess[str]:
    if progress:
        progress("[asset-enrichment] " + " ".join(cmd[:4]) + " ...")
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1.0, float(timeout)),
        check=False,
    )


def generate_migration_plan(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    timeout_seconds: float = 180.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    vendor = _vendor_root(project)
    cfg, available, missing = _current_config(project, client_root, server_root)
    out_dir = project / "pt_build" / "enrichment_vendor"
    manifest = out_dir / "migration_plan.csv"
    cp = _run(
        [sys.executable, str(vendor / "migrate_assets.py"), "--config", str(cfg), "plan", "--out", str(manifest)],
        timeout=timeout_seconds,
        progress=progress,
    )
    summary_path = manifest.with_suffix(".summary.json")
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
        except Exception:
            pass
    status = "PASS" if cp.returncode == 0 and manifest.is_file() else "FAIL"
    report = {
        "format": FORMAT_PLAN,
        "status": status,
        "scope": "PLAN_ONLY_NO_TARGET_WRITE",
        "config": str(cfg),
        "manifest": str(manifest) if manifest.is_file() else None,
        "summary": str(summary_path) if summary_path.is_file() else None,
        "summary_data": summary,
        "available_donor_count": len(available),
        "unavailable_donor_count": len(missing),
        "unavailable_donors": missing,
        "returncode": cp.returncode,
        "stdout_tail": cp.stdout[-12000:],
        "stderr_tail": cp.stderr[-12000:],
        "client_write_authorized": False,
        "server_write_authorized": False,
        "production_authorized": False,
    }
    report_path = out_dir / "migration_plan.result.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_dependency_graph(
    project_root: pathlib.Path,
    client_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    skip_client_scan: bool = False,
    timeout_seconds: float = 240.0,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_root).resolve()
    vendor = _vendor_root(project)
    cfg, available, missing = _current_config(project, client_root, server_root)
    out_dir = project / "pt_build" / "enrichment_vendor" / "dependency_graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(vendor / "build_dependency_graph.py"), "--config", str(cfg), "--out-dir", str(out_dir)]
    if skip_client_scan:
        cmd.append("--skip-client-scan")
    cp = _run(cmd, timeout=timeout_seconds, progress=progress)
    summary_path = out_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
        except Exception:
            pass
    status = "PASS" if cp.returncode == 0 and summary_path.is_file() else "FAIL"
    report = {
        "format": FORMAT_GRAPH,
        "status": status,
        "scope": "READ_ONLY_DEPENDENCY_GRAPH",
        "config": str(cfg),
        "graph_dir": str(out_dir),
        "summary": str(summary_path) if summary_path.is_file() else None,
        "summary_data": summary,
        "skip_client_scan": bool(skip_client_scan),
        "available_donor_count": len(available),
        "unavailable_donor_count": len(missing),
        "unavailable_donors": missing,
        "returncode": cp.returncode,
        "stdout_tail": cp.stdout[-12000:],
        "stderr_tail": cp.stderr[-12000:],
        "client_write_authorized": False,
        "server_write_authorized": False,
        "production_authorized": False,
    }
    report_path = project / "pt_build" / "enrichment_vendor" / "dependency_graph.result.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
