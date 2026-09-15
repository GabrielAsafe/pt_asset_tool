#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib
import inspect
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from incremental_audit_cache import CachePolicy, GateCache
from blender_watchdog import BlenderWatchdog

APP_DIR = Path(__file__).resolve().parent
CACHE_ROOT = APP_DIR / "pt_build" / "incremental_cache_v1"

KNOWN_HEAVY_GATES = {
    "server_design_auto",
    "model062_mixed_synthetic",
    "model062_physical_corpus",
    "rigid_context_census",
    "rigid_lod_context_corpus",
    "model062_rigid",
    "model062_rigid_standalone",
    "model062_material_corpus",
    "material_physical_corpus",
    "stage072_physical_corpus",
    "texture_physical_corpus",
    "smb_animation_corpus",
    "motion_semantic_corpus",
}


def _arg_value(argv: Sequence[str], option: str) -> Optional[str]:
    for i, arg in enumerate(argv):
        if arg == option and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(option + "="):
            return arg.split("=", 1)[1]
    return None


def _module_name_for(path: Path) -> str:
    rel = path.resolve().relative_to(APP_DIR)
    return ".".join(rel.with_suffix("").parts)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def discover_logged_gate_names() -> Set[str]:
    gates = set(KNOWN_HEAVY_GATES)
    patterns = [
        re.compile(r"START\s+([A-Za-z0-9_]+)"),
        re.compile(r"DONE\s+([A-Za-z0-9_]+)\s+status="),
    ]
    for path in APP_DIR.rglob("*.py"):
        if "pt_build" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "release-1-auto" not in text and "release_1_auto" not in text:
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                name = _normalize_name(match.group(1))
                if name and len(name) > 3 and name not in {"server", "client", "environment", "inventory"}:
                    gates.add(name)
    return gates


def _function_candidates(path: Path, gate_name: str) -> List[Tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except Exception:
        return []
    gate = _normalize_name(gate_name)
    out: List[Tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = _normalize_name(node.name)
        seg = ast.get_source_segment(text, node) or ""
        score = 0
        if name == gate:
            score += 50
        if name in {f"run_{gate}", f"validate_{gate}", f"audit_{gate}", f"cmd_{gate}"}:
            score += 45
        if name.endswith("_" + gate) or name.startswith(gate + "_"):
            score += 30
        if gate in name:
            score += 20
        pretty = gate.replace("_", "-")
        if f"START {gate}" in seg or f"START {pretty}" in seg:
            score += 10
        if gate == "server_design_auto":
            if "SERVER START inventory" in seg:
                score += 25
            if "SERVER_INVENTORY" in seg:
                score += 10
        # Avoid wrapping the full release driver for a sub-gate merely because
        # it contains the gate name in logging/data tables.
        if "release_1_auto" in name and gate != "release_1_auto":
            score -= 40
        if score > 0:
            out.append((score, node.name))
    return out


def discover_gate_function(gate_name: str) -> Optional[Tuple[Path, str, int]]:
    best: Optional[Tuple[int, Path, str]] = None
    for path in APP_DIR.rglob("*.py"):
        if "pt_build" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name in {Path(__file__).name, "incremental_audit_cache.py", "cache_status.py"}:
            continue
        for score, func_name in _function_candidates(path, gate_name):
            candidate = (score, path, func_name)
            if best is None or score > best[0]:
                best = candidate
    if best is None or best[0] < 20:
        return None
    return best[1], best[2], best[0]


def import_module_for_file(path: Path) -> ModuleType:
    return importlib.import_module(_module_name_for(path))


def report_candidates(gate_name: str) -> List[Path]:
    gate = _normalize_name(gate_name)
    return [
        APP_DIR / "pt_build" / "devtest" / gate / "result.json",
        APP_DIR / "pt_build" / gate / "result.json",
        APP_DIR / "pt_build" / "release_1_auto" / gate / "result.json",
        APP_DIR / "pt_build" / "release_1_auto" / f"{gate}.json",
    ]


def _bound_root(func: Callable[..., Any], args: Sequence[Any], kwargs: Mapping[str, Any], kind: str) -> Optional[str]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **dict(kwargs))
        for name, value in bound.arguments.items():
            lname = name.lower()
            if kind == "server" and ("server_root" in lname or lname == "server"):
                if isinstance(value, (str, os.PathLike)):
                    return str(value)
            if kind == "client" and ("client_root" in lname or lname in {"root", "client"}):
                if isinstance(value, (str, os.PathLike)):
                    return str(value)
    except Exception:
        pass
    return None


def _roots_for_gate(
    gate_name: str,
    func: Callable[..., Any],
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    client_fallback: Optional[str],
    server_fallback: Optional[str],
) -> Dict[str, str]:
    gate = _normalize_name(gate_name)
    roots: Dict[str, str] = {}
    if gate.startswith("server_") or gate == "server_design_auto":
        value = _bound_root(func, args, kwargs, "server") or server_fallback
        if value:
            roots["server_root"] = value
    else:
        value = _bound_root(func, args, kwargs, "client") or client_fallback
        if value:
            roots["client_root"] = value
    return roots


def patch_gate(
    gate_name: str,
    policy: CachePolicy,
    client_fallback: Optional[str],
    server_fallback: Optional[str],
    used_targets: Set[Tuple[str, str]],
) -> bool:
    found = discover_gate_function(gate_name)
    if found is None:
        return False
    path, func_name, score = found
    target_key = (_module_name_for(path), func_name)
    if target_key in used_targets:
        return False
    module = import_module_for_file(path)
    original = getattr(module, func_name, None)
    if not callable(original):
        return False

    cache = GateCache(CACHE_ROOT, app_dir=APP_DIR, policy=policy)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        roots = _roots_for_gate(gate_name, original, args, kwargs, client_fallback, server_fallback)
        if not roots:
            print(f"[incremental-cache] WARN no root resolved gate={gate_name}; running normally")
            return original(*args, **kwargs)
        return cache.call(
            gate_name,
            original,
            args,
            kwargs,
            roots,
            warm_reports=report_candidates(gate_name),
        )

    wrapped.__name__ = getattr(original, "__name__", func_name)
    wrapped.__qualname__ = getattr(original, "__qualname__", func_name)
    wrapped.__doc__ = getattr(original, "__doc__", None)
    setattr(module, func_name, wrapped)
    used_targets.add(target_key)
    print(f"[incremental-cache] PATCH gate={gate_name} target={target_key[0]}.{func_name} score={score} mode={policy.mode}")
    return True


def patch_discovered_gates(policy: CachePolicy, client_root: Optional[str], server_root: Optional[str]) -> int:
    gates = sorted(discover_logged_gate_names(), key=lambda x: (-len(x), x))
    used: Set[Tuple[str, str]] = set()
    patched = 0
    # Always attempt server first because it is the largest known repeated census.
    ordered = ["server_design_auto"] + [g for g in gates if g != "server_design_auto"]
    for gate in ordered:
        try:
            if patch_gate(gate, policy, client_root, server_root, used):
                patched += 1
        except Exception as exc:
            print(f"[incremental-cache] WARN patch failed gate={gate}: {exc}")
    print(f"[incremental-cache] PATCH_SUMMARY patched={patched} discovered_gate_names={len(gates)}")
    return patched


def _run_original_pt_asset() -> int:
    pt_asset = importlib.import_module("pt_asset")
    main = getattr(pt_asset, "main", None)
    if callable(main):
        result = main()
        return int(result) if isinstance(result, int) else 0
    cli = getattr(pt_asset, "cli", None)
    if callable(cli):
        result = cli()
        return int(result) if isinstance(result, int) else 0
    raise RuntimeError("pt_asset.py has no callable main()/cli(); cached runner cannot safely invoke it")


def main() -> int:
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    policy = CachePolicy.from_env()
    client_root = _arg_value(sys.argv[1:], "--client-root")
    server_root = _arg_value(sys.argv[1:], "--server-root")
    if policy.mode == "trust-readonly":
        print("[incremental-cache] TRUST_READONLY enabled: asset payloads are not rescanned to validate cache identity")
        print("[incremental-cache] Delete pt_build/incremental_cache_v1 if client/server files were changed externally")
    patch_discovered_gates(policy, client_root, server_root)
    watchdog = BlenderWatchdog()
    watchdog.start()
    try:
        return _run_original_pt_asset()
    finally:
        watchdog.stop()


if __name__ == "__main__":
    raise SystemExit(main())
