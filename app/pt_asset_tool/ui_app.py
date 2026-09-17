from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .ui_actions import ACTION_SPECS, build_command, public_action_specs
from .app_config import discover_client_root, load_config
from .ui_catalog import CatalogIndex, UIStateStore, UI_VERSION
from .ui_capabilities import capabilities_for_asset
from .profile_registry import CharacterProfileRegistry
from .ui_image import PreviewDecodeError, preview_image_bytes
from .ui_jobs import JobManager
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .entity_catalog import entity_detail, load_entity_seed, query_entities
from .server_ui import build_server_ui_summary, server_report_rows
from .app_config import (
    save_server_root, clear_server_root,
    save_source_root, clear_source_root,
    save_reference_source_root, clear_reference_source_root,
    save_contract_donor_clients, configured_contract_donor_clients,
    save_contract_donor_servers, configured_contract_donor_servers,
)
from .validation import rigid_model_info_options
from .server_field_editor import inspect_field_metadata, stage_spm_text, stage_spp_records, stage_spc_clone
from .general_asset_census import query_general_asset_census
from .source_catalog import configured_source_roots
from .texture_upscale import capability_status as texture_upscale_capability_status

LOOPBACKS = {"127.0.0.1", "localhost", "::1"}
ARM_PHRASE = "ARM BUILD WRITES"


def _discover_client_root(project_root: pathlib.Path) -> pathlib.Path:
    return discover_client_root(project_root)


def _backend_version(project_root: pathlib.Path) -> str:
    try:
        p = subprocess.run(
            ["python3", str(project_root / "pt_asset.py"), "--version"],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
        return (p.stdout or "").strip().splitlines()[-1][:80] if (p.stdout or "").strip() else "unknown"
    except Exception:
        return "unknown"


def _reports(project_root: pathlib.Path, limit: int = 80) -> list[dict[str, Any]]:
    root = project_root / "pt_build"
    if not root.is_dir():
        return []
    # Most application reports live below pt_build/pt_asset_tool and, now,
    # pt_build/blender_edits. A root-only glob made the Reports tab appear empty.
    files = []
    for candidate in root.rglob("*.json"):
        try:
            if candidate.name.startswith("ui_state_"):
                continue
            if candidate.is_file():
                files.append(candidate)
        except OSError:
            continue
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    rows = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        item: dict[str, Any] = {
            "name": rel,
            "path": str(p),
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "status": None,
            "format": None,
            "release_version": None,
        }
        try:
            if p.stat().st_size <= 16 * 1024 * 1024:
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    item["status"] = d.get("status")
                    item["format"] = d.get("format")
                    item["release_version"] = d.get("release_version") or d.get("overlay_version") or d.get("core_version")
        except Exception:
            pass
        rows.append(item)
    return rows


def _path_inside(root: pathlib.Path, rel: str) -> pathlib.Path:
    relp = pathlib.PurePosixPath(rel.replace("\\", "/").lstrip("/"))
    if any(part in {"", ".", ".."} for part in relp.parts):
        raise ValueError("INVALID_PATH")
    p = (root / pathlib.Path(*relp.parts)).resolve()
    if p != root and root not in p.parents:
        raise ValueError("PATH_ESCAPE")
    return p


class UIContext:
    def __init__(self, project_root: pathlib.Path, client_root: pathlib.Path, server_root: pathlib.Path | None = None):
        self.project_root = project_root.resolve()
        self.client_root = client_root.resolve()
        self.static_root = pathlib.Path(__file__).resolve().parent / "ui_static"
        self.token = secrets.token_urlsafe(32)
        self.backend_version = _backend_version(self.project_root)
        self.state = UIStateStore(self.project_root / "pt_build" / "ui_state_v0100.json")
        self.catalog = CatalogIndex(self.client_root, self.state)
        self.catalog.rebuild()
        self.entity_seed = load_entity_seed(self.project_root)
        self.settings = Settings.discover(self.project_root, self.client_root, server_root)
        self.server_root = self.settings.server_root
        # Use the same bounded source auto-discovery as the CLI so a freshly
        # extracted FULL release does not force re-entry of known Summit roots.
        trees = configured_source_roots(self.project_root)
        tree_map = {t.source_id: t for t in trees}
        self.source_root = tree_map.get("CURRENT_SOURCE").root if tree_map.get("CURRENT_SOURCE") else None
        self.reference_source_root = tree_map.get("EU_REFERENCE_SOURCE").root if tree_map.get("EU_REFERENCE_SOURCE") else None
        self.contract_donor_clients = configured_contract_donor_clients(self.project_root)
        self.contract_donor_servers = configured_contract_donor_servers(self.project_root)
        self.resolver = ClientResolver(self.client_root)
        self._registry: AssetRegistry | None = None
        self._registry_error: str | None = None
        self._registry_lock = threading.RLock()
        self.jobs = JobManager(
            self.project_root, max_concurrent=2,
            env_overrides={
                "PT_PROJECT_ROOT": str(self.project_root),
                "PT_CLIENT_ROOT": str(self.client_root),
                **({"PT_SERVER_ROOT": str(self.server_root)} if self.server_root else {}),
                **({"PT_SOURCE_ROOT": str(self.source_root)} if self.source_root else {}),
                **({"PT_REFERENCE_SOURCE_ROOT": str(self.reference_source_root)} if self.reference_source_root else {}),
            },
        )
        try:
            self.profile_registry = CharacterProfileRegistry(self.project_root / "pt_build" / "state" / "character_profiles")
        except Exception:
            self.profile_registry = None
        self.write_armed_until = 0.0
        self.server: ThreadingHTTPServer | None = None

    def set_server_root(self, value: pathlib.Path | None) -> None:
        self.server_root = value.resolve() if value is not None else None
        self.settings = Settings.discover(self.project_root, self.client_root, self.server_root)
        if self.server_root:
            self.jobs.env_overrides["PT_SERVER_ROOT"] = str(self.server_root)
        else:
            self.jobs.env_overrides.pop("PT_SERVER_ROOT", None)

    def set_contract_sources(
        self,
        source_root: pathlib.Path | None,
        reference_source_root: pathlib.Path | None,
        donor_clients: list[str] | None = None,
        donor_servers: list[str] | None = None,
    ) -> None:
        self.source_root = source_root.resolve() if source_root is not None else None
        self.reference_source_root = reference_source_root.resolve() if reference_source_root is not None else None
        if donor_clients is not None:
            self.contract_donor_clients = list(donor_clients)
        if donor_servers is not None:
            self.contract_donor_servers = list(donor_servers)
        if self.source_root:
            self.jobs.env_overrides["PT_SOURCE_ROOT"] = str(self.source_root)
        else:
            self.jobs.env_overrides.pop("PT_SOURCE_ROOT", None)
        if self.reference_source_root:
            self.jobs.env_overrides["PT_REFERENCE_SOURCE_ROOT"] = str(self.reference_source_root)
        else:
            self.jobs.env_overrides.pop("PT_REFERENCE_SOURCE_ROOT", None)

    def invalidate_registry(self) -> None:
        with self._registry_lock:
            self._registry = None
            self._registry_error = None

    def registry(self) -> AssetRegistry:
        with self._registry_lock:
            if self._registry is not None:
                return self._registry
            if self._registry_error is not None:
                raise RuntimeError(self._registry_error)
            try:
                self._registry = AssetRegistry(
                    self.settings.inventory, self.settings.pairing, resolver=self.resolver
                )
                return self._registry
            except Exception as exc:
                self._registry_error = f"{type(exc).__name__}:{exc}"
                raise

    def asset_detail(self, rel: str) -> dict[str, Any] | None:
        row = self.catalog.get_asset(rel)
        if not row:
            return None
        row["registry_asset"] = False
        row["inventory_record_present"] = False
        row["capability_notes"] = {}
        try:
            reg = self.registry()
            record = reg.record_for_path(rel)
            row["inventory_record_present"] = bool(record)
            if record:
                row["inventory_kind"] = record.get("kind")
                row["inventory_family"] = record.get("compatibility_family")
                row["inventory_category"] = record.get("category_hint")
            try:
                asset = reg.resolve(rel)
            except KeyError:
                asset = None
            if asset is not None:
                row["registry_asset"] = True
                row["asset_id"] = asset.asset_id
                row["family"] = asset.family
                row["kind"] = asset.kind
                row["character_profiles"] = (
                    self.profile_registry.match_asset(asset.primary_path)
                    if self.profile_registry is not None else []
                )
                row["binding_mode"] = asset.binding_mode
                row["binding_source"] = asset.binding_source
                row["rigid_binding_ready"] = asset.rigid_binding_ready
                row["animation_binding_ready"] = asset.animation_binding_ready
                head_candidates = []
                if asset.category == "CHARACTER" and asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
                    try:
                        head_candidates = reg.head_candidates(asset)
                    except Exception:
                        head_candidates = []
                row["head_candidates"] = head_candidates[:50]
                row["head_candidate_count"] = len(head_candidates)
                dependency_status = reg.physical_dependency_status(asset)
                row["physical_dependency_status"] = dependency_status
                row["rigid_binding_ready_physical"] = bool(dependency_status.get("rigid_binding_ready_physical"))
                row["animation_binding_ready_physical"] = bool(dependency_status.get("animation_binding_ready_physical"))
                physical = self.resolver.resolve(asset.primary_path, required=False)
                caps, notes = capabilities_for_asset(asset, pathlib.Path(physical) if physical else None)
                # Semantic registry readiness is not enough when this configured
                # client is partial/missing a resolved INX/SMB dependency.
                if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
                    if not row["rigid_binding_ready_physical"]:
                        caps = [x for x in caps if x not in {"import_blender", "validate_structural", "validate_visual", "validate_animation", "diagnose_animation"}]
                        notes["import_blender"] = "MISSING_PHYSICAL_BINDING_DEPENDENCY"
                    if not row["animation_binding_ready_physical"]:
                        caps = [x for x in caps if x not in {"motions", "validate_animation", "diagnose_animation"}]
                        notes["motions"] = "MISSING_PHYSICAL_ANIMATION_DEPENDENCY"
                        notes["validate_animation"] = "MISSING_PHYSICAL_ANIMATION_DEPENDENCY"
                        notes["diagnose_animation"] = "MISSING_PHYSICAL_ANIMATION_DEPENDENCY"
                if head_candidates:
                    caps = sorted(set(caps) | {"heads"})
                row["capabilities"] = caps
                row["capability_notes"] = notes
            else:
                # Files such as INX/SMB/WAV remain useful catalog/inspection
                # entries but do not inherit model-only actions.
                row["capabilities"] = ["inspect"]
        except Exception as exc:
            row["registry_error"] = f"{type(exc).__name__}:{exc}"
            row["capabilities"] = ["inspect"]
        return row

    @property
    def write_armed(self) -> bool:
        return time.time() < self.write_armed_until

    def arm(self, seconds: int = 900) -> None:
        self.write_armed_until = time.time() + max(60, min(3600, seconds))

    def disarm(self) -> None:
        self.write_armed_until = 0.0


class UIHandler(BaseHTTPRequestHandler):
    server_version = "PTAssetUI/0.12"

    @property
    def ctx(self) -> UIContext:
        return self.server.ctx  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep console quiet; job output stays in the UI job logs.
        return

    def _json(self, status: int, data: Any) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, code: str, detail: str | None = None) -> None:
        self._json(status, {"ok": False, "error": code, "detail": detail})

    def _body_json(self) -> dict[str, Any]:
        try:
            n = min(1024 * 1024, max(0, int(self.headers.get("Content-Length", "0"))))
            raw = self.rfile.read(n)
            obj = json.loads(raw.decode("utf-8")) if raw else {}
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _require_token(self) -> bool:
        if secrets.compare_digest(self.headers.get("X-PT-UI-Token", ""), self.ctx.token):
            return True
        self._error(403, "INVALID_UI_TOKEN")
        return False

    def do_GET(self) -> None:
        u = urllib.parse.urlparse(self.path)
        path = u.path
        q = urllib.parse.parse_qs(u.query)
        if path == "/":
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/bootstrap":
            s = self.ctx.catalog.stats
            return self._json(200, {
                "ok": True,
                "ui_version": UI_VERSION,
                "backend_version": self.ctx.backend_version,
                "project_root": str(self.ctx.project_root),
                "client_root": str(self.ctx.client_root),
                "server_root": str(self.ctx.server_root) if self.ctx.server_root else None,
                "source_root": str(self.ctx.source_root) if self.ctx.source_root else None,
                "reference_source_root": str(self.ctx.reference_source_root) if self.ctx.reference_source_root else None,
                "contract_donor_clients": list(self.ctx.contract_donor_clients),
                "contract_donor_servers": list(self.ctx.contract_donor_servers),
                "token": self.ctx.token,
                "catalog": {"file_count": s.file_count, "total_bytes": s.total_bytes, "indexed_at": s.indexed_at},
                "write_armed": self.ctx.write_armed,
                "write_armed_until": self.ctx.write_armed_until,
                "actions": public_action_specs(),
                "optional_capabilities": {"texture_upscale": texture_upscale_capability_status()},
                "safety": {
                    "client_source_write": False,
                    "build_write_requires_arm": True,
                    "arm_phrase": ARM_PHRASE,
                    "server_source_write": False,
                    "persistence_write": False,
                    "note": "The UI never deploys into the client or server roots. Backend writers remain authoritative and fail-closed.",
                },
            })
        if path == "/api/catalog":
            try:
                return self._json(200, {"ok": True, **self.ctx.catalog.query(
                    q=_one(q, "q"), category=_one(q, "category"), folder=_one(q, "folder"),
                    role=_one(q, "role"), ext=_one(q, "ext"),
                    favorites=_one(q, "favorites") in {"1", "true", "yes"},
                    page=int(_one(q, "page") or 1), page_size=int(_one(q, "page_size") or 100),
                )})
            except Exception as exc:
                return self._error(400, "CATALOG_QUERY_FAILED", str(exc))
        if path == "/api/asset":
            rel = _one(q, "path")
            row = self.ctx.asset_detail(rel)
            return self._json(200, {"ok": True, "asset": row}) if row else self._error(404, "ASSET_NOT_FOUND")
        if path == "/api/entities":
            try:
                try:
                    registry = self.ctx.registry()
                    registry_error = None
                except Exception as exc:
                    registry = None
                    registry_error = f"{type(exc).__name__}:{exc}"
                report = query_entities(
                    self.ctx.catalog.assets,
                    self.ctx.entity_seed,
                    group=_one(q, "group"),
                    q=_one(q, "q"),
                    limit=int(_one(q, "limit") or 500),
                    registry=registry,
                )
                if registry_error:
                    report["registry_error"] = registry_error
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "ENTITY_QUERY_FAILED", str(exc))
        if path == "/api/entity":
            try:
                try:
                    registry = self.ctx.registry()
                    registry_error = None
                except Exception as exc:
                    registry = None
                    registry_error = f"{type(exc).__name__}:{exc}"
                report = entity_detail(
                    self.ctx.catalog.assets,
                    self.ctx.entity_seed,
                    _one(q, "key"),
                    registry=registry,
                )
                if report is None:
                    return self._error(404, "ENTITY_NOT_FOUND")
                if registry_error:
                    report["registry_error"] = registry_error
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "ENTITY_DETAIL_FAILED", str(exc))
        if path == "/api/contracts":
            try:
                out_dir = self.ctx.project_root / "pt_build" / "asset_contracts"
                def load_report(name: str):
                    p = out_dir / name
                    if not p.is_file():
                        return None
                    try:
                        return json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        return {"status": "INVALID_REPORT", "path": str(p)}
                def load_json_path(p: pathlib.Path):
                    if not p.is_file():
                        return None
                    try:
                        return json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        return {"status": "INVALID_REPORT", "path": str(p)}

                player_aggregate = load_json_path(self.ctx.project_root / "pt_build" / "aggregate" / "player_classes" / "all" / "manifest.json")
                summit_superset = load_json_path(self.ctx.project_root / "pt_build" / "aggregate" / "summit" / "all" / "manifest.json")
                client_superset = load_json_path(self.ctx.project_root / "pt_build" / "aggregate" / "client_superset" / "all" / "manifest.json")
                server_superset = load_json_path(self.ctx.project_root / "pt_build" / "aggregate" / "server_superset" / "all" / "manifest.json")
                inventory = load_json_path(self.ctx.project_root / "pt_build" / "devtest" / "server_inventory" / "result.json")
                if isinstance(summit_superset, dict):
                    reasons = []
                    if isinstance(client_superset, dict):
                        if pathlib.Path(str(client_superset.get("target_root") or "")).resolve() != self.ctx.client_root.resolve():
                            reasons.append("CLIENT_ROOT_CHANGED")
                        if int(client_superset.get("target_canonical_path_count") or -1) != int(self.ctx.catalog.stats.file_count):
                            reasons.append("CLIENT_FILE_COUNT_CHANGED")
                    if isinstance(server_superset, dict) and self.ctx.server_root is not None:
                        if pathlib.Path(str(server_superset.get("target_root") or "")).resolve() != self.ctx.server_root.resolve():
                            reasons.append("SERVER_ROOT_CHANGED")
                        if isinstance(inventory, dict) and inventory.get("total_files") is not None:
                            if int(server_superset.get("target_canonical_path_count") or -1) != int(inventory.get("total_files") or 0):
                                reasons.append("SERVER_FILE_COUNT_CHANGED")
                    summit_superset["_freshness"] = {"status": "STALE" if reasons else "FRESH", "reasons": reasons}
                return self._json(200, {
                    "ok": True,
                    "source_root": str(self.ctx.source_root) if self.ctx.source_root else None,
                    "reference_source_root": str(self.ctx.reference_source_root) if self.ctx.reference_source_root else None,
                    "donor_clients": list(self.ctx.contract_donor_clients),
                    "donor_servers": list(self.ctx.contract_donor_servers),
                    "source_contracts": load_report("source_contract_census.json"),
                    "player_class_contracts": load_report("player_class_contract_census.json"),
                    "player_class_aggregate": player_aggregate,
                    "summit_superset": summit_superset,
                    "general_asset_census": load_json_path(self.ctx.project_root / "pt_build" / "general_asset_census" / "result.json"),
                })
            except Exception as exc:
                return self._error(400, "CONTRACT_SUMMARY_FAILED", str(exc))
        if path == "/api/general-census":
            try:
                report = query_general_asset_census(
                    self.ctx.project_root,
                    query=_one(q, "q"),
                    side=_one(q, "side"),
                    decision=_one(q, "decision"),
                    family=_one(q, "family"),
                    offset=int(_one(q, "offset") or 0),
                    limit=int(_one(q, "limit") or 200),
                )
                summary = report.get("summary") if isinstance(report, dict) else None
                if isinstance(summary, dict):
                    roots_match = (
                        pathlib.Path(str(summary.get("client_root") or "")).resolve() == self.ctx.client_root.resolve()
                        and self.ctx.server_root is not None
                        and pathlib.Path(str(summary.get("server_root") or "")).resolve() == self.ctx.server_root.resolve()
                    )
                    report["freshness"] = "FRESH_ROOTS" if roots_match else "STALE_ROOTS"
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "GENERAL_CENSUS_QUERY_FAILED", str(exc))
        if path == "/api/server":
            try:
                return self._json(200, {"ok": True, **build_server_ui_summary(
                    self.ctx.project_root, self.ctx.server_root, self.ctx.client_root
                )})
            except Exception as exc:
                return self._error(400, "SERVER_SUMMARY_FAILED", str(exc))
        if path == "/api/server/report":
            try:
                report = server_report_rows(
                    self.ctx.project_root,
                    _one(q, "kind"),
                    query=_one(q, "q"),
                    status=_one(q, "status"),
                    reason=_one(q, "reason"),
                    offset=int(_one(q, "offset") or 0),
                    limit=int(_one(q, "limit") or 200),
                )
                return self._json(200, {"ok": True, **report})
            except ValueError as exc:
                return self._error(400, "SERVER_REPORT_QUERY_INVALID", str(exc))
            except Exception as exc:
                return self._error(400, "SERVER_REPORT_QUERY_FAILED", str(exc))
        if path == "/api/server/field-editor":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
            rel = _one(q, "path").strip()
            if not rel:
                return self._error(400, "FIELD_PATH_REQUIRED")
            try:
                report = inspect_field_metadata(self.ctx.project_root, self.ctx.server_root, rel)
                return self._json(200, {"ok": True, "field": report})
            except FileNotFoundError as exc:
                return self._error(404, "FIELD_METADATA_NOT_FOUND", str(exc))
            except ValueError as exc:
                return self._error(400, "FIELD_METADATA_INVALID", str(exc))
            except Exception as exc:
                return self._error(500, "FIELD_METADATA_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/jobs":
            return self._json(200, {"ok": True, "jobs": self.ctx.jobs.list(int(_one(q, "limit") or 50))})
        if path == "/api/job":
            job = self.ctx.jobs.get(_one(q, "id"))
            return self._json(200, {"ok": True, "job": job}) if job else self._error(404, "JOB_NOT_FOUND")
        if path == "/api/reports":
            return self._json(200, {"ok": True, "reports": _reports(self.ctx.project_root)})
        if path == "/api/report":
            name = _one(q, "name").strip().replace("\\", "/")
            if not name or not name.lower().endswith(".json"):
                return self._error(400, "INVALID_REPORT_NAME")
            try:
                report_path = _path_inside((self.ctx.project_root / "pt_build").resolve(), name)
            except ValueError:
                return self._error(400, "INVALID_REPORT_NAME")
            if not report_path.is_file():
                return self._error(404, "REPORT_NOT_FOUND")
            try:
                if report_path.stat().st_size > 64 * 1024 * 1024:
                    return self._error(413, "REPORT_TOO_LARGE")
                data = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return self._error(400, "REPORT_READ_FAILED", str(exc))
            return self._json(200, {"ok": True, "name": name, "report": data})
        if path == "/api/preview":
            rel = _one(q, "path")
            row = self.ctx.catalog.get_asset(rel)
            if not row or not row.get("previewable"):
                return self._error(404, "PREVIEW_NOT_AVAILABLE")
            try:
                p = _path_inside(self.ctx.client_root, rel)
                if not p.is_file():
                    return self._error(404, "PREVIEW_SOURCE_NOT_FOUND")
                raw, mime = preview_image_bytes(p, self.ctx.project_root)
            except FileNotFoundError as exc:
                return self._error(404, "PREVIEW_SOURCE_NOT_FOUND", str(exc))
            except PreviewDecodeError as exc:
                return self._error(422, "PREVIEW_UNSUPPORTED", str(exc))
            except ValueError as exc:
                return self._error(422, "PREVIEW_DECODE_FAILED", str(exc))
            except OSError as exc:
                return self._error(500, "PREVIEW_READ_FAILED", f"{type(exc).__name__}:{exc}")
            except Exception as exc:
                return self._error(500, "PREVIEW_INTERNAL_ERROR", f"{type(exc).__name__}:{exc}")
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "private, max-age=120")
            self.end_headers()
            self.wfile.write(raw)
            return
        return self._error(404, "NOT_FOUND")

    def do_POST(self) -> None:
        if not self._require_token():
            return
        u = urllib.parse.urlparse(self.path)
        body = self._body_json()
        if u.path == "/api/reindex":
            s = self.ctx.catalog.rebuild()
            self.ctx.invalidate_registry()
            return self._json(200, {"ok": True, "catalog": {"file_count": s.file_count, "total_bytes": s.total_bytes, "indexed_at": s.indexed_at}})
        if u.path == "/api/state/update":
            rel = str(body.get("path") or "")
            row = self.ctx.catalog.apply_state_update(rel, body.get("patch") if isinstance(body.get("patch"), dict) else {})
            if not row:
                return self._error(404, "ASSET_NOT_FOUND")
            return self._json(200, {"ok": True, "asset": self.ctx.asset_detail(rel)})
        if u.path == "/api/safety/arm":
            if str(body.get("confirm") or "") != ARM_PHRASE:
                return self._error(400, "ARM_CONFIRMATION_MISMATCH")
            self.ctx.arm(int(body.get("seconds") or 900))
            return self._json(200, {"ok": True, "write_armed": True, "write_armed_until": self.ctx.write_armed_until})
        if u.path == "/api/safety/disarm":
            self.ctx.disarm()
            return self._json(200, {"ok": True, "write_armed": False})
        if u.path == "/api/contracts/config":
            source_raw = str(body.get("source_root") or "").strip()
            reference_raw = str(body.get("reference_source_root") or "").strip()
            donor_raw = body.get("donor_clients") if isinstance(body.get("donor_clients"), list) else []
            donors = [str(x).strip() for x in donor_raw if str(x).strip()]
            donor_server_raw = body.get("donor_servers") if isinstance(body.get("donor_servers"), list) else []
            donor_servers = [str(x).strip() for x in donor_server_raw if str(x).strip()]
            try:
                source = pathlib.Path(source_raw).expanduser().resolve() if source_raw else None
                reference = pathlib.Path(reference_raw).expanduser().resolve() if reference_raw else None
                if source is not None and not source.is_dir():
                    return self._error(400, "SOURCE_ROOT_NOT_DIRECTORY", str(source))
                if reference is not None and not reference.is_dir():
                    return self._error(400, "REFERENCE_SOURCE_ROOT_NOT_DIRECTORY", str(reference))
                if source is not None:
                    save_source_root(self.ctx.project_root, source)
                else:
                    clear_source_root(self.ctx.project_root)
                if reference is not None:
                    save_reference_source_root(self.ctx.project_root, reference)
                else:
                    clear_reference_source_root(self.ctx.project_root)
                save_contract_donor_clients(self.ctx.project_root, donors)
                save_contract_donor_servers(self.ctx.project_root, donor_servers)
                persisted_donors = configured_contract_donor_clients(self.ctx.project_root)
                persisted_server_donors = configured_contract_donor_servers(self.ctx.project_root)
                self.ctx.set_contract_sources(source, reference, persisted_donors, persisted_server_donors)
                return self._json(200, {
                    "ok": True,
                    "source_root": str(self.ctx.source_root) if self.ctx.source_root else None,
                    "reference_source_root": str(self.ctx.reference_source_root) if self.ctx.reference_source_root else None,
                    "donor_clients": list(self.ctx.contract_donor_clients),
                    "donor_servers": list(self.ctx.contract_donor_servers),
                })
            except Exception as exc:
                return self._error(400, "CONTRACT_SOURCE_CONFIG_FAILED", str(exc))
        if u.path == "/api/contracts/analyze":
            if self.ctx.source_root is None or not self.ctx.source_root.is_dir():
                return self._error(409, "SOURCE_ROOT_REQUIRED", "Configure o source Summit primeiro.")
            if self.ctx.reference_source_root is None or not self.ctx.reference_source_root.is_dir():
                return self._error(409, "REFERENCE_SOURCE_ROOT_REQUIRED", "Configure o source EU de referência primeiro.")
            mode = str(body.get("mode") or "source").strip().lower()
            if mode not in {"source", "player_classes", "aggregate_player_classes", "aggregate_summit", "general_census"}:
                return self._error(400, "CONTRACT_ANALYSIS_MODE_INVALID")
            if mode == "general_census":
                if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                    return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
                cmd = [
                    "python3", str(self.ctx.project_root / "pt_asset.py"),
                    "--client-root", str(self.ctx.client_root),
                    "--server-root", str(self.ctx.server_root),
                    "audit", "general-asset-census",
                    "--source-root", str(self.ctx.source_root),
                    "--reference-source-root", str(self.ctx.reference_source_root),
                ]
            elif mode == "aggregate_summit":
                if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                    return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
                cmd = [
                    "python3", str(self.ctx.project_root / "pt_asset.py"),
                    "--client-root", str(self.ctx.client_root),
                    "--server-root", str(self.ctx.server_root),
                    "aggregate", "summit-superset",
                    "--source-root", str(self.ctx.source_root),
                    "--reference-source-root", str(self.ctx.reference_source_root),
                ]
            elif mode == "aggregate_player_classes":
                cmd = [
                    "python3", str(self.ctx.project_root / "pt_asset.py"),
                    "--client-root", str(self.ctx.client_root),
                    "aggregate", "player-classes",
                    "--source-root", str(self.ctx.source_root),
                    "--reference-source-root", str(self.ctx.reference_source_root),
                ]
            else:
                cmd = [
                    "python3", str(self.ctx.project_root / "pt_asset.py"),
                    "--client-root", str(self.ctx.client_root),
                    "audit", "source-contracts" if mode == "source" else "player-class-contracts",
                    "--source-root", str(self.ctx.source_root),
                    "--reference-source-root", str(self.ctx.reference_source_root),
                ]
            if mode in {"player_classes", "aggregate_player_classes", "aggregate_summit", "general_census"}:
                for donor in self.ctx.contract_donor_clients:
                    cmd.extend(["--donor-client", donor])
            if mode in {"aggregate_summit", "general_census"}:
                for donor in self.ctx.contract_donor_servers:
                    cmd.extend(["--donor-server", donor])
            job = self.ctx.jobs.submit(f"contracts_{mode}", None, cmd)
            return self._json(202, {"ok": True, "job": job.public(), "mode": mode})
        if u.path == "/api/server/config":
            raw = str(body.get("server_root") or "").strip()
            try:
                if raw:
                    server = pathlib.Path(raw).expanduser().resolve()
                    if not server.is_dir():
                        return self._error(400, "SERVER_ROOT_NOT_DIRECTORY", str(server))
                    save_server_root(self.ctx.project_root, server)
                    self.ctx.set_server_root(server)
                else:
                    clear_server_root(self.ctx.project_root)
                    self.ctx.set_server_root(None)
                return self._json(200, {"ok": True, "server_root": str(self.ctx.server_root) if self.ctx.server_root else None})
            except Exception as exc:
                return self._error(400, "SERVER_ROOT_CONFIG_FAILED", str(exc))
        if u.path == "/api/server/analyze":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
            mode = str(body.get("mode") or "design").strip().lower()
            subcommands = {
                "environment": ["validate", "server-environment-auto"],
                "design": ["validate", "server-design-auto"],
                "integration": ["validate", "integration-regression-auto"],
                "inventory": ["audit", "server-inventory"],
                "entities": ["audit", "server-bundles"],
                "fields": ["audit", "server-fields"],
                "items": ["audit", "server-items"],
                "vendor_plan": ["audit", "enrichment-plan"],
                "vendor_graph": ["audit", "enrichment-graph"],
            }
            if mode not in subcommands:
                return self._error(400, "SERVER_ANALYSIS_MODE_INVALID")
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "--server-root", str(self.ctx.server_root),
                *subcommands[mode],
            ]
            job = self.ctx.jobs.submit(f"server_{mode}", None, cmd)
            return self._json(202, {"ok": True, "job": job.public(), "mode": mode})
        if u.path == "/api/server/field-editor/stage":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
            if not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme temporariamente as ações de workspace/build antes de criar um draft de Field.")
            rel = str(body.get("path") or "").strip()
            kind = str(body.get("type") or "").strip().upper()
            expected = str(body.get("expected_sha256") or "").strip() or None
            if not rel or kind not in {"SPM", "SPP", "SPC"}:
                return self._error(400, "FIELD_STAGE_REQUEST_INVALID")
            try:
                if kind == "SPM":
                    result = stage_spm_text(
                        self.ctx.project_root, self.ctx.server_root, rel,
                        str(body.get("text") or ""), expected_sha256=expected,
                    )
                elif kind == "SPP":
                    edits = body.get("edits") if isinstance(body.get("edits"), list) else []
                    result = stage_spp_records(
                        self.ctx.project_root, self.ctx.server_root, rel, edits, expected_sha256=expected,
                    )
                else:
                    result = stage_spc_clone(
                        self.ctx.project_root, self.ctx.server_root, rel,
                        template_index=(None if body.get("template_index") in {None, ""} else int(body.get("template_index"))),
                        slot_index=(None if body.get("slot_index") in {None, ""} else int(body.get("slot_index"))),
                        record_name=str(body.get("record_name") or ""),
                        model_ini=str(body.get("model_ini") or ""),
                        server_npc=str(body.get("server_npc") or ""),
                        x=int(body.get("x") or 0), y=int(body.get("y") or 0), z=int(body.get("z") or 0),
                        ax=int(body.get("ax") or 0), ay=int(body.get("ay") or 0), az=int(body.get("az") or 0),
                        state=int(body.get("state") or 0), expected_sha256=expected,
                    )
                return self._json(200, {"ok": True, "draft": result})
            except FileNotFoundError as exc:
                return self._error(404, "FIELD_METADATA_NOT_FOUND", str(exc))
            except (ValueError, KeyError, TypeError) as exc:
                return self._error(400, "FIELD_DRAFT_REJECTED", str(exc))
            except Exception as exc:
                return self._error(500, "FIELD_DRAFT_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/tree-compare":
            left_raw = str(body.get("left") or "").strip()
            right_raw = str(body.get("right") or "").strip()
            if not left_raw or not right_raw:
                return self._error(400, "TREE_ROOT_REQUIRED")
            left = pathlib.Path(left_raw).expanduser().resolve()
            right = pathlib.Path(right_raw).expanduser().resolve()
            if not left.is_dir() or not right.is_dir():
                return self._error(400, "TREE_ROOT_NOT_DIRECTORY")
            stamp = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
            output = self.ctx.project_root / "pt_build" / f"tree_compare_ui_{stamp}.json"
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "compare", "trees", "--left", str(left), "--right", str(right),
                "--output", str(output),
            ]
            if bool(body.get("hash")):
                cmd.append("--hash")
            if bool(body.get("case_sensitive")):
                cmd.append("--case-sensitive")
            if bool(body.get("differences_only")):
                cmd.append("--differences-only")
            extensions = str(body.get("extensions") or "").strip()
            if extensions:
                cmd.extend(["--ext", extensions])
            category = str(body.get("category") or "").strip().upper()
            if category:
                cmd.extend(["--category", category])
            path_contains = str(body.get("path_contains") or "").strip()
            if path_contains:
                cmd.extend(["--path-contains", path_contains])
            job = self.ctx.jobs.submit("tree_compare", None, cmd)
            return self._json(202, {"ok": True, "job": job.public(), "output": str(output)})
        if u.path == "/api/monster-npc-census":
            stamp = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
            output = self.ctx.project_root / "pt_build" / f"monster_npc_census_ui_{stamp}.json"
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "audit", "monster-npc-census",
                "--client-root", str(self.ctx.client_root),
                "--output", str(output),
            ]
            if bool(body.get("refresh_census")):
                cmd.append("--refresh-census")
            job = self.ctx.jobs.submit("monster_npc_census", None, cmd)
            return self._json(202, {"ok": True, "job": job.public(), "output": str(output)})
        if u.path == "/api/action":
            action = str(body.get("action") or "")
            rel = str(body.get("path") or "") or None
            options = body.get("options") if isinstance(body.get("options"), dict) else {}
            spec = ACTION_SPECS.get(action)
            if not spec:
                return self._error(400, "ACTION_NOT_ALLOWED")
            if action == "upscale_texture":
                tcaps = texture_upscale_capability_status()
                if not bool(tcaps.get("lanczos_ready")):
                    return self._error(409, "TEXTURE_UPSCALE_PILLOW_UNAVAILABLE", "Instale Pillow para habilitar upscale de texturas.")
                backend = str(options.get("backend") or "lanczos").strip().lower()
                if backend == "realesrgan" and not bool(tcaps.get("realesrgan_ready")):
                    return self._error(409, "TEXTURE_UPSCALE_REALESRGAN_UNAVAILABLE", "realesrgan-ncnn-vulkan não foi encontrado; use Lanczos ou instale/configure o executável.")
            detail = None
            if rel:
                detail = self.ctx.asset_detail(rel)
                if not detail:
                    return self._error(404, "ASSET_NOT_FOUND")
                if action not in set(detail.get("capabilities") or []):
                    family = detail.get("family") or detail.get("inventory_family") or detail.get("physical_hint") or "UNKNOWN"
                    return self._error(409, "ACTION_NOT_SUPPORTED_FOR_ASSET", f"action={action} family={family}")
            elif action != "doctor":
                return self._error(400, "ASSET_PATH_REQUIRED")
            if spec.mutates_build and not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme temporariamente as ações de workspace/build no painel de Segurança.")
            if spec.mutates_build and self.ctx.jobs.has_active(rel):
                return self._error(409, "ASSET_EDIT_ALREADY_RUNNING", "Já existe uma tarefa ativa para este asset; aguarde ou cancele-a antes de iniciar outra edição/build.")
            try:
                cmd = build_command(self.ctx.project_root, action, rel, options)
            except Exception as exc:
                return self._error(400, "ACTION_BUILD_FAILED", str(exc))
            job = self.ctx.jobs.submit(action, rel, cmd, interactive=spec.interactive)
            return self._json(202, {"ok": True, "job": job.public(), "write_armed": self.ctx.write_armed})
        if u.path == "/api/job/input":
            ok = self.ctx.jobs.send_input(str(body.get("id") or ""), str(body.get("value") or ""))
            return self._json(200, {"ok": True}) if ok else self._error(409, "JOB_INPUT_NOT_ACCEPTED", "A tarefa não está aguardando uma resposta interativa válida.")
        if u.path == "/api/job/cancel":
            ok = self.ctx.jobs.cancel(str(body.get("id") or ""))
            return self._json(200, {"ok": ok}) if ok else self._error(409, "JOB_NOT_CANCELLABLE")
        if u.path == "/api/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return self._error(404, "NOT_FOUND")

    def _serve_static(self, rel: str) -> None:
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel or ".." in pathlib.PurePosixPath(rel).parts:
            return self._error(404, "NOT_FOUND")
        p = (self.ctx.static_root / pathlib.Path(*pathlib.PurePosixPath(rel).parts)).resolve()
        if self.ctx.static_root.resolve() not in p.parents and p != self.ctx.static_root.resolve():
            return self._error(404, "NOT_FOUND")
        if not p.is_file():
            return self._error(404, "NOT_FOUND")
        raw = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)


def _one(q: dict[str, list[str]], key: str) -> str:
    v = q.get(key)
    return str(v[0]) if v else ""


def _is_loopback(host: str) -> bool:
    if host in LOOPBACKS:
        return True
    try:
        return socket.gethostbyname(host).startswith("127.")
    except Exception:
        return False


def run_ui(
    project_root: pathlib.Path,
    client_root: pathlib.Path | None,
    server_root: pathlib.Path | None,
    host: str,
    port: int,
    open_browser: bool,
    allow_remote: bool,
) -> int:
    project_root = project_root.resolve()
    if not (project_root / "pt_asset.py").is_file():
        raise FileNotFoundError(f"pt_asset.py not found in {project_root}")
    if not _is_loopback(host):
        raise RuntimeError("REMOTE_BIND_DISABLED_V1; the current UI session token is intended for loopback-only use")
    client_root = (client_root or _discover_client_root(project_root)).resolve()
    ctx = UIContext(project_root, client_root, server_root)
    server = ThreadingHTTPServer((host, int(port)), UIHandler)
    server.daemon_threads = True
    server.ctx = ctx  # type: ignore[attr-defined]
    ctx.server = server
    addr, actual_port = server.server_address[:2]
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{actual_port}/"
    print(json.dumps({
        "format": "PT_ASSET_UI_SERVER_V1",
        "status": "READY",
        "ui_version": UI_VERSION,
        "backend_version": ctx.backend_version,
        "project_root": str(project_root),
        "client_root": str(client_root),
        "server_root": str(ctx.server_root) if ctx.server_root else None,
        "url": url,
        "catalog_file_count": ctx.catalog.stats.file_count,
        "client_modified": False,
        "core_modified": False,
    }, ensure_ascii=False, indent=2), flush=True)
    print(f"pt_asset_ui=READY url={url} client_modified=false core_modified=false", flush=True)
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
