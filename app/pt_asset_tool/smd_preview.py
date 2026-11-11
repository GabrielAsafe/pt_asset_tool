from __future__ import annotations

import hashlib
from contextlib import contextmanager
try:
    import fcntl  # Cross-process index coordination on Linux
except ImportError:
    fcntl = None
import json
import os
import pathlib
import queue
import subprocess
import threading
import time
from typing import Any

from .blender_workspace import asset_workspace_name
from .dependencies import blender_runtime_info
from .rigid_model_info import effective_lod_node_coverage

FORMAT = "PT_CATALOG_SMD_PREVIEW_V3"
INDEX_FORMAT = "PT_CATALOG_SMD_PREVIEW_INDEX_V1"


def _stat(path: pathlib.Path | None) -> list[int]:
    if path is None:
        return [0, 0]
    try:
        st = path.stat()
        return [int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [0, 0]


def _json_load(path: pathlib.Path) -> dict[str, Any]:
    try:
        x = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return x if isinstance(x, dict) else {}


def _preview_rigid_context(asset: Any) -> dict[str, Any] | None:
    """Select a paint/edit style rigid context for read-only thumbnails.

    Authoring remains fail-closed and can require an explicit INX when several
    contexts differ.  A thumbnail is different: it needs a physically valid
    visual witness, not an authoring decision.  Prefer a registry-proven INX/LOD
    whose node coverage passes; if none does, retain the proven skeleton and use
    the same skeleton-only path as the stable Paint/Edit workspace.
    """
    skeleton = str(getattr(asset, "binding_skeleton_smb", "") or "").replace("\\", "/").strip("/")
    if not bool(getattr(asset, "rigid_binding_ready", False)) or not skeleton:
        return None
    candidates: list[tuple[int, int, str, str, dict[str, Any], dict[str, Any]]] = []
    for cfg in list(getattr(asset, "configs", None) or []):
        inx = str(cfg.get("inx") or "").replace("\\", "/").strip("/")
        if not inx:
            continue
        groups = cfg.get("lod_groups") or {}
        cfg_smb = str(cfg.get("motion_smb") or "").replace("\\", "/").strip("/")
        for lod_rank, lod in enumerate(("default", "high", "low")):
            if not groups.get(lod):
                continue
            coverage = effective_lod_node_coverage(asset, cfg, lod)
            if str(coverage.get("status") or "").upper() != "PASS":
                continue
            # Prefer a config that explicitly names the proven binding skeleton,
            # then the normal default/high/low order, then deterministic INX path.
            skeleton_rank = 0 if cfg_smb and cfg_smb.casefold() == skeleton.casefold() else 1
            candidates.append((skeleton_rank, lod_rank, inx.casefold(), lod, cfg, coverage))
    if candidates:
        candidates.sort(key=lambda row: (row[0], row[1], row[2]))
        _srank, _lrank, _name, lod, cfg, coverage = candidates[0]
        return {
            "strategy": "PAINT_RIGID_LOD",
            "skeleton_logical": str(cfg.get("motion_smb") or skeleton).replace("\\", "/"),
            "model_info_logical": str(cfg.get("inx") or "").replace("\\", "/"),
            "lod": lod,
            "single_tier_full_container": str(coverage.get("selection_mode") or "") == "SINGLE_TIER_FULL_CONTAINER",
            "coverage": coverage,
        }
    return {
        "strategy": "PAINT_RIGID_SKELETON_ONLY",
        "skeleton_logical": skeleton,
        "model_info_logical": "",
        "lod": "standalone",
        "single_tier_full_container": False,
        "coverage": {"status": "FALLBACK", "reason": "NO_MODEL_INFO_LOD_WITH_FULL_NODE_COVERAGE"},
    }


def build_smd_preview_plan(registry: Any, resolver: Any, rel: str) -> dict[str, Any] | None:
    """Build a source-backed *visual* preview plan.

    The catalog thumbnail intentionally follows the stable Paint/Edit import
    environment.  It never loads animation Actions.  For rigid models it first
    uses a source-backed INX/LOD with passing node coverage and otherwise falls
    back to the proven skeleton-only paint context.  That tolerance is preview-
    only; authoring/writers keep their stricter gates.
    """
    if pathlib.PurePosixPath(str(rel or "")).suffix.casefold() != ".smd":
        return None
    try:
        asset = registry.resolve(rel)
    except Exception:
        return None
    if asset.family not in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_STATIC"}:
        return None
    smd = resolver.resolve(asset.primary_path, required=False)
    if smd is None:
        return None

    if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
        context = _preview_rigid_context(asset)
        if context is None:
            return None
    else:
        context = {
            "strategy": "PAINT_STATIC",
            "skeleton_logical": "",
            "model_info_logical": "",
            "lod": "default",
            "single_tier_full_container": False,
            "coverage": {"status": "NOT_APPLICABLE"},
        }

    skeleton_logical = str(context.get("skeleton_logical") or "")
    model_info_logical = str(context.get("model_info_logical") or "")
    skeleton = resolver.resolve(skeleton_logical, required=False) if skeleton_logical else None
    model_info = resolver.resolve(model_info_logical, required=False) if model_info_logical else None
    if skeleton_logical and skeleton is None:
        return None
    if model_info_logical and model_info is None:
        # A preview may still use the proven skeleton-only Paint/Edit context.
        context = dict(context)
        context.update(
            strategy="PAINT_RIGID_SKELETON_ONLY",
            model_info_logical="",
            lod="standalone",
            single_tier_full_container=False,
            coverage={"status": "FALLBACK", "reason": "MODEL_INFO_PHYSICAL_FILE_MISSING"},
        )
        model_info_logical = ""
        model_info = None

    logical_deps = [asset.primary_path, *list(asset.textures or [])]
    if skeleton_logical:
        logical_deps.append(skeleton_logical)
    if model_info_logical:
        logical_deps.append(model_info_logical)
    physical_deps: list[str] = []
    for logical in logical_deps:
        p = resolver.resolve(logical, required=False)
        if p is not None:
            physical_deps.append(str(pathlib.Path(p).resolve()))
    return {
        "logical": asset.primary_path,
        "smd": str(pathlib.Path(smd).resolve()),
        "skeleton": str(pathlib.Path(skeleton).resolve()) if skeleton is not None else "",
        "skeleton_logical": skeleton_logical,
        "model_info": str(pathlib.Path(model_info).resolve()) if model_info is not None else "",
        "model_info_logical": model_info_logical,
        "lod": str(context.get("lod") or "default"),
        "strategy": str(context.get("strategy") or "PAINT_STATIC"),
        "single_tier_full_container": bool(context.get("single_tier_full_container")),
        "coverage": context.get("coverage") or {},
        "dependency_paths": sorted(set(physical_deps), key=str.casefold),
        "texture_logicals": list(asset.textures or []),
        "family": asset.family,
        "visual_mode": str(getattr(asset, "visual_mode", "") or ""),
        "preview_environment": "PAINT_EDIT",
        "load_actions": "none",
    }


class SmdPreviewManager:
    """Blender preview worker with a persistent, cheap catalog status index."""

    def __init__(self, project_root: pathlib.Path, client_root: pathlib.Path, *, workers: int = 1):
        self.project_root = pathlib.Path(project_root).resolve()
        self.client_root = pathlib.Path(client_root).resolve()
        self.root = self.project_root / "pt_build" / "previews" / "smd_catalog"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self._lock = threading.RLock()
        self._index_lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._queued: set[str] = set()
        self._queue: queue.Queue[tuple[str, dict[str, Any], str]] = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self.worker_count = max(1, min(4, int(workers)))
        self._index = self._load_index()
        self._index_mtime_ns = self._index_stamp()
        self._runtime_cache: dict[str, Any] | None = None
        self._runtime_cache_at = 0.0
        self._workers: list[threading.Thread] = []
        for i in range(self.worker_count):
            t = threading.Thread(target=self._run, name=f"pt-smd-preview-{i+1}", daemon=True)
            t.start()
            self._workers.append(t)

    @staticmethod
    def _key(logical: str) -> str:
        return str(logical or "").replace("\\", "/").strip("/").casefold()

    def _load_index(self) -> dict[str, Any]:
        raw = _json_load(self.index_path)
        if raw.get("format") == INDEX_FORMAT and isinstance(raw.get("items"), dict):
            return raw
        items: dict[str, Any] = {}
        for meta in self.root.glob("*/preview.json"):
            row = _json_load(meta)
            logical = str(row.get("asset") or "")
            if not logical:
                continue
            items[self._key(logical)] = {
                "asset": logical,
                "status": str(row.get("status") or "MISSING"),
                "detail": row.get("detail"),
                "cache_key": row.get("cache_key"),
                "updated_at": row.get("created_at") or row.get("finished_at") or meta.stat().st_mtime,
                "dependency_count": len(row.get("dependency_paths") or []),
            }
        data = {"format": INDEX_FORMAT, "updated_at": time.time(), "items": items}
        if items:
            self._write_index(data)
        return data

    @contextmanager
    def _index_process_lock(self):
        lock_path = self.root / "index.lock"
        with lock_path.open("a+b") as lock_stream:
            if fcntl is not None:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)

    def _index_stamp(self) -> int:
        try:
            st = self.index_path.stat()
            return (st.st_ino, st.st_size, st.st_mtime_ns)
        except OSError:
            return (0, 0, 0)

    def _sync_index_from_disk(self) -> None:
        """A batch runs in another process: don't serve the UI's startup snapshot."""
        stamp = self._index_stamp()
        if stamp != self._index_mtime_ns:
            raw = _json_load(self.index_path)
            if raw.get("format") == INDEX_FORMAT and isinstance(raw.get("items"), dict):
                self._index = raw
            self._index_mtime_ns = stamp

    def _write_index(self, data: dict[str, Any] | None = None) -> None:
        with self._index_lock:
            if data is not None:
                self._index = data
            self._index["format"] = INDEX_FORMAT
            self._index["updated_at"] = time.time()
            tmp = self.index_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.index_path)
            self._index_mtime_ns = self._index_stamp()

    def _index_update(self, logical: str, **fields: Any) -> None:
        with self._index_lock, self._index_process_lock():
            self._sync_index_from_disk()
            items = self._index.setdefault("items", {})
            row = dict(items.get(self._key(logical)) or {})
            row.update({"asset": logical, "updated_at": time.time(), **fields})
            items[self._key(logical)] = row
            self._write_index()

    def status_index(self) -> dict[str, dict[str, Any]]:
        with self._index_lock:
            self._sync_index_from_disk()
            return {k: dict(v) for k, v in (self._index.get("items") or {}).items() if isinstance(v, dict)}

    def mark_all_stale(self, detail: str = "REGISTRY_REINDEXED") -> int:
        changed = 0
        with self._index_lock, self._index_process_lock():
            self._sync_index_from_disk()
            for row in (self._index.get("items") or {}).values():
                if isinstance(row, dict) and row.get("status") == "READY":
                    row.update(status="STALE", detail=detail, updated_at=time.time())
                    changed += 1
            if changed:
                self._write_index()
        return changed

    def workspace(self, logical: str) -> pathlib.Path:
        return self.root / asset_workspace_name(logical)

    def _blender_runtime(self, *, max_age: float = 30.0) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if self._runtime_cache is not None and now - self._runtime_cache_at <= max_age:
                return dict(self._runtime_cache)
        info = blender_runtime_info(self.project_root, probe_version=True)
        with self._lock:
            self._runtime_cache = dict(info)
            self._runtime_cache_at = now
        return dict(info)

    def _cache_key(self, plan: dict[str, Any], blender_runtime: dict[str, Any]) -> str:
        deps = [[str(pathlib.Path(str(raw))), _stat(pathlib.Path(str(raw)))] for raw in plan.get("dependency_paths") or []]
        scripts = [
            self.project_root / "pt_smd_blender_import_v4_generic.py",
            pathlib.Path(__file__).resolve().parent / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py",
            pathlib.Path(__file__).resolve().parent / "legacy_runtime" / "pt_catalog_smd_render.py",
        ]
        payload = {
            "logical": str(plan.get("logical") or ""),
            "strategy": str(plan.get("strategy") or ""),
            "preview_environment": str(plan.get("preview_environment") or "PAINT_EDIT"),
            "lod": str(plan.get("lod") or "default"),
            "skeleton": str(plan.get("skeleton_logical") or ""),
            "model_info": str(plan.get("model_info_logical") or ""),
            "single_tier_full_container": bool(plan.get("single_tier_full_container")),
            "deps": deps,
            "scripts": [[str(p), _stat(p)] for p in scripts],
            "blender": {"command": list(blender_runtime.get("command") or []), "source": blender_runtime.get("source"), "version": blender_runtime.get("version")},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _public(self, state: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in state.items() if k not in {"plan", "cache_key"}}

    def classify(self, plan: dict[str, Any] | None) -> dict[str, Any]:
        if not plan or not plan.get("logical"):
            return {"format": FORMAT, "status": "UNSUPPORTED", "detail": "SMD_PREVIEW_PLAN_UNAVAILABLE"}
        logical = str(plan["logical"])
        rt = self._blender_runtime()
        cmd = list(rt.get("command") or [])
        if not rt.get("ready"):
            return {"format": FORMAT, "status": "UNAVAILABLE", "asset": logical, "detail": rt.get("detail"), "blender_source": rt.get("source"), "blender_version": rt.get("version"), "blender_command": cmd}
        ws = self.workspace(logical)
        preview, blend, meta = ws / "preview.png", ws / "model.blend", ws / "preview.json"
        cache_key = self._cache_key(plan, rt)
        old = _json_load(meta)
        common = {"format": FORMAT, "asset": logical, "dependency_count": len(plan.get("dependency_paths") or []), "cache_key": cache_key, "blender_source": rt.get("source"), "blender_version": rt.get("version"), "blender_command": cmd}
        if preview.is_file() and blend.is_file() and old.get("cache_key") == cache_key and old.get("status") == "READY":
            return {**common, "status": "READY", "image_url": "/api/smd-preview?path=" + __import__("urllib.parse").parse.quote(logical), "blend": str(blend), "source": "CACHE"}
        if old.get("status") == "FAILED" and old.get("cache_key") == cache_key:
            return {**common, "status": "FAILED", "detail": old.get("detail")}
        if preview.exists() or blend.exists() or old:
            return {**common, "status": "STALE", "detail": "DEPENDENCY_OR_RUNTIME_CHANGED"}
        return {**common, "status": "MISSING", "detail": "PREVIEW_NOT_GENERATED"}

    def request(self, plan: dict[str, Any] | None, *, retry: bool = False) -> dict[str, Any]:
        initial = self.classify(plan)
        if initial.get("status") in {"UNSUPPORTED", "UNAVAILABLE", "READY"}:
            if initial.get("asset"):
                self._index_update(str(initial["asset"]), status=initial.get("status"), detail=initial.get("detail"), dependency_count=initial.get("dependency_count", 0))
            return {k: v for k, v in initial.items() if k != "cache_key"}
        if initial.get("status") == "FAILED" and not retry:
            return {k: v for k, v in initial.items() if k != "cache_key"}
        assert plan is not None
        logical, key, cache_key = str(plan["logical"]), self._key(str(plan["logical"])), str(initial.get("cache_key") or "")
        with self._lock:
            current = self._states.get(key)
            if current and current.get("cache_key") == cache_key and current.get("status") in {"QUEUED", "RUNNING"}:
                return self._public(current)
            state = {"format": FORMAT, "status": "QUEUED", "asset": logical, "queued_at": time.time(), "detail": "Blender low-res preview queued", "dependency_count": len(plan.get("dependency_paths") or []), "blender_source": initial.get("blender_source"), "blender_version": initial.get("blender_version"), "blender_command": initial.get("blender_command"), "plan": dict(plan), "cache_key": cache_key}
            self._states[key] = state
            self._index_update(logical, status="QUEUED", detail=state["detail"], dependency_count=state["dependency_count"])
            if key not in self._queued:
                self._queued.add(key)
                try:
                    self._queue.put_nowait((key, dict(plan), cache_key))
                except queue.Full:
                    self._queued.discard(key)
                    state.update(status="FAILED", detail="SMD_PREVIEW_QUEUE_FULL")
                    self._index_update(logical, status="FAILED", detail=state["detail"], dependency_count=state["dependency_count"])
            return self._public(state)

    def render_now(self, plan: dict[str, Any] | None, *, retry: bool = True, force: bool = False, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        initial = self.classify(plan)
        if initial.get("status") in {"UNSUPPORTED", "UNAVAILABLE"} or (initial.get("status") == "READY" and not force) or (initial.get("status") == "FAILED" and not retry):
            return {k: v for k, v in initial.items() if k != "cache_key"}
        assert plan is not None
        key, cache_key = self._key(str(plan["logical"])), str(initial.get("cache_key") or "")
        self._render(key, dict(plan), cache_key, cancel_event=cancel_event)
        with self._lock:
            return self._public(dict(self._states.get(key) or {}))

    def image_path(self, logical: str) -> pathlib.Path:
        p = self.workspace(logical) / "preview.png"
        if not p.is_file():
            raise FileNotFoundError(logical)
        return p

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                key, plan, cache_key = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._render(key, plan, cache_key)
            finally:
                with self._lock:
                    self._queued.discard(key)
                self._queue.task_done()

    def _render(self, key: str, plan: dict[str, Any], cache_key: str, *, cancel_event: threading.Event | None = None) -> None:
        logical = str(plan["logical"])
        ws = self.workspace(logical); ws.mkdir(parents=True, exist_ok=True)
        blend, preview, meta = ws / "model.blend", ws / "preview.png", ws / "preview.json"
        import_log, render_log = ws / "import.log", ws / "render.log"
        rt = self._blender_runtime(); blender_cmd = list(rt.get("command") or [])
        with self._lock:
            state = self._states.setdefault(key, {})
            state.update(format=FORMAT, status="RUNNING", asset=logical, started_at=time.time(), cache_key=cache_key, plan=dict(plan))
        self._index_update(logical, status="RUNNING", detail="Blender rendering", dependency_count=len(plan.get("dependency_paths") or []))
        if not rt.get("ready"):
            self._fail(key, meta, cache_key, f"BLENDER_UNAVAILABLE:{rt.get('detail')}"); return
        renderer = pathlib.Path(__file__).resolve().parent / "legacy_runtime" / "pt_catalog_smd_render.py"

        def run_to_log(cmd: list[str], log: pathlib.Path, timeout: float) -> int:
            hdr = f"PT_ASSET_BLENDER source={rt.get('source')} version={rt.get('version') or 'unverified'} command={json.dumps(blender_cmd, ensure_ascii=False)}\n"
            with log.open("w", encoding="utf-8") as fh:
                fh.write(hdr); fh.flush()
                proc = subprocess.Popen(cmd, cwd=self.project_root, stdout=fh, stderr=subprocess.STDOUT, text=True)
                started = time.monotonic()
                while True:
                    rc = proc.poll()
                    if rc is not None:
                        return int(rc)
                    if cancel_event is not None and cancel_event.is_set():
                        proc.terminate()
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill(); proc.wait(timeout=3)
                        raise InterruptedError("SMD_PREVIEW_CANCELED")
                    if time.monotonic() - started > timeout:
                        proc.kill(); proc.wait(timeout=3)
                        raise TimeoutError(f"BLENDER_TIMEOUT:{int(timeout)}s")
                    time.sleep(0.15)

        def import_commands() -> list[tuple[str, list[str]]]:
            strategy = str(plan.get("strategy") or "PAINT_STATIC")
            generic = self.project_root / "pt_smd_blender_import_v4_generic.py"
            rigid = self.project_root / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py"
            base_tail = ["--smd", str(plan["smd"]), "--client-root", str(self.client_root), "--out", str(blend), "--no-pack"]
            rows: list[tuple[str, list[str]]] = []
            if strategy == "PAINT_STATIC":
                rows.append(("PAINT_STATIC", blender_cmd + ["--background", "--python-exit-code", "1", "--python", str(generic), "--", *base_tail]))
            elif strategy == "PAINT_RIGID_LOD":
                cmd = blender_cmd + ["--background", "--python-exit-code", "1", "--python", str(rigid), "--", *base_tail,
                    "--skeleton", str(plan["skeleton"]), "--model-info", str(plan["model_info"]), "--lod", str(plan.get("lod") or "default")]
                if plan.get("single_tier_full_container"):
                    cmd.append("--single-tier-full-container")
                rows.append(("PAINT_RIGID_LOD", cmd))
                # Preview-only tolerance: if an otherwise-proven INX context is
                # unsuitable for visual import, use the stable paint skeleton.
                rows.append(("PAINT_RIGID_SKELETON_ONLY_FALLBACK", blender_cmd + ["--background", "--python-exit-code", "1", "--python", str(rigid), "--", *base_tail, "--skeleton", str(plan["skeleton"])]))
            elif strategy == "PAINT_RIGID_SKELETON_ONLY":
                rows.append((strategy, blender_cmd + ["--background", "--python-exit-code", "1", "--python", str(rigid), "--", *base_tail, "--skeleton", str(plan["skeleton"])]))
            return rows

        try:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("SMD_PREVIEW_CANCELED")
            chosen_strategy = None
            attempt_errors: list[str] = []
            for attempt, cmd in import_commands():
                try:
                    if blend.exists(): blend.unlink()
                    attempt_log = import_log if not attempt_errors else ws / f"import_{len(attempt_errors)+1}_{attempt.lower()}.log"
                    rc = run_to_log(cmd, attempt_log, 180)
                    if rc == 0 and blend.is_file():
                        chosen_strategy = attempt
                        break
                    attempt_errors.append(f"{attempt}:rc={rc}")
                except InterruptedError:
                    raise
                except Exception as exc:
                    attempt_errors.append(f"{attempt}:{type(exc).__name__}:{exc}")
            if chosen_strategy is None:
                raise RuntimeError("IMPORT_FAILED:" + " | ".join(attempt_errors[-4:]))
            rcmd = blender_cmd + ["--background", str(blend), "--python-exit-code", "1", "--python", str(renderer), "--", "--out", str(preview), "--size", "320"]
            rc2 = run_to_log(rcmd, render_log, 120)
            if rc2 != 0 or not preview.is_file(): raise RuntimeError(f"RENDER_FAILED:{rc2}")
            payload = {"format": FORMAT, "status": "READY", "asset": logical, "cache_key": cache_key, "created_at": time.time(), "blend": str(blend), "preview": str(preview), "dependency_paths": list(plan.get("dependency_paths") or []), "model_info": plan.get("model_info_logical"), "skeleton": plan.get("skeleton_logical"), "preview_environment": "PAINT_EDIT", "planned_strategy": plan.get("strategy"), "import_strategy": chosen_strategy, "load_actions": "none", "client_modified": False, "blender": {"source": rt.get("source"), "version": rt.get("version"), "command": blender_cmd, "detail": rt.get("detail")}}
            tmp = meta.with_suffix(".json.tmp"); tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(tmp, meta)
            with self._lock:
                self._states[key] = {"format": FORMAT, "status": "READY", "asset": logical, "cache_key": cache_key, "image_url": "/api/smd-preview?path=" + __import__("urllib.parse").parse.quote(logical), "blend": str(blend), "dependency_count": len(plan.get("dependency_paths") or []), "finished_at": time.time(), "source": "BLENDER", "preview_environment": "PAINT_EDIT", "import_strategy": chosen_strategy, "blender_source": rt.get("source"), "blender_version": rt.get("version"), "blender_command": blender_cmd}
            self._index_update(logical, status="READY", detail=None, cache_key=cache_key, dependency_count=len(plan.get("dependency_paths") or []), preview_environment="PAINT_EDIT", import_strategy=chosen_strategy, blender_version=rt.get("version"))
        except InterruptedError as exc:
            self._cancel(key, meta, cache_key, str(exc))
        except Exception as exc:
            self._fail(key, meta, cache_key, f"{type(exc).__name__}:{exc}")

    def _cancel(self, key: str, meta: pathlib.Path, cache_key: str, detail: str = "SMD_PREVIEW_CANCELED") -> None:
        state = self._states.get(key) or {}
        payload = {"format": FORMAT, "status": "CANCELED", "asset": state.get("asset"), "cache_key": cache_key, "detail": detail, "finished_at": time.time(), "client_modified": False}
        try:
            tmp = meta.with_suffix(".json.tmp"); tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(tmp, meta)
        except Exception: pass
        with self._lock:
            state.update(payload); self._states[key] = state
        if state.get("asset"):
            self._index_update(str(state["asset"]), status="MISSING", detail="PREVIEW_CANCELED_RETRYABLE", cache_key=None, dependency_count=len((state.get("plan") or {}).get("dependency_paths") or []))

    def _fail(self, key: str, meta: pathlib.Path, cache_key: str, detail: str) -> None:
        state = self._states.get(key) or {}
        payload = {"format": FORMAT, "status": "FAILED", "asset": state.get("asset"), "cache_key": cache_key, "detail": detail, "finished_at": time.time(), "client_modified": False}
        try:
            tmp = meta.with_suffix(".json.tmp"); tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(tmp, meta)
        except Exception: pass
        with self._lock:
            state.update(payload); self._states[key] = state
        if state.get("asset"):
            self._index_update(str(state["asset"]), status="FAILED", detail=detail, cache_key=cache_key, dependency_count=len((state.get("plan") or {}).get("dependency_paths") or []))
