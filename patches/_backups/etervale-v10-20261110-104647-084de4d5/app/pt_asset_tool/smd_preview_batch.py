from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import time
import threading
from typing import Any

from .config import Settings
from .dependencies import blender_runtime_info
from .registry import AssetRegistry
from .resolver import ClientResolver
from .smd_preview import SmdPreviewManager, build_smd_preview_plan

FORMAT = "PT_SMD_PREVIEW_BATCH_V2"


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
    cancel_event: threading.Event | None = None,
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
        "phase": "PLANNING",
        "planning_processed": 0,
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
        "counts": {"READY": 0, "MISSING": 0, "STALE": 0, "FAILED": 0, "UNSUPPORTED": 0, "UNAVAILABLE": 0, "QUEUED": 0, "RUNNING": 0, "SKIPPED": 0, "CANCELED": 0},
        "items": {},
    }
    _atomic_json(state_path, state)

    plans: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = []
    for ordinal, rel in enumerate(candidates, 1):
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
        state["planning_processed"] = ordinal
        state["selected_so_far"] = len(plans)
        if ordinal % 50 == 0 or ordinal == len(candidates):
            state["updated_at"] = time.time()
            _atomic_json(state_path, state)
            print(f"SMD_PREVIEW_PLANNING done={ordinal} total={len(candidates)} selected={len(plans)}", flush=True)
    state["selected_for_render"] = len(plans)
    state["phase"] = "RENDERING"
    state["updated_at"] = time.time()
    _atomic_json(state_path, state)

    completed = 0
    lock = threading.RLock()
    stop = cancel_event or threading.Event()

    def render_one(entry: tuple[str, dict[str, Any], dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        rel, plan, _classification = entry
        if stop.is_set():
            return rel, {"status": "CANCELED", "asset": rel, "detail": "BATCH_CANCELED"}
        with lock:
            state["items"][rel] = {"status": "RUNNING", "updated_at": time.time()}
            state["updated_at"] = time.time()
            _atomic_json(state_path, state)
        try:
            result = manager.render_now(plan, retry=True, force=force, cancel_event=stop)
        except TypeError as exc:
            # Compatibility for injected/legacy preview managers that predate
            # cooperative cancellation.  The first-party manager accepts it.
            if "cancel_event" not in str(exc):
                raise
            result = manager.render_now(plan, retry=True, force=force)
        return rel, result

    def persist_result(rel: str, result: dict[str, Any]) -> None:
        nonlocal completed
        completed += 1
        st = str(result.get("status") or "FAILED")
        with lock:
            state["items"][rel] = {
                "status": st,
                "detail": result.get("detail"),
                "dependency_count": result.get("dependency_count"),
                "import_strategy": result.get("import_strategy"),
                "updated_at": time.time(),
            }
            final_counts: dict[str, int] = {}
            for row in state["items"].values():
                ss = str((row or {}).get("status") or "MISSING")
                final_counts[ss] = final_counts.get(ss, 0) + 1
            state["counts_final"] = final_counts
            state["completed"] = completed
            state["updated_at"] = time.time()
            _atomic_json(state_path, state)
        print(f"SMD_PREVIEW_PROGRESS done={completed} total={len(plans)} status={st} path={rel}", flush=True)

    max_workers = max(1, min(4, int(workers)))
    canceled = False
    executor: concurrent.futures.ThreadPoolExecutor | None = None
    if plans:
        plan_iter = iter(plans)
        pending: dict[concurrent.futures.Future, str] = {}
        try:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pt-smd-batch")
            for _ in range(max_workers):
                try: entry = next(plan_iter)
                except StopIteration: break
                pending[executor.submit(render_one, entry)] = entry[0]
            while pending:
                if stop.is_set():
                    canceled = True
                    break
                done, _ = concurrent.futures.wait(
                    list(pending), timeout=0.25,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for fut in done:
                    rel = pending.pop(fut)
                    try:
                        out_rel, result = fut.result()
                    except Exception as exc:
                        out_rel, result = rel, {"status": "FAILED", "asset": rel, "detail": f"{type(exc).__name__}:{exc}"}
                    persist_result(out_rel, result)
                    if stop.is_set():
                        canceled = True
                        break
                    try: entry = next(plan_iter)
                    except StopIteration: continue
                    pending[executor.submit(render_one, entry)] = entry[0]
        except KeyboardInterrupt:
            canceled = True
            stop.set()
            print("SMD_PREVIEW_BATCH=CANCELING reason=KeyboardInterrupt", flush=True)
        finally:
            if canceled:
                stop.set()
                for fut in list(pending):
                    fut.cancel()
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
            elif executor is not None:
                executor.shutdown(wait=True)

    if canceled or stop.is_set():
        for rel, row in state["items"].items():
            if str((row or {}).get("status") or "") in {"RUNNING", "QUEUED"}:
                row.update(status="MISSING", detail="BATCH_CANCELED_RETRYABLE", updated_at=time.time())
        final_counts: dict[str, int] = {}
        for row in state["items"].values():
            ss = str((row or {}).get("status") or "MISSING")
            final_counts[ss] = final_counts.get(ss, 0) + 1
        state["counts_final"] = final_counts
        state["completed"] = completed
        state["status"] = "CANCELED"
        state["finished_at"] = time.time()
        state["updated_at"] = state["finished_at"]
        state["duration_seconds"] = round(state["finished_at"] - started, 3)
        _atomic_json(state_path, state)
        print("SMD_PREVIEW_BATCH=CANCELED " + " ".join(f"{k.lower()}={v}" for k, v in sorted(final_counts.items())), flush=True)
        return state

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
        out = run_batch(root, pathlib.Path(ns.client_root).expanduser() if ns.client_root else None, mode=ns.mode, workers=ns.workers, limit=ns.limit, force=ns.force)
        return 130 if out.get("status") == "CANCELED" else 0
    except Exception as exc:
        print(f"SMD_PREVIEW_BATCH=FAIL {type(exc).__name__}:{exc}", flush=True)
        return 2
