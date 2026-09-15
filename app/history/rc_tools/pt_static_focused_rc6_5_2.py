#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

FORMAT = "PT_RC6_5_2_STATIC_FOCUSED_BOOTSTRAP_V1"
STATIC_BATCH_NAME = "run_static_semantic_automated_devtest_batch"
STATIC_CHOOSER_NAME = "choose_static_semantic_representatives"
RELEASE_FORMAT_MARKER = "PT_ASSET_RELEASE_1_AUTOMATED_GATE_V1"


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
    # Prefer newest lexical version only when unique max; fail closed on ties.
    return candidates[-1]


def _function_strings(fn: Any) -> str:
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return ""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    vals = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            vals.append(n.value)
    return " ".join(vals)


def _find_release_entry(mod: Any):
    # RC6.5.2: the physical module exposes both a builder and the real runner.
    # Prefer the exact execution entrypoint instead of allowing generic scoring
    # to tie build_release_1_automated_gate with run_release_1_automated_gate.
    exact_name = "run_release_1_automated_gate"
    exact = getattr(mod, exact_name, None)
    if inspect.isfunction(exact):
        scored = []
        for name, obj in vars(mod).items():
            if not inspect.isfunction(obj):
                continue
            score = 0
            lname = name.casefold()
            if "release" in lname:
                score += 20
            if "auto" in lname:
                score += 10
            if RELEASE_FORMAT_MARKER in _function_strings(obj):
                score += 100
            if name == exact_name:
                score += 1000
            if score:
                scored.append((score, name, obj))
        scored.sort(key=lambda x: x[0], reverse=True)
        exact_row = next(x for x in scored if x[1] == exact_name)
        return exact_row, scored[:10]

    scored = []
    for name, obj in vars(mod).items():
        if not inspect.isfunction(obj):
            continue
        score = 0
        lname = name.casefold()
        if "release" in lname:
            score += 20
        if "auto" in lname:
            score += 10
        if lname.startswith("run_"):
            score += 15
        if lname.startswith("build_"):
            score -= 15
        if RELEASE_FORMAT_MARKER in _function_strings(obj):
            score += 100
        if score:
            scored.append((score, name, obj))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        raise RuntimeError("release entrypoint not found")
    best = scored[0]
    ties = [x for x in scored if x[0] == best[0]]
    if len(ties) != 1:
        raise RuntimeError(f"ambiguous release entrypoint: {[(s,n) for s,n,_ in ties]}")
    return best, scored[:10]


def _candidate_value(name: str, known: dict[str, Any], app: Path, client: Path, server: Path):
    if name in known:
        return known[name], True

    aliases = {
        "settings": ("settings", "config", "configuration"),
        "asset_registry": ("asset_registry", "registry", "client_registry"),
        "resolver": ("resolver", "asset_resolver", "path_resolver"),
        "certifications": ("certifications", "certs", "writer_certifications", "certification_registry"),
    }
    for canonical, names in aliases.items():
        if name == canonical:
            for n in names:
                if n in known:
                    return known[n], True

    # Derive representative rows only from a real registry object; never invent rows.
    if name in {"rows", "registry_rows", "assets", "asset_rows"}:
        reg = None
        for n in ("asset_registry", "registry", "client_registry"):
            if n in known:
                reg = known[n]
                break
        if reg is not None:
            for attr in ("rows", "asset_rows", "assets"):
                if hasattr(reg, attr):
                    val = getattr(reg, attr)
                    if callable(val):
                        try:
                            val = val()
                        except TypeError:
                            continue
                    return val, True
            if isinstance(reg, dict):
                for key in ("rows", "assets"):
                    if key in reg:
                        return reg[key], True

    roots = {
        "app_root": app, "app_dir": app,
        "client_root": client, "client_dir": client,
        "server_root": server, "server_dir": server,
    }
    if name in roots:
        return roots[name], True

    return None, False


def _call_by_signature(fn: Any, known: dict[str, Any], app: Path, client: Path, server: Path,
                       extra: dict[str, Any] | None = None):
    values = dict(known)
    if extra:
        values.update(extra)
    sig = inspect.signature(fn)
    args = []
    kwargs = {}
    unresolved = []
    mapping = {}
    for p in sig.parameters.values():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        val, ok = _candidate_value(p.name, values, app, client, server)
        if ok:
            mapping[p.name] = _jsonable(val)
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                args.append(val)
            else:
                kwargs[p.name] = val
        elif p.default is inspect._empty:
            unresolved.append(p.name)
    if unresolved:
        raise RuntimeError(
            f"cannot map required parameters for {fn.__module__}.{fn.__name__}: {unresolved}; "
            f"known={sorted(values)} signature={sig}"
        )
    return fn(*args, **kwargs), mapping


def _harvest_bound(original: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(original)
    try:
        bound = sig.bind_partial(*args, **kwargs)
        known = dict(bound.arguments)
    except TypeError:
        known = dict(kwargs)
        for idx, value in enumerate(args):
            known[f"_arg{idx}"] = value

    # Expand common container objects conservatively by attribute name only.
    expanded = dict(known)
    for obj in list(known.values()):
        if obj is None:
            continue
        for attr in (
            "settings", "config", "configuration",
            "asset_registry", "registry", "client_registry",
            "resolver", "asset_resolver", "path_resolver",
            "certifications", "certs", "writer_certifications", "certification_registry",
        ):
            if attr in expanded:
                continue
            try:
                val = getattr(obj, attr)
            except Exception:
                continue
            if not callable(val):
                expanded[attr] = val
    return expanded


def run_focused(app: Path, client: Path, server: Path) -> dict[str, Any]:
    app = app.resolve()
    client = client.resolve()
    server = server.resolve()
    sys.path.insert(0, str(app))
    os.chdir(app)

    static_mod = importlib.import_module("pt_asset_tool.static_semantic_devtest")
    batch = getattr(static_mod, STATIC_BATCH_NAME)
    chooser = getattr(static_mod, STATIC_CHOOSER_NAME)

    release_mod = importlib.import_module("pt_asset_tool.release_1_auto")
    (entry_score, entry_name, original_entry), entry_candidates = _find_release_entry(release_mod)

    report: dict[str, Any] = {
        "format": FORMAT,
        "app_root": str(app),
        "client_root": str(client),
        "server_root": str(server),
        "release_entry": {
            "module": release_mod.__name__,
            "function": entry_name,
            "score": entry_score,
            "signature": str(inspect.signature(original_entry)),
            "candidates": [{"score": s, "function": n} for s, n, _ in entry_candidates],
        },
        "static_batch_signature": str(inspect.signature(batch)),
        "static_chooser_signature": str(inspect.signature(chooser)),
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }

    focused_result: dict[str, Any] = {}

    def intercepted_release(*args: Any, **kwargs: Any):
        nonlocal focused_result
        known = _harvest_bound(original_entry, args, kwargs)
        report["captured_release_arguments"] = {
            k: _jsonable(v) for k, v in known.items()
            if k in {
                "settings", "config", "configuration",
                "asset_registry", "registry", "client_registry",
                "resolver", "asset_resolver", "path_resolver",
                "certifications", "certs", "writer_certifications", "certification_registry",
            }
        }
        report["captured_argument_names"] = sorted(known)

        selected_rows, chooser_mapping = _call_by_signature(
            chooser, known, app, client, server
        )
        if not isinstance(selected_rows, (list, tuple)):
            # Some chooser implementations may return a dict wrapper.
            if isinstance(selected_rows, dict):
                for key in ("rows", "representatives", "selected", "assets"):
                    if isinstance(selected_rows.get(key), (list, tuple)):
                        selected_rows = selected_rows[key]
                        break
        if not isinstance(selected_rows, (list, tuple)):
            raise RuntimeError(
                f"static chooser returned unsupported type {type(selected_rows).__name__}"
            )

        rows = list(selected_rows)
        report["chooser_mapping"] = chooser_mapping
        report["selected_row_count"] = len(rows)
        report["selected_row_preview"] = [_jsonable(x) for x in rows[:5]]

        result, batch_mapping = _call_by_signature(
            batch, known, app, client, server, extra={"rows": rows}
        )
        report["batch_mapping"] = batch_mapping
        if not isinstance(result, dict):
            raise RuntimeError(f"static batch returned {type(result).__name__}, expected dict")

        focused_result = result
        report["result"] = result
        report["status"] = result.get("status", "UNKNOWN")
        raise _FocusedDone()

    setattr(release_mod, entry_name, intercepted_release)

    core_path = _find_core(app)
    report["core"] = str(core_path)
    spec = importlib.util.spec_from_file_location("pt_asset_core_rc651", core_path)
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
        setattr(release_mod, entry_name, original_entry)

    if "result" not in report:
        raise RuntimeError("release interception was not reached; no static batch executed")
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
    out = app / "pt_build/devtest/rc6_5_2_static_focused/result.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    base = {
        "format": FORMAT,
        "app_root": str(app),
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }
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
            **base,
            "status": "FAIL_BOOTSTRAP",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if result.get("status") != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
