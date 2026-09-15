#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

FORMAT = "PT_RC6_5_3_STATIC_DIRECT_REPLAY_V1"
EXPECTED_REPRESENTATIVE_COUNT = 13
STATIC_BATCH_REL = Path("pt_build/devtest/static_semantic_auto/batch_result.json")


class _FocusedDone(BaseException):
    pass


def _jsonable(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in list(v.items())[:50]}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in list(v)[:50]]
    return f"<{type(v).__module__}.{type(v).__name__}>"


def _find_core(app: Path) -> Path:
    exact = app / "pt_asset_core_v0_8_9.py"
    if exact.is_file():
        return exact
    candidates = sorted(app.glob("pt_asset_core_v*.py"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError("no pt_asset_core_v*.py found")
    return candidates[-1]


def _norm_path(v: Any) -> str:
    s = str(v).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.casefold()


def _row_strings(row: Any) -> list[str]:
    keys = (
        "asset", "path", "logical", "relative_path", "relpath",
        "source", "source_path", "client_path", "file", "filename",
    )
    vals: list[str] = []
    if isinstance(row, dict):
        for k in keys:
            if k in row and row[k] is not None:
                vals.append(str(row[k]))
    else:
        for k in keys:
            try:
                v = getattr(row, k)
            except Exception:
                continue
            if v is not None and not callable(v):
                vals.append(str(v))
    return vals


def _registry_rows(registry: Any) -> list[Any]:
    if isinstance(registry, (list, tuple)):
        return list(registry)
    if isinstance(registry, dict):
        for key in ("rows", "assets", "entries", "records"):
            v = registry.get(key)
            if isinstance(v, (list, tuple)):
                return list(v)

    for attr in ("rows", "assets", "entries", "records", "asset_rows"):
        try:
            v = getattr(registry, attr)
        except Exception:
            continue
        if callable(v):
            try:
                v = v()
            except TypeError:
                continue
        if isinstance(v, (list, tuple)):
            return list(v)

    # Last resort only for explicitly iterable registry containers.
    if hasattr(registry, "__iter__") and not isinstance(registry, (str, bytes, dict)):
        try:
            rows = list(registry)
        except Exception:
            rows = []
        if rows:
            return rows

    raise RuntimeError(
        f"cannot extract rows from registry type {type(registry).__module__}.{type(registry).__name__}"
    )


def _load_prior_assets(app: Path) -> list[dict[str, str]]:
    p = app / STATIC_BATCH_REL
    if not p.is_file():
        raise RuntimeError(f"prior static batch report missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    assets: list[dict[str, str]] = []

    passed = data.get("passed_assets") or []
    for item in passed:
        if isinstance(item, str):
            assets.append({"asset": item, "domain": ""})
        elif isinstance(item, dict) and item.get("asset"):
            assets.append({"asset": str(item["asset"]), "domain": str(item.get("domain") or "")})

    failed = data.get("failed_assets") or []
    for item in failed:
        if isinstance(item, dict) and item.get("asset"):
            assets.append({"asset": str(item["asset"]), "domain": str(item.get("domain") or "")})
        elif isinstance(item, str):
            assets.append({"asset": item, "domain": ""})

    # Stable de-duplication.
    seen = set()
    out = []
    for item in assets:
        n = _norm_path(item["asset"])
        if n and n not in seen:
            seen.add(n)
            out.append(item)

    requested = data.get("requested")
    if requested is not None and int(requested) != len(out):
        raise RuntimeError(
            f"prior batch selection mismatch: requested={requested} unique_assets={len(out)}"
        )
    if len(out) != EXPECTED_REPRESENTATIVE_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_REPRESENTATIVE_COUNT} prior static representatives, found {len(out)}"
        )
    return out


def _match_rows(registry: Any, selected: list[dict[str, str]]) -> tuple[list[Any], list[dict[str, Any]]]:
    rows = _registry_rows(registry)
    matched = []
    diagnostics = []
    used_ids = set()

    for sel in selected:
        target = _norm_path(sel["asset"])
        candidates = []
        for idx, row in enumerate(rows):
            strings = _row_strings(row)
            score = 0
            evidence = None
            for raw in strings:
                n = _norm_path(raw)
                if n == target:
                    score = max(score, 100)
                    evidence = raw
                elif n.endswith("/" + target):
                    score = max(score, 90)
                    evidence = raw
            if score:
                candidates.append((score, idx, row, evidence))

        candidates.sort(key=lambda x: x[0], reverse=True)
        if not candidates:
            diagnostics.append({"asset": sel["asset"], "status": "NOT_FOUND"})
            continue
        top_score = candidates[0][0]
        top = [x for x in candidates if x[0] == top_score]
        if len(top) != 1:
            diagnostics.append({
                "asset": sel["asset"],
                "status": "AMBIGUOUS",
                "candidate_count": len(top),
                "score": top_score,
                "evidence": [x[3] for x in top[:10]],
            })
            continue

        _, idx, row, evidence = top[0]
        if idx in used_ids:
            diagnostics.append({
                "asset": sel["asset"],
                "status": "ROW_ALREADY_USED",
                "evidence": evidence,
            })
            continue
        used_ids.add(idx)
        matched.append(row)
        diagnostics.append({
            "asset": sel["asset"],
            "domain": sel.get("domain", ""),
            "status": "MATCHED",
            "score": top_score,
            "evidence": evidence,
        })

    bad = [x for x in diagnostics if x["status"] != "MATCHED"]
    if bad:
        raise RuntimeError(f"could not map prior static representatives to registry rows: {bad}")
    if len(matched) != EXPECTED_REPRESENTATIVE_COUNT:
        raise RuntimeError(f"mapped {len(matched)} rows, expected {EXPECTED_REPRESENTATIVE_COUNT}")
    return matched, diagnostics


def _harvest_bound(original: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(original)
    try:
        return dict(sig.bind_partial(*args, **kwargs).arguments)
    except TypeError:
        known = dict(kwargs)
        for idx, value in enumerate(args):
            known[f"_arg{idx}"] = value
        return known


def _find_known(known: dict[str, Any], names: tuple[str, ...]) -> Any:
    for n in names:
        if n in known:
            return known[n]
    raise RuntimeError(f"required captured object not found; tried={names}; known={sorted(known)}")


def _call_static_batch(batch: Any, known: dict[str, Any], rows: list[Any]) -> tuple[dict[str, Any], dict[str, str]]:
    aliases = {
        "settings": ("settings", "config", "configuration"),
        "asset_registry": ("asset_registry", "registry", "client_registry"),
        "registry": ("registry", "asset_registry", "client_registry"),
        "resolver": ("resolver", "asset_resolver", "path_resolver"),
        "certifications": ("certifications", "certs", "writer_certifications", "certification_registry"),
        "rows": ("__rows__",),
    }
    values = dict(known)
    values["__rows__"] = rows
    sig = inspect.signature(batch)
    args = []
    kwargs = {}
    mapping = {}
    unresolved = []

    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        val = None
        ok = False
        names = aliases.get(p.name, (p.name,))
        for n in names:
            if n in values:
                val = values[n]
                ok = True
                break
        if ok:
            mapping[p.name] = f"<{type(val).__module__}.{type(val).__name__}>"
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                args.append(val)
            else:
                kwargs[p.name] = val
        elif p.default is inspect._empty:
            unresolved.append(p.name)

    if unresolved:
        raise RuntimeError(f"static batch unresolved required parameters={unresolved}; signature={sig}")
    result = batch(*args, **kwargs)
    if not isinstance(result, dict):
        raise RuntimeError(f"static batch returned {type(result).__name__}, expected dict")
    return result, mapping


def _install_server_design_stub(report: dict[str, Any]) -> tuple[Any, Any]:
    mod = importlib.import_module("pt_asset_tool.server_design_auto")
    original = getattr(mod, "run_server_design_auto", None)
    if not callable(original):
        raise RuntimeError("pt_asset_tool.server_design_auto.run_server_design_auto not found")

    def stub(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report["server_design_intercepted"] = True
        return {
            "format": "PT_RC6_5_3_FOCUSED_SERVER_DESIGN_STUB_V1",
            "status": "PASS",
            "server_design_catalog_ready": True,
            "bundle_closure_complete": False,
            "unresolved_or_review_count": 0,
            "environment": {"status": "PASS"},
            "production_authorized": False,
            "server_write_authorized": False,
            "report": None,
            "focused_stub": True,
        }

    setattr(mod, "run_server_design_auto", stub)
    return mod, original


def run_focused(app: Path, client: Path, server: Path) -> dict[str, Any]:
    app = app.resolve()
    client = client.resolve()
    server = server.resolve()
    sys.path.insert(0, str(app))
    os.chdir(app)

    selected = _load_prior_assets(app)
    report: dict[str, Any] = {
        "format": FORMAT,
        "app_root": str(app),
        "client_root": str(client),
        "server_root": str(server),
        "selection_source": str(app / STATIC_BATCH_REL),
        "selection": selected,
        "server_design_intercepted": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }

    static_mod = importlib.import_module("pt_asset_tool.static_semantic_devtest")
    batch = getattr(static_mod, "run_static_semantic_automated_devtest_batch")
    report["static_batch_signature"] = str(inspect.signature(batch))

    release_mod = importlib.import_module("pt_asset_tool.release_1_auto")
    original_release = getattr(release_mod, "run_release_1_automated_gate", None)
    if not callable(original_release):
        raise RuntimeError("exact run_release_1_automated_gate not found")

    server_mod, original_server = _install_server_design_stub(report)

    def intercepted_release(*args: Any, **kwargs: Any):
        known = _harvest_bound(original_release, args, kwargs)
        report["captured_argument_names"] = sorted(known)

        registry = _find_known(known, ("asset_registry", "registry", "client_registry"))
        matched_rows, row_diag = _match_rows(registry, selected)
        report["registry_row_mapping"] = row_diag
        report["matched_row_count"] = len(matched_rows)

        result, mapping = _call_static_batch(batch, known, matched_rows)
        report["batch_mapping"] = mapping
        report["result"] = result
        report["status"] = result.get("status", "UNKNOWN")
        raise _FocusedDone()

    setattr(release_mod, "run_release_1_automated_gate", intercepted_release)

    core_path = _find_core(app)
    report["core"] = str(core_path)
    spec = importlib.util.spec_from_file_location("pt_asset_core_rc653", core_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load core {core_path}")
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core

    old_argv = list(sys.argv)
    sys.argv = [
        str(core_path),
        "--client-root", str(client),
        "--server-root", str(server),
        "validate", "release-1-auto", "--resume",
    ]
    try:
        spec.loader.exec_module(core)
        main = getattr(core, "main", None)
        if not callable(main):
            raise RuntimeError("core main() not found")
        try:
            main()
        except _FocusedDone:
            pass
    finally:
        sys.argv = old_argv
        setattr(release_mod, "run_release_1_automated_gate", original_release)
        setattr(server_mod, "run_server_design_auto", original_server)

    if not report.get("server_design_intercepted"):
        raise RuntimeError("server_design_auto was not intercepted; focused safety invariant failed")
    if "result" not in report:
        raise RuntimeError("release interception was not reached; static batch was not executed")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-root", default=".")
    ap.add_argument(
        "--client-root",
        default="/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente",
    )
    ap.add_argument(
        "--server-root",
        default="/home/gabriel/Área de Trabalho/summit/Servidor",
    )
    args = ap.parse_args()

    app = Path(args.app_root).expanduser().resolve()
    out = app / "pt_build/devtest/rc6_5_3_static_focused/result.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = run_focused(
            app,
            Path(args.client_root).expanduser(),
            Path(args.server_root).expanduser(),
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        result = {
            "format": FORMAT,
            "app_root": str(app),
            "status": "FAIL_BOOTSTRAP",
            "error": f"{type(exc).__name__}: {exc}",
            "production_authorized": False,
            "client_write_authorized": False,
            "server_write_authorized": False,
        }

    out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if result.get("status") != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
