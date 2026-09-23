from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import time
from typing import Any

from .config import Settings
from .dependencies import blender_runtime_info
from .registry import AssetRegistry
from .resolver import ClientResolver
from .smd_preview import SmdPreviewManager, build_smd_preview_plan

FORMAT = "PT_SMD_PREVIEW_BATCH_V1"


def _atomic_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _candidate_paths(registry: AssetRegistry) -> list[str]:
    rows = []
    for asset in registry.assets:
        if asset.family in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_STATIC"}:
            rows.append(asset.primary_path)
    return sorted(set(rows), key=str.casefold)


def batch_state_path(project_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(project_root) / "pt_build" / "previews" / "smd_catalog" / "batch_state.json"


def read_batch_state(project_root: pathlib.Path) -> dict[str, Any]:
    path = batch_state_path(project_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"format": FORMAT, "status": "NOT_RUN", "counts": {}, "items": {}}
    return raw if isinstance(raw, dict) else {"format": FORMAT, "status": "NOT_RUN", "counts": {}, "items": {}}


def run_batch(
    project_root: pathlib.Path,
    client_root: pathlib.Path | None = None,
    *,
    mode: str = "warmup",
    workers: int = 1,
    limit: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    settings = Settings.discover(project_root, client_root, verify_registry=False)
    if not settings.client_root.is_dir():
        raise FileNotFoundError(f"CLIENT_ROOT_NOT_FOUND:{settings.client_root}")
    if not settings.inventory.is_file() or not settings.pairing.is_file():
        raise FileNotFoundError("ASSET_REGISTRY_REQUIRED; execute Reindexar/registry rebuild first")

    runtime = blender_runtime_info(project_root, probe_version=True)
    if not runtime.get("ready"):
        raise RuntimeError(f"BLENDER_UNAVAILABLE:{runtime.get('detail')}")

    resolver = ClientResolver(settings.client_root)
    resolver.prime_from_inventory(settings.inventory)
    registry = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    manager = SmdPreviewManager(project_root, settings.client_root, workers=1)
    candidates = _candidate_paths(registry)
    if limit:
        candidates = candidates[: max(0, int(limit))]

    state_path = batch_state_path(project_root)
    started = time.time()
    state: dict[str, Any] = {
        "format": FORMAT,
        "status": "RUNNING",
        "mode": mode,
        "workers": max(1, min(4, int(workers))),
        "force": bool(force),
        "started_at": started,
        "updated_at": started,
        "client_root": str(settings.client_root),
        "inventory": str(settings.inventory),
        "blender": {
            "source": runtime.get("source"),
            "version": runtime.get("version"),
            "command": list(runtime.get("command") or []),
        },
        "total_candidates": len(candidates),
        "counts": {"READY": 0, "MISSING": 0, "STALE": 0, "FAILED": 0, "UNSUPPORTED": 0, "UNAVAILABLE": 0, "QUEUED": 0, "RUNNING": 0, "SKIPPED": 0},
        "items": {},
    }
    _atomic_json(state_path, state)

    plans: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = []
    for rel in candidates:
        plan = build_smd_preview_plan(registry, resolver, rel)
        classification = manager.classify(plan) if plan else {"status": "UNSUPPORTED", "detail": "SMD_PREVIEW_PLAN_UNAVAILABLE", "asset": rel}
        status = str(classification.get("status") or "MISSING")
        state["items"][rel] = {"status": status, "detail": classification.get("detail"), "updated_at": time.time()}
        state["counts"][status] = int(state["counts"].get(status, 0)) + 1
        should = force or (
            mode == "all" and status != "UNSUPPORTED" and status != "UNAVAILABLE"
        ) or (
            mode == "warmup" and status in {"MISSING", "STALE", "FAILED"}
        ) or (
            mode == "missing" and status == "MISSING"
        ) or (
            mode == "stale" and status == "STALE"
        ) or (
            mode == "failed" and status == "FAILED"
        )
        if should and plan:
            plans.append((rel, plan, classification))
        elif status not in {"READY", "UNSUPPORTED", "UNAVAILABLE"}:
            state["counts"]["SKIPPED"] += 1
    state["selected_for_render"] = len(plans)
    state["updated_at"] = time.time()
    _atomic_json(state_path, state)

    completed = 0
    lock = __import__("threading").RLock()

    def render_one(entry: tuple[str, dict[str, Any], dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        rel, plan, _classification = entry
        with lock:
            state["items"][rel] = {"status": "RUNNING", "updated_at": time.time()}
            state["updated_at"] = time.time()
            _atomic_json(state_path, state)
        result = manager.render_now(plan, retry=True, force=force)
        return rel, result

    max_workers = max(1, min(4, int(workers)))
    if plans:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pt-smd-batch") as ex:
            futures = [ex.submit(render_one, entry) for entry in plans]
            for fut in concurrent.futures.as_completed(futures):
                rel, result = fut.result()
                completed += 1
                st = str(result.get("status") or "FAILED")
                with lock:
                    state["items"][rel] = {
                        "status": st,
                        "detail": result.get("detail"),
                        "dependency_count": result.get("dependency_count"),
                        "updated_at": time.time(),
                    }
                    # Recount final states rather than trying to mutate the preflight counts.
                    final_counts: dict[str, int] = {}
                    for row in state["items"].values():
                        s = str((row or {}).get("status") or "MISSING")
                        final_counts[s] = final_counts.get(s, 0) + 1
                    state["counts_final"] = final_counts
                    state["completed"] = completed
                    state["updated_at"] = time.time()
                    _atomic_json(state_path, state)
                print(f"SMD_PREVIEW_PROGRESS done={completed} total={len(plans)} status={st} path={rel}", flush=True)

    final_counts: dict[str, int] = {}
    for row in state["items"].values():
        s = str((row or {}).get("status") or "MISSING")
        final_counts[s] = final_counts.get(s, 0) + 1
    state["counts_final"] = final_counts
    state["completed"] = completed
    state["status"] = "COMPLETE"
    state["finished_at"] = time.time()
    state["updated_at"] = state["finished_at"]
    state["duration_seconds"] = round(state["finished_at"] - started, 3)
    _atomic_json(state_path, state)
    print("SMD_PREVIEW_BATCH=PASS " + " ".join(f"{k.lower()}={v}" for k, v in sorted(final_counts.items())), flush=True)
    return state


def cli_main(argv: list[str] | None = None, *, project_root: pathlib.Path | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pt_asset.py preview render-all-smd")
    ap.add_argument("--client-root")
    ap.add_argument("--mode", choices=["warmup", "all", "missing", "stale", "failed"], default="warmup")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ns = ap.parse_args(argv)
    root = pathlib.Path(project_root).resolve() if project_root else pathlib.Path(__file__).resolve().parent.parent
    try:
        run_batch(root, pathlib.Path(ns.client_root).expanduser() if ns.client_root else None, mode=ns.mode, workers=ns.workers, limit=ns.limit, force=ns.force)
        return 0
    except Exception as exc:
        print(f"SMD_PREVIEW_BATCH=FAIL {type(exc).__name__}:{exc}", flush=True)
        return 2
