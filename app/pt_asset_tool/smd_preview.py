from __future__ import annotations

import hashlib
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

FORMAT = "PT_CATALOG_SMD_PREVIEW_V1"


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


class SmdPreviewManager:
    """Single-worker, deduplicated Blender preview queue for catalog SMDs.

    Source/client assets remain read-only. Generated .blend, PNG and metadata are
    stored below pt_build/previews/smd_catalog. The cache key includes every
    dependency used to construct the model so a changed SMD/INX/SMB/texture
    invalidates the preview without rescanning the client.
    """

    def __init__(self, project_root: pathlib.Path, client_root: pathlib.Path):
        self.project_root = pathlib.Path(project_root).resolve()
        self.client_root = pathlib.Path(client_root).resolve()
        self.root = self.project_root / "pt_build" / "previews" / "smd_catalog"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._queued: set[str] = set()
        self._queue: queue.Queue[tuple[str, dict[str, Any], str]] = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="pt-smd-preview", daemon=True)
        self._worker.start()

    @staticmethod
    def _key(logical: str) -> str:
        return str(logical or "").replace("\\", "/").strip("/").casefold()

    def workspace(self, logical: str) -> pathlib.Path:
        return self.root / asset_workspace_name(logical)

    def _cache_key(self, plan: dict[str, Any], blender_runtime: dict[str, Any]) -> str:
        deps = []
        for raw in plan.get("dependency_paths") or []:
            p = pathlib.Path(str(raw))
            deps.append([str(p), _stat(p)])
        scripts = [
            self.project_root / "pt_smd_blender_import_v4_generic.py",
            pathlib.Path(__file__).resolve().parent / "legacy_runtime" / "pt_catalog_smd_render.py",
        ]
        payload = {
            "logical": str(plan.get("logical") or ""),
            "lod": str(plan.get("lod") or "default"),
            "deps": deps,
            "scripts": [[str(p), _stat(p)] for p in scripts],
            "blender": {
                "command": list(blender_runtime.get("command") or []),
                "source": blender_runtime.get("source"),
                "version": blender_runtime.get("version"),
            },
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _public(self, state: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in state.items() if k not in {"plan", "cache_key"}}

    def request(self, plan: dict[str, Any] | None, *, retry: bool = False) -> dict[str, Any]:
        if not plan or not plan.get("logical"):
            return {"format": FORMAT, "status": "UNSUPPORTED", "detail": "SMD_PREVIEW_PLAN_UNAVAILABLE"}
        logical = str(plan["logical"])
        key = self._key(logical)
        blender_runtime = blender_runtime_info(self.project_root, probe_version=True)
        blender_cmd = list(blender_runtime.get("command") or [])
        if not blender_runtime.get("ready"):
            return {
                "format": FORMAT, "status": "UNAVAILABLE", "asset": logical,
                "detail": blender_runtime.get("detail"),
                "blender_source": blender_runtime.get("source"),
                "blender_version": blender_runtime.get("version"),
                "blender_command": blender_cmd,
            }
        workspace = self.workspace(logical)
        preview = workspace / "preview.png"
        blend = workspace / "model.blend"
        meta = workspace / "preview.json"
        cache_key = self._cache_key(plan, blender_runtime)
        old = _json_load(meta)
        if preview.is_file() and blend.is_file() and old.get("format") == FORMAT and old.get("cache_key") == cache_key and old.get("status") == "READY":
            return {
                "format": FORMAT, "status": "READY", "asset": logical,
                "image_url": "/api/smd-preview?path=" + __import__("urllib.parse").parse.quote(logical),
                "blend": str(blend), "dependency_count": len(plan.get("dependency_paths") or []),
                "source": "CACHE",
                "blender_source": blender_runtime.get("source"),
                "blender_version": blender_runtime.get("version"),
                "blender_command": blender_cmd,
            }
        with self._lock:
            current = self._states.get(key)
            if current and current.get("cache_key") == cache_key:
                if current.get("status") in {"QUEUED", "RUNNING"}:
                    return self._public(current)
                if current.get("status") == "FAILED" and not retry:
                    return self._public(current)
            state = {
                "format": FORMAT, "status": "QUEUED", "asset": logical,
                "queued_at": time.time(), "detail": "Blender low-res preview queued",
                "dependency_count": len(plan.get("dependency_paths") or []),
                "blender_source": blender_runtime.get("source"),
                "blender_version": blender_runtime.get("version"),
                "blender_command": blender_cmd,
                "plan": dict(plan), "cache_key": cache_key,
            }
            self._states[key] = state
            if key not in self._queued:
                self._queued.add(key)
                try:
                    self._queue.put_nowait((key, dict(plan), cache_key))
                except queue.Full:
                    self._queued.discard(key)
                    state["status"] = "FAILED"
                    state["detail"] = "SMD_PREVIEW_QUEUE_FULL"
            return self._public(state)

    def image_path(self, logical: str) -> pathlib.Path:
        path = self.workspace(logical) / "preview.png"
        if not path.is_file():
            raise FileNotFoundError(logical)
        return path

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

    def _render(self, key: str, plan: dict[str, Any], cache_key: str) -> None:
        logical = str(plan["logical"])
        workspace = self.workspace(logical)
        workspace.mkdir(parents=True, exist_ok=True)
        blend = workspace / "model.blend"
        preview = workspace / "preview.png"
        meta = workspace / "preview.json"
        import_log = workspace / "import.log"
        render_log = workspace / "render.log"
        blender_runtime = blender_runtime_info(self.project_root, probe_version=True)
        blender_cmd = list(blender_runtime.get("command") or [])
        with self._lock:
            state = self._states.setdefault(key, {})
            state.update({"format": FORMAT, "status": "RUNNING", "asset": logical, "started_at": time.time(), "cache_key": cache_key, "plan": dict(plan)})
        if not blender_runtime.get("ready"):
            self._fail(key, meta, cache_key, f"BLENDER_UNAVAILABLE:{blender_runtime.get('detail')}")
            return
        importer = self.project_root / "pt_smd_blender_import_v4_generic.py"
        renderer = pathlib.Path(__file__).resolve().parent / "legacy_runtime" / "pt_catalog_smd_render.py"
        cmd = list(blender_cmd) + [
            "--background", "--python-exit-code", "1", "--python", str(importer), "--",
            "--smd", str(plan["smd"]), "--client-root", str(self.client_root),
            "--out", str(blend), "--lod", str(plan.get("lod") or "default"),
            "--cache", str(workspace / "texture_cache"),
        ]
        if plan.get("skeleton"):
            cmd += ["--skeleton", str(plan["skeleton"])]
        if plan.get("model_info"):
            cmd += ["--model-info", str(plan["model_info"])]
        try:
            runtime_header = (
                f"PT_ASSET_BLENDER source={blender_runtime.get('source')} "
                f"version={blender_runtime.get('version') or 'unverified'} "
                f"command={json.dumps(blender_cmd, ensure_ascii=False)}\n"
            )
            p = subprocess.run(cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180, check=False)
            import_log.write_text(runtime_header + (p.stdout or ""), encoding="utf-8")
            if p.returncode != 0 or not blend.is_file():
                raise RuntimeError(f"IMPORT_FAILED:{p.returncode}")
            render_cmd = list(blender_cmd) + [
                "--background", str(blend), "--python-exit-code", "1", "--python", str(renderer), "--",
                "--out", str(preview), "--size", "320",
            ]
            p2 = subprocess.run(render_cmd, cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120, check=False)
            render_log.write_text(runtime_header + (p2.stdout or ""), encoding="utf-8")
            if p2.returncode != 0 or not preview.is_file():
                raise RuntimeError(f"RENDER_FAILED:{p2.returncode}")
            payload = {
                "format": FORMAT, "status": "READY", "asset": logical, "cache_key": cache_key,
                "created_at": time.time(), "blend": str(blend), "preview": str(preview),
                "dependency_paths": list(plan.get("dependency_paths") or []),
                "model_info": plan.get("model_info_logical"), "skeleton": plan.get("skeleton_logical"),
                "client_modified": False,
                "blender": {
                    "source": blender_runtime.get("source"),
                    "version": blender_runtime.get("version"),
                    "command": blender_cmd,
                    "detail": blender_runtime.get("detail"),
                },
            }
            tmp = meta.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, meta)
            with self._lock:
                self._states[key] = {
                    "format": FORMAT, "status": "READY", "asset": logical, "cache_key": cache_key,
                    "image_url": "/api/smd-preview?path=" + __import__("urllib.parse").parse.quote(logical),
                    "blend": str(blend), "dependency_count": len(plan.get("dependency_paths") or []),
                    "finished_at": time.time(), "source": "BLENDER",
                    "blender_source": blender_runtime.get("source"),
                    "blender_version": blender_runtime.get("version"),
                    "blender_command": blender_cmd,
                }
        except Exception as exc:
            self._fail(key, meta, cache_key, f"{type(exc).__name__}:{exc}")

    def _fail(self, key: str, meta: pathlib.Path, cache_key: str, detail: str) -> None:
        state = self._states.get(key) or {}
        payload = {
            "format": FORMAT, "status": "FAILED", "asset": state.get("asset"),
            "cache_key": cache_key, "detail": detail, "finished_at": time.time(), "client_modified": False,
        }
        try:
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        with self._lock:
            state.update(payload)
            self._states[key] = state
