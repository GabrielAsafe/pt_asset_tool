#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FORMAT = "PT_RC6_6_STATIC_FOCUSED_V1"
EXPECTED_REPRESENTATIVE_COUNT = 13
STATIC_BATCH_REL = Path("pt_build/devtest/static_semantic_auto/batch_result.json")


def _norm_path(v: Any) -> str:
    s = str(v).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.casefold()


def _row_asset(row: Any) -> str | None:
    keys = ("asset", "path", "logical", "relative_path", "relpath", "source", "source_path")
    if isinstance(row, dict):
        for k in keys:
            v = row.get(k)
            if v:
                return str(v)
    else:
        for k in keys:
            try:
                v = getattr(row, k)
            except Exception:
                continue
            if v and not callable(v):
                return str(v)
    return None


def _load_prior_selection(app: Path) -> list[dict[str, str]]:
    p = app / STATIC_BATCH_REL
    if not p.is_file():
        raise RuntimeError(f"static batch report missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    selected: list[dict[str, str]] = []
    for key in ("passed_assets", "failed_assets"):
        for item in data.get(key) or []:
            if isinstance(item, str):
                selected.append({"asset": item, "domain": ""})
            elif isinstance(item, dict) and item.get("asset"):
                selected.append({
                    "asset": str(item["asset"]),
                    "domain": str(item.get("domain") or ""),
                })
    dedup: dict[str, dict[str, str]] = {}
    for item in selected:
        dedup.setdefault(_norm_path(item["asset"]), item)
    selected = list(dedup.values())
    if int(data.get("requested", -1)) != EXPECTED_REPRESENTATIVE_COUNT:
        raise RuntimeError(f"static requested={data.get('requested')}; expected 13")
    if len(selected) != EXPECTED_REPRESENTATIVE_COUNT:
        raise RuntimeError(f"static unique representative count={len(selected)}; expected 13")
    if any(not x["domain"] for x in selected):
        raise RuntimeError("static selection missing domain metadata")
    return selected


def _find_core(app: Path) -> Path:
    exact = app / "pt_asset_core_v0_8_9.py"
    if exact.is_file():
        return exact
    candidates = sorted(app.glob("pt_asset_core_v*.py"))
    if not candidates:
        raise RuntimeError("no pt_asset_core_v*.py found")
    return candidates[-1]


def _harvest_bound(original: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(original)
    try:
        return dict(sig.bind_partial(*args, **kwargs).arguments)
    except TypeError:
        known = dict(kwargs)
        for i, v in enumerate(args):
            known[f"_arg{i}"] = v
        return known


def _find_known(known: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in known:
            return known[name]
    raise RuntimeError(f"required object not captured; tried={names}; known={sorted(known)}")


def _call_chooser(chooser: Any, registry: Any, resolver: Any, domain: str, limit: int) -> list[Any]:
    sig = inspect.signature(chooser)
    values = {
        "registry": registry, "asset_registry": registry,
        "resolver": resolver, "domain": domain, "limit": limit,
    }
    args, kwargs, unresolved = [], {}, []
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in values:
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                args.append(values[p.name])
            else:
                kwargs[p.name] = values[p.name]
        elif p.default is inspect._empty:
            unresolved.append(p.name)
    if unresolved:
        raise RuntimeError(f"chooser unresolved parameters={unresolved}; signature={sig}")
    rows = chooser(*args, **kwargs)
    if not isinstance(rows, (list, tuple)):
        raise RuntimeError(f"chooser returned {type(rows).__name__}, expected list")
    return list(rows)


def _validate_domain_selection(expected: list[dict[str, str]], actual_rows: list[Any], domain: str) -> dict[str, Any]:
    expected_paths = sorted(_norm_path(x["asset"]) for x in expected)
    actual_pairs = []
    for row in actual_rows:
        asset = _row_asset(row)
        if not asset:
            raise RuntimeError(f"chooser row for {domain} has no recognizable asset path")
        actual_pairs.append((_norm_path(asset), asset))
    actual_paths = sorted(x[0] for x in actual_pairs)
    report = {
        "domain": domain,
        "expected_count": len(expected_paths),
        "actual_count": len(actual_paths),
        "expected": [x["asset"] for x in expected],
        "actual": [x[1] for x in actual_pairs],
        "exact_match": expected_paths == actual_paths,
    }
    if not report["exact_match"]:
        report["missing"] = sorted(set(expected_paths) - set(actual_paths))
        report["unexpected"] = sorted(set(actual_paths) - set(expected_paths))
        raise RuntimeError(f"static chooser selection drift for {domain}: {report}")
    return report


def _call_batch(batch: Any, settings: Any, registry: Any, resolver: Any, certifications: Any, rows: list[Any]) -> dict[str, Any]:
    sig = inspect.signature(batch)
    values = {
        "settings": settings, "asset_registry": registry, "registry": registry,
        "resolver": resolver, "certifications": certifications, "rows": rows,
    }
    args, kwargs, unresolved = [], {}, []
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in values:
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                args.append(values[p.name])
            else:
                kwargs[p.name] = values[p.name]
        elif p.default is inspect._empty:
            unresolved.append(p.name)
    if unresolved:
        raise RuntimeError(f"batch unresolved parameters={unresolved}; signature={sig}")
    result = batch(*args, **kwargs)
    if not isinstance(result, dict):
        raise RuntimeError(f"batch returned {type(result).__name__}, expected dict")
    return result


def _install_server_stub(report: dict[str, Any]):
    mod = importlib.import_module("pt_asset_tool.server_design_auto")
    original = getattr(mod, "run_server_design_auto", None)
    if not callable(original):
        raise RuntimeError("server_design_auto entrypoint not found")

    def stub(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report["server_design_intercepted"] = True
        return {
            "format": "PT_RC6_6_SERVER_DESIGN_FOCUSED_STUB_V1",
            "status": "PASS",
            "server_design_catalog_ready": True,
            "bundle_closure_complete": False,
            "unresolved_or_review_count": 0,
            "environment": {"status": "PASS"},
            "server_write_authorized": False,
            "production_authorized": False,
            "focused_stub": True,
            "report": None,
        }

    setattr(mod, "run_server_design_auto", stub)
    return mod, original


def _synthetic_release_result(static_result: dict[str, Any], report_path: str | None) -> dict[str, Any]:
    status = static_result.get("status", "FAIL")
    return {
        "format": "PT_RC6_6_FOCUSED_RELEASE_STUB_V1",
        "status": status,
        "automatic_gate_status": status,
        "focused_static_only": True,
        "summary": {"model062_static": static_result},
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
        "client_modified": False,
        "report": report_path,
    }


def run_focused(app: Path, client: Path, server: Path) -> dict[str, Any]:
    app = app.resolve(); client = client.resolve(); server = server.resolve()
    sys.path.insert(0, str(app)); os.chdir(app)

    expected = _load_prior_selection(app)
    domain_counts = Counter(x["domain"] for x in expected)

    report: dict[str, Any] = {
        "format": FORMAT,
        "mode": "RERUN",
        "app_root": str(app),
        "client_root": str(client),
        "server_root": str(server),
        "selection_source": str(app / STATIC_BATCH_REL),
        "expected_representative_count": len(expected),
        "expected_domain_counts": dict(sorted(domain_counts.items())),
        "server_design_intercepted": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }

    static_mod = importlib.import_module("pt_asset_tool.static_semantic_devtest")
    chooser = getattr(static_mod, "choose_static_semantic_representatives")
    batch = getattr(static_mod, "run_static_semantic_automated_devtest_batch")

    release_mod = importlib.import_module("pt_asset_tool.release_1_auto")
    original_release = getattr(release_mod, "run_release_1_automated_gate", None)
    if not callable(original_release):
        raise RuntimeError("exact run_release_1_automated_gate not found")

    server_mod, original_server = _install_server_stub(report)
    interception_count = 0

    def intercepted_release(*args: Any, **kwargs: Any):
        nonlocal interception_count
        interception_count += 1
        if interception_count > 1:
            report["duplicate_release_interception_count"] = interception_count
            # Return the already-computed synthetic result without re-running Blender.
            if "result" not in report:
                raise RuntimeError("duplicate release interception before static result exists")
            return _synthetic_release_result(report["result"], report["result"].get("report"))

        known = _harvest_bound(original_release, args, kwargs)
        report["captured_argument_names"] = sorted(known)
        settings = _find_known(known, "settings", "config", "configuration")
        registry = _find_known(known, "registry", "asset_registry", "client_registry")
        resolver = _find_known(known, "resolver", "asset_resolver", "path_resolver")
        certifications = _find_known(
            known, "certifications", "certs", "writer_certifications", "certification_registry"
        )

        combined_rows: list[Any] = []
        domain_reports = []
        for domain in sorted(domain_counts):
            expected_domain = [x for x in expected if x["domain"] == domain]
            rows = _call_chooser(chooser, registry, resolver, domain, len(expected_domain))
            domain_reports.append(_validate_domain_selection(expected_domain, rows, domain))
            combined_rows.extend(rows)

        if len(combined_rows) != EXPECTED_REPRESENTATIVE_COUNT:
            raise RuntimeError(f"combined chooser rows={len(combined_rows)}; expected 13")

        report["domain_selection"] = domain_reports
        report["selected_row_count"] = len(combined_rows)
        static_result = _call_batch(batch, settings, registry, resolver, certifications, combined_rows)
        report["result"] = static_result
        report["status"] = static_result.get("status", "UNKNOWN")
        report["release_interception_count"] = interception_count
        return _synthetic_release_result(static_result, static_result.get("report"))

    setattr(release_mod, "run_release_1_automated_gate", intercepted_release)

    core_path = _find_core(app)
    report["core"] = str(core_path)
    spec = importlib.util.spec_from_file_location("pt_asset_core_rc655", core_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load core {core_path}")
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core

    old_argv = list(sys.argv)
    sys.argv = [
        str(core_path), "--client-root", str(client), "--server-root", str(server),
        "validate", "release-1-auto", "--resume",
    ]
    try:
        spec.loader.exec_module(core)
        # Some physical cores dispatch during module load; others expose main().
        if "result" not in report:
            main_fn = getattr(core, "main", None)
            if not callable(main_fn):
                raise RuntimeError("core main() not found and import did not dispatch")
            main_fn()
    finally:
        sys.argv = old_argv
        setattr(release_mod, "run_release_1_automated_gate", original_release)
        setattr(server_mod, "run_server_design_auto", original_server)

    if not report["server_design_intercepted"]:
        raise RuntimeError("server_design_auto interception did not execute")
    if "result" not in report:
        raise RuntimeError("static batch was not executed")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-root", default=".")
    ap.add_argument("--client-root", default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente")
    ap.add_argument("--server-root", default="/home/gabriel/Área de Trabalho/summit/Servidor")
    a = ap.parse_args()

    app = Path(a.app_root).expanduser().resolve()
    out = app / "pt_build/devtest/rc6_6_static_focused/result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = run_focused(
            app, Path(a.client_root).expanduser(), Path(a.server_root).expanduser()
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        result = {
            "format": FORMAT, "mode": "RERUN", "app_root": str(app),
            "status": "FAIL_BOOTSTRAP", "error": f"{type(exc).__name__}: {exc}",
            "production_authorized": False, "client_write_authorized": False,
            "server_write_authorized": False,
        }
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    # Exit 0 after a completed focused batch, even when the semantic result is FAIL.
    # FAIL is evidence for the verifier, not a bootstrap failure.
    if result.get("status") == "FAIL_BOOTSTRAP":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
