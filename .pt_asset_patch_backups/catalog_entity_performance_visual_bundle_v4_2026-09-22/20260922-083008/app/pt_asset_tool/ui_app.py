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
from .ui_capabilities import capabilities_for_asset, ui_options_for_asset
from .profile_registry import CharacterProfileRegistry
from .ui_image import PreviewDecodeError, preview_image_bytes
from .ui_jobs import JobManager
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .legacy_management_web import (
    legacy_management_dashboard, legacy_management_item_detail,
    query_legacy_management_report, verify_management_for_web,
)
from .legacy_authoring import authoring_capabilities, authoring_workspace_guide, inspect_authoring, stage_authoring
from .entity_catalog import entity_detail, load_entity_seed, query_entities
from .server_ui import build_server_ui_summary, server_report_rows
from .client_enrichment import asset_analysis_evidence, build_client_enrichment_summary, query_client_enrichment_report
from .asset_contract_registry import registry_summary, get_contract, schema_for_contract, match_contracts_for_path
from .asset_compiler import compiler_capabilities, plan_compiler_input, compile_compiler_input
from .asset_bundle_deploy import (
    APPLY_CONFIRM as ASSET_BUNDLE_APPLY_CONFIRM,
    RESTORE_CONFIRM as ASSET_BUNDLE_RESTORE_CONFIRM,
    latest_bundle_manifest, publish_asset_bundle, restore_asset_bundle, asset_bundle_deploy_status,
)
from .app_config import (
    save_server_root, clear_server_root,
    configured_contract_donor_clients, configured_contract_donor_servers,
    validate_contract_donor_specs, save_contract_source_config,
)
from .validation import rigid_model_info_options
from .server_field_editor import inspect_field_metadata, stage_spm_text, stage_spp_records, stage_spc_native
from .general_asset_census import query_general_asset_census
from .server_enrichment_readiness import build_general_census_readiness
from .source_catalog import configured_source_roots
from .texture_upscale import capability_status as texture_upscale_capability_status, enhancement_status, enhancement_root, enhancement_batch_status
from .blender_workspace import blender_edit_root
from .dependencies import dependency_report
from . import particle_service
from .legacy_apps.workspace import (
    workspace_status as legacy_apps_workspace_status,
    inspect_character as legacy_apps_inspect_character,
    inspect_account_task as legacy_apps_inspect_account,
    queue_status as legacy_apps_queue_status,
    item_scan as legacy_apps_item_scan,
    inventory_status as legacy_apps_inventory_status,
    admin_status as legacy_apps_admin_status,
    plan_operation as legacy_apps_plan_operation,
    analyze_protector_log as legacy_apps_analyze_protector_log,
)
from .legacy_apps.plan_store import save_plan as legacy_apps_save_plan, load_plan as legacy_apps_load_plan
from .legacy_apps.pritator_bulk import (
    plan_bulk_experience as legacy_plan_bulk_exp, stage_bulk_experience as legacy_stage_bulk_exp,
    plan_bulk_gold as legacy_plan_bulk_gold, stage_bulk_gold as legacy_stage_bulk_gold,
)
from .legacy_apps.apply import apply_saved_plan as legacy_apps_apply_saved_plan
from .workspace_bundle_deploy import latest_applied_bundle_manifest, workspace_bundle_restore_capabilities

LOOPBACKS = {"127.0.0.1", "localhost", "::1"}
ARM_PHRASE = "ARM BUILD WRITES"
DEPLOY_ARM_PHRASE = "ARM CLIENT DEPLOY"
SERVER_DEPLOY_ARM_PHRASE = "ARM ASSET DEPLOY"


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
        self.deploy_armed_until = 0.0
        self.server_deploy_armed_until = 0.0
        self.particle_preview_lock = threading.Lock()
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
        row["asset_contract_candidates"] = match_contracts_for_path(rel)
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
                row["analysis_evidence"] = asset_analysis_evidence(self.settings, asset.asset_id)
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
                model_info_options = rigid_model_info_options(asset) if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE" else []
                row["model_info_options"] = model_info_options
                row["ui_options"] = ui_options_for_asset(
                    asset,
                    self.resolver,
                    model_info_options=model_info_options,
                    head_candidates=head_candidates,
                    animation_binding_ready_physical=row["animation_binding_ready_physical"],
                )
                # Explicit related paths are relationship evidence, not filename guesses.
                related=[]
                seen_related=set()
                def add_related(logical: str, relation: str, evidence: str) -> None:
                    logical=str(logical or "").replace("\\", "/").strip("/")
                    if not logical or logical.casefold() == str(asset.primary_path).casefold():
                        return
                    key=(logical.casefold(), relation)
                    if key in seen_related:
                        return
                    seen_related.add(key)
                    catalog_row=self.catalog.get_asset(logical)
                    related.append({
                        "path": logical,
                        "relation": relation,
                        "evidence": evidence,
                        "present": bool(catalog_row),
                        "previewable": bool((catalog_row or {}).get("previewable")),
                        "category": (catalog_row or {}).get("category"),
                        "role": (catalog_row or {}).get("role"),
                        "ext": (catalog_row or {}).get("ext") or pathlib.PurePosixPath(logical).suffix.lower(),
                    })
                for texture in getattr(asset, "textures", []) or []:
                    add_related(texture, "TEXTURE", "SMD_MATERIAL_TEXLINK")
                for cfg in getattr(asset, "configs", []) or []:
                    if isinstance(cfg, dict):
                        add_related(cfg.get("inx"), "CONFIG", "REGISTRY_CONFIG")
                        add_related(cfg.get("motion_inx"), "MOTION_CONFIG", "VERIFIED_BINDING_CONTEXT")
                        add_related(cfg.get("motion_smb"), "SKELETON_MOTION", "VERIFIED_BINDING_CONTEXT")
                for motion_path in getattr(asset, "motions", []) or []:
                    add_related(motion_path, "SKELETON_MOTION", "VERIFIED_REGISTRY_BINDING")
                row["related_assets"] = sorted(related, key=lambda x: (x["relation"], x["path"].casefold()))
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
                if not row.get("ui_options", {}).get("supports_animation"):
                    caps = [x for x in caps if x not in {"motions", "validate_animation", "diagnose_animation"}]
                    if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE" and row["animation_binding_ready_physical"]:
                        notes["motions"] = "NO_ACTIVE_PHYSICAL_MOTIONINFO"
                if head_candidates:
                    caps = sorted(set(caps) | {"heads"})
                if asset.family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"}:
                    workspace = blender_edit_root(self.project_root, "generic_import", asset.primary_path)
                    if (workspace / "imported.blend").is_file() and (workspace / "authoring_manifest.json").is_file():
                        caps = sorted(set(caps) | {"prepare_bundle", "publish_bundle"})
                        row["publish_workspace"] = str(workspace)
                        row["roundtrip_workspace_ready"] = True
                    try:
                        latest = latest_applied_bundle_manifest(self.project_root, asset.primary_path)
                    except Exception:
                        latest = None
                    if latest is not None:
                        restore_caps = workspace_bundle_restore_capabilities(self.project_root, asset.primary_path)
                        if restore_caps.get("can_restore_bundle"):
                            caps = sorted(set(caps) | {"check_bundle", "restore_bundle"})
                        if restore_caps.get("can_restore_model"):
                            caps = sorted(set(caps) | {"restore_model_only"})
                        row["latest_deploy_manifest"] = str(latest)
                        row["roundtrip_last_deploy_ready"] = bool(restore_caps.get("can_restore_bundle"))
                        row["roundtrip_restore"] = restore_caps
                try:
                    enh = enhancement_status(self.project_root, self.client_root, asset.primary_path)
                except Exception as exc:
                    enh = {"workspace_root": str(enhancement_root(self.project_root)), "candidate_ready": False, "can_restore": False, "status_error": f"{type(exc).__name__}:{exc}"}
                row["enhancement"] = enh
                if "upscale_texture" in caps and enh.get("candidate_ready"):
                    caps = sorted(set(caps) | {"publish_enhancement"})
                if "upscale_texture" in caps and enh.get("can_restore"):
                    caps = sorted(set(caps) | {"restore_enhancement"})
                row["capabilities"] = caps
                row["capability_notes"] = notes
            else:
                # Files such as INX/SMB/WAV remain useful catalog/inspection
                # entries but do not inherit model-only actions.
                fallback_caps = ["inspect"]
                ext = pathlib.PurePosixPath(str(row.get("path") or "")).suffix.lower()
                if ext in {".bmp", ".tga", ".png", ".jpg", ".jpeg"} and bool(texture_upscale_capability_status().get("lanczos_ready")):
                    fallback_caps.append("upscale_texture")
                    try:
                        enh = enhancement_status(self.project_root, self.client_root, str(row.get("path") or ""))
                    except Exception as exc:
                        enh = {"workspace_root": str(enhancement_root(self.project_root)), "candidate_ready": False, "can_restore": False, "status_error": f"{type(exc).__name__}:{exc}"}
                    row["enhancement"] = enh
                    if enh.get("candidate_ready"):
                        fallback_caps.append("publish_enhancement")
                    if enh.get("can_restore"):
                        fallback_caps.append("restore_enhancement")
                row["capabilities"] = sorted(set(fallback_caps))
                row["ui_options"] = {
                    "supports_paint": False, "supports_animation": False, "available_motions": [],
                    "motion_inventory": [], "default_motion": None, "supports_lod_selection": False,
                    "available_lods": [], "requires_model_info": False, "model_info_options": [],
                    "supports_head": False, "head_candidates": [], "supports_roundtrip": False,
                }
                row["related_assets"] = []
        except Exception as exc:
            row["registry_error"] = f"{type(exc).__name__}:{exc}"
            row["capabilities"] = ["inspect"]
            row.setdefault("ui_options", {
                "supports_paint": False, "supports_animation": False, "available_motions": [],
                "motion_inventory": [], "default_motion": None, "supports_lod_selection": False,
                "available_lods": [], "requires_model_info": False, "model_info_options": [],
                "supports_head": False, "head_candidates": [], "supports_roundtrip": False,
            })
            row.setdefault("related_assets", [])
        return row

    @property
    def write_armed(self) -> bool:
        return time.time() < self.write_armed_until

    def arm(self, seconds: int = 900) -> None:
        self.write_armed_until = time.time() + max(60, min(3600, seconds))

    def disarm(self) -> None:
        self.write_armed_until = 0.0

    @property
    def deploy_armed(self) -> bool:
        return time.time() < self.deploy_armed_until

    def arm_deploy(self, seconds: int = 300) -> None:
        self.deploy_armed_until = time.time() + max(60, min(900, seconds))

    def disarm_deploy(self) -> None:
        self.deploy_armed_until = 0.0

    @property
    def server_deploy_armed(self) -> bool:
        return time.time() < self.server_deploy_armed_until

    def arm_server_deploy(self, seconds: int = 300) -> None:
        self.server_deploy_armed_until = time.time() + max(60, min(900, seconds))

    def disarm_server_deploy(self) -> None:
        self.server_deploy_armed_until = 0.0


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
                "deploy_armed": self.ctx.deploy_armed,
                "deploy_armed_until": self.ctx.deploy_armed_until,
                "server_deploy_armed": self.ctx.server_deploy_armed,
                "server_deploy_armed_until": self.ctx.server_deploy_armed_until,
                "actions": public_action_specs(),
                "optional_capabilities": {"texture_upscale": texture_upscale_capability_status()},
                "dependencies": dependency_report(self.ctx.project_root),
                "safety": {
                    "client_source_write": "EXPLICIT_VERIFIED_BUNDLE_ONLY",
                    "build_write_requires_arm": True,
                    "arm_phrase": ARM_PHRASE,
                    "client_deploy_requires_separate_arm": True,
                    "deploy_arm_phrase": DEPLOY_ARM_PHRASE,
                    "server_deploy_requires_separate_arm": True,
                    "server_deploy_arm_phrase": "ARM CHARACTER DEPLOY",  # legacy bootstrap compatibility only
                    "asset_bundle_deploy_arm_phrase": SERVER_DEPLOY_ARM_PHRASE,
                    "new_character_server_write": "VERIFIED_BUNDLE_ONLY",
                    "new_character_surface": "DISABLED_LEGACY_SURFACE",
                    "server_source_write": False,
                    "persistence_write": False,
                    "note": "Client/server Asset Bundle writes are limited to verified transactions with backup, drift gate, atomic replace and rollback. Persistence/security/log paths remain blocked.",
                },
            })
        if path == "/api/legacy-ops/status":
            try:
                return self._json(200, {"ok": True, **legacy_apps_workspace_status(self.ctx.project_root, self.ctx.server_root)})
            except Exception as exc:
                return self._error(400, "LEGACY_OPS_STATUS_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-ops/character":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            name = _one(q, "name").strip()
            if not name:
                return self._error(400, "CHARACTER_NAME_REQUIRED")
            try:
                return self._json(200, {"ok": True, "result": legacy_apps_inspect_character(self.ctx.server_root, name)})
            except Exception as exc:
                return self._error(400, "LEGACY_CHARACTER_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-ops/account":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            account = _one(q, "name").strip()
            if not account:
                return self._error(400, "ACCOUNT_NAME_REQUIRED")
            try:
                return self._json(200, {"ok": True, "result": legacy_apps_inspect_account(self.ctx.server_root, account)})
            except Exception as exc:
                return self._error(400, "LEGACY_ACCOUNT_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-ops/postbox":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            account = _one(q, "account").strip()
            if not account:
                return self._error(400, "ACCOUNT_NAME_REQUIRED")
            try:
                return self._json(200, {"ok": True, "result": legacy_apps_queue_status(self.ctx.server_root, account)})
            except Exception as exc:
                return self._error(400, "LEGACY_POSTBOX_READ_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-ops/inventory":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            store = _one(q, "store").strip().lower()
            key = _one(q, "key").strip()
            if store not in {"userdata", "warehouse"}:
                return self._error(400, "INVENTORY_STORE_INVALID")
            if not key:
                return self._error(400, "INVENTORY_KEY_REQUIRED")
            try:
                return self._json(200, {"ok": True, "result": legacy_apps_inventory_status(self.ctx.server_root, store=store, key=key)})
            except Exception as exc:
                return self._error(400, "LEGACY_INVENTORY_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-ops/admin":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            try:
                return self._json(200, {"ok": True, "result": legacy_apps_admin_status(self.ctx.server_root)})
            except Exception as exc:
                return self._error(400, "LEGACY_ADMIN_STATUS_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-management":
            try:
                return self._json(200, {"ok": True, **legacy_management_dashboard(
                    self.ctx.project_root, client_root=self.ctx.client_root, server_root=self.ctx.server_root
                )})
            except Exception as exc:
                return self._error(400, "LEGACY_MANAGEMENT_SUMMARY_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-management/item":
            code = _one(q, "code").strip()
            if not code:
                return self._error(400, "LEGACY_ITEM_CODE_REQUIRED")
            try:
                return self._json(200, {"ok": True, **legacy_management_item_detail(code, resolver=self.ctx.resolver)})
            except Exception as exc:
                return self._error(400, "LEGACY_ITEM_LOOKUP_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/legacy-management/report":
            try:
                result = query_legacy_management_report(
                    self.ctx.project_root, section=_one(q, "section") or "items", query=_one(q, "q"),
                    status=_one(q, "status"), offset=int(_one(q, "offset") or 0), limit=int(_one(q, "limit") or 100),
                )
                return self._json(200, {"ok": True, **result})
            except ValueError as exc:
                return self._error(400, "LEGACY_MANAGEMENT_REPORT_QUERY_INVALID", str(exc))
            except Exception as exc:
                return self._error(400, "LEGACY_MANAGEMENT_REPORT_QUERY_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/catalog":
            try:
                entity_key = _one(q, "entity")
                allowed_paths = None
                active_entity = None
                if entity_key:
                    try:
                        registry = self.ctx.registry()
                    except Exception:
                        registry = None
                    detail = entity_detail(self.ctx.catalog.assets, self.ctx.entity_seed, entity_key, registry=registry)
                    if detail is None:
                        return self._error(404, "ENTITY_NOT_FOUND")
                    active_entity = detail.get("entity") or {}
                    allowed_paths = set(active_entity.get("all_paths") or [])
                report = self.ctx.catalog.query(
                    q=_one(q, "q"), category="" if entity_key else _one(q, "category"), folder=_one(q, "folder"),
                    role=_one(q, "role"), ext=_one(q, "ext"),
                    favorites=_one(q, "favorites") in {"1", "true", "yes"},
                    show_system=_one(q, "show_system") in {"1", "true", "yes"},
                    allowed_paths=allowed_paths,
                    page=int(_one(q, "page") or 1), page_size=int(_one(q, "page_size") or 100),
                )
                return self._json(200, {"ok": True, **report, "active_entity": active_entity})
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
                report["enhancement_batch"] = enhancement_batch_status(self.ctx.project_root)
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
        if path == "/api/asset-contracts":
            try:
                contract_id = _one(q, "id")
                if contract_id:
                    contract = get_contract(contract_id).public()
                    return self._json(200, {
                        "ok": True, "status": "PASS", "contract": contract,
                        "schema": schema_for_contract(contract_id),
                        "compiler": compiler_capabilities(),
                    })
                report = registry_summary(
                    query=_one(q, "q"), capability=_one(q, "capability"), implementation=_one(q, "implementation")
                )
                return self._json(200, {"ok": True, **report})
            except KeyError:
                return self._error(404, "ASSET_CONTRACT_NOT_FOUND")
            except Exception as exc:
                return self._error(400, "ASSET_CONTRACT_REGISTRY_FAILED", str(exc))
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
                active_general_census = next((
                    job for job in self.ctx.jobs.list(50)
                    if job.get("action") == "contracts_general_census"
                    and job.get("status") in {"QUEUED", "RUNNING", "CANCELLING"}
                ), None)
                census_readiness = build_general_census_readiness(
                    self.ctx.project_root, self.ctx.client_root, self.ctx.server_root,
                    self.ctx.source_root, self.ctx.reference_source_root,
                    self.ctx.contract_donor_clients, self.ctx.contract_donor_servers,
                    active_job=active_general_census,
                )
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
                    "general_census_readiness": census_readiness,
                    "asset_contract_registry": registry_summary(),
                    "asset_compiler": compiler_capabilities(),
                })
            except Exception as exc:
                return self._error(400, "CONTRACT_SUMMARY_FAILED", str(exc))
        if path == "/api/legacy-authoring/capabilities":
            return self._json(200, {"ok": True, "result": authoring_capabilities()})
        if path == "/api/legacy-authoring/guide":
            return self._json(200, {"ok": True, "result": authoring_workspace_guide(server_root=self.ctx.server_root, client_root=self.ctx.client_root)})
        if path == "/api/legacy-authoring/inspect":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
            kind = _one(q, "kind").strip().upper()
            logical = _one(q, "path").strip()
            if not kind or not logical:
                return self._error(400, "LEGACY_AUTHORING_INSPECT_REQUEST_INVALID")
            try:
                result = inspect_authoring(self.ctx.project_root, self.ctx.server_root, self.ctx.client_root, kind, logical)
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_AUTHORING_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
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
                readiness = build_general_census_readiness(
                    self.ctx.project_root, self.ctx.client_root, self.ctx.server_root,
                    self.ctx.source_root, self.ctx.reference_source_root,
                    self.ctx.contract_donor_clients, self.ctx.contract_donor_servers,
                )
                report["freshness"] = readiness.get("freshness")
                report["freshness_reasons"] = readiness.get("freshness_reasons") or []
                report["readiness_state"] = readiness.get("state")
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "GENERAL_CENSUS_QUERY_FAILED", str(exc))
        if path == "/api/client/report":
            try:
                report = query_client_enrichment_report(
                    self.ctx.project_root,
                    query=_one(q, "q"),
                    state=_one(q, "state"),
                    group=_one(q, "group"),
                    kind=_one(q, "kind"),
                    offset=int(_one(q, "offset") or 0),
                    limit=int(_one(q, "limit") or 250),
                )
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "CLIENT_ENRICHMENT_REPORT_QUERY_FAILED", str(exc))
        if path == "/api/client":
            try:
                try:
                    registry = self.ctx.registry()
                    registry_error = None
                except Exception as exc:
                    registry = None
                    registry_error = f"{type(exc).__name__}:{exc}"
                report = build_client_enrichment_summary(
                    self.ctx.project_root, self.ctx.client_root, self.ctx.catalog, self.ctx.entity_seed,
                    registry=registry, settings=self.ctx.settings,
                )
                if registry_error:
                    report["registry_error"] = registry_error
                return self._json(200, {"ok": True, **report})
            except Exception as exc:
                return self._error(400, "CLIENT_ENRICHMENT_SUMMARY_FAILED", str(exc))
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
        if path == "/api/particles":
            try:
                rows = particle_service.asset_index(self.ctx.client_root, _one(q, "q"))
                return self._json(200, {"ok": True, "items": rows, "count": len(rows)})
            except Exception as exc:
                return self._error(400, "PARTICLE_INDEX_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/particles/inspect":
            try:
                asset = _one(q, "asset")
                result = particle_service.inspect_asset(
                    self.ctx.client_root, self.ctx.project_root / "pt_build" / "devtest", asset
                )
                return self._json(200, {"ok": True, "particle": result})
            except FileNotFoundError as exc:
                return self._error(404, "PARTICLE_ASSET_NOT_FOUND", str(exc))
            except Exception as exc:
                return self._error(400, "PARTICLE_INSPECT_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/particles/draft-verify":
            try:
                result = particle_service.verify_asset_draft(
                    self.ctx.client_root, self.ctx.project_root / "pt_build" / "devtest", _one(q, "asset")
                )
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "PARTICLE_DRAFT_VERIFY_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/particles/preview-image":
            try:
                image = particle_service.safe_preview_image(self.ctx.project_root, _one(q, "path"))
                raw = image.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            except FileNotFoundError as exc:
                return self._error(404, "PARTICLE_PREVIEW_NOT_FOUND", str(exc))
            except Exception as exc:
                return self._error(400, "PARTICLE_PREVIEW_IMAGE_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/asset-compiler/status":
            try:
                return self._json(200, {"ok": True, "result": asset_bundle_deploy_status(self.ctx.project_root)})
            except Exception as exc:
                return self._error(400, "ASSET_BUNDLE_STATUS_FAILED", f"{type(exc).__name__}:{exc}")
        if path == "/api/jobs":
            surface = _one(q, "surface").strip() or None
            return self._json(200, {"ok": True, "jobs": self.ctx.jobs.list(int(_one(q, "limit") or 50), surface=surface)})
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
        if u.path == "/api/legacy-ops/plan":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            operation = str(body.get("operation") or "").strip().upper()
            payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
            if not operation:
                return self._error(400, "LEGACY_OPERATION_REQUIRED")
            try:
                plan = legacy_apps_plan_operation(self.ctx.server_root, operation, payload)
                saved = legacy_apps_save_plan(self.ctx.project_root, operation, plan)
                return self._json(200, {"ok": True, "result": saved})
            except Exception as exc:
                return self._error(400, "LEGACY_OPERATION_PLAN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/apply":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            if not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme workspace/build antes de aplicar uma operação de persistência Legacy Python.")
            plan_id = str(body.get("plan_id") or "").strip()
            confirmation = str(body.get("confirmation") or "")
            if not plan_id:
                return self._error(400, "LEGACY_PLAN_ID_REQUIRED")
            try:
                result = legacy_apps_apply_saved_plan(self.ctx.project_root, self.ctx.server_root, plan_id, confirmation)
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_OPERATION_APPLY_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/monster-bulk-exp-plan":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            try:
                paths = body.get("paths") or []
                if isinstance(paths, str):
                    paths = [x.strip() for x in paths.splitlines() if x.strip()]
                if not isinstance(paths, list):
                    return self._error(400, "MONSTER_PATHS_LIST_REQUIRED")
                max_raw = body.get("max_exp")
                max_exp = int(max_raw) if max_raw not in (None, "") else None
                plan = legacy_plan_bulk_exp(self.ctx.server_root, paths, str(body.get("formula") or ""), max_exp=max_exp)
                saved = legacy_apps_save_plan(self.ctx.project_root, "PRITATOR_BULK_EXP", plan)
                return self._json(200, {"ok": True, "result": saved})
            except Exception as exc:
                return self._error(400, "MONSTER_BULK_EXP_PLAN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/monster-bulk-exp-stage":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            plan_id = str(body.get("plan_id") or "").strip()
            if not plan_id:
                return self._error(400, "LEGACY_PLAN_ID_REQUIRED")
            try:
                loaded = legacy_apps_load_plan(self.ctx.project_root, plan_id)
                if str(loaded.get("operation_request") or "").upper() != "PRITATOR_BULK_EXP":
                    return self._error(400, "MONSTER_BULK_EXP_PLAN_KIND_INVALID")
                result = legacy_stage_bulk_exp(self.ctx.project_root, self.ctx.server_root, self.ctx.client_root, loaded["plan"])
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "MONSTER_BULK_EXP_STAGE_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/monster-bulk-gold-plan":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            try:
                paths = body.get("paths") or []
                if isinstance(paths, str):
                    paths = [x.strip() for x in paths.splitlines() if x.strip()]
                if not isinstance(paths, list):
                    return self._error(400, "MONSTER_PATHS_LIST_REQUIRED")
                max_raw = body.get("max_gold")
                max_gold = int(max_raw) if max_raw not in (None, "") else None
                plan = legacy_plan_bulk_gold(self.ctx.server_root, paths, str(body.get("formula") or ""), max_gold=max_gold)
                saved = legacy_apps_save_plan(self.ctx.project_root, "PRITATOR_BULK_GOLD", plan)
                return self._json(200, {"ok": True, "result": saved})
            except Exception as exc:
                return self._error(400, "MONSTER_BULK_GOLD_PLAN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/monster-bulk-gold-stage":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            plan_id = str(body.get("plan_id") or "").strip()
            if not plan_id:
                return self._error(400, "LEGACY_PLAN_ID_REQUIRED")
            try:
                loaded = legacy_apps_load_plan(self.ctx.project_root, plan_id)
                if str(loaded.get("operation_request") or "").upper() != "PRITATOR_BULK_GOLD":
                    return self._error(400, "MONSTER_BULK_GOLD_PLAN_KIND_INVALID")
                result = legacy_stage_bulk_gold(self.ctx.project_root, self.ctx.server_root, self.ctx.client_root, loaded["plan"])
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "MONSTER_BULK_GOLD_STAGE_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/item-scan":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            try:
                result = legacy_apps_item_scan(
                    self.ctx.server_root,
                    query=str(body.get("query") or ""),
                    include_warehouse=bool(body.get("include_warehouse", True)),
                )
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_ITEM_SCAN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-ops/protector-analyze":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_NOT_CONFIGURED")
            try:
                result = legacy_apps_analyze_protector_log(self.ctx.server_root, str(body.get("text") or ""))
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_PROTECTOR_ANALYZE_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-management/verify":
            root = str(body.get("management_root") or "").strip()
            if not root:
                return self._error(400, "MANAGEMENT_ROOT_REQUIRED")
            try:
                result = verify_management_for_web(root)
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_MANAGEMENT_VERIFY_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/legacy-management/audit":
            management_root = str(body.get("management_root") or "").strip()
            tutorial_root = str(body.get("tutorial_root") or "").strip()
            sample_limit = int(body.get("sample_limit") or 80)
            if sample_limit < 1 or sample_limit > 500:
                return self._error(400, "LEGACY_MANAGEMENT_SAMPLE_LIMIT_INVALID")
            for label, raw in (("MANAGEMENT_ROOT", management_root), ("TUTORIAL_ROOT", tutorial_root)):
                if raw and not pathlib.Path(raw).expanduser().is_dir():
                    return self._error(400, f"{label}_NOT_DIRECTORY", raw)
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
            ]
            if self.ctx.server_root is not None and self.ctx.server_root.is_dir():
                cmd.extend(["--server-root", str(self.ctx.server_root)])
            cmd.extend(["audit", "legacy-management", "--sample-limit", str(sample_limit)])
            if management_root:
                cmd.extend(["--management-root", management_root])
            if tutorial_root:
                cmd.extend(["--tutorial-root", tutorial_root])
            job = self.ctx.jobs.submit("legacy_management_audit", None, cmd)
            return self._json(202, {"ok": True, "job": job.public(), "mode": "legacy_management_audit"})
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
        if u.path == "/api/safety/deploy-arm":
            if str(body.get("confirm") or "") != DEPLOY_ARM_PHRASE:
                return self._error(400, "DEPLOY_ARM_CONFIRMATION_REQUIRED", DEPLOY_ARM_PHRASE)
            self.ctx.arm_deploy(int(body.get("seconds") or 300))
            return self._json(200, {"ok": True, "deploy_armed": True, "deploy_armed_until": self.ctx.deploy_armed_until})
        if u.path == "/api/safety/deploy-disarm":
            self.ctx.disarm_deploy()
            return self._json(200, {"ok": True, "deploy_armed": False})
        if u.path == "/api/safety/server-deploy-arm":
            if str(body.get("confirm") or "") != SERVER_DEPLOY_ARM_PHRASE:
                return self._error(400, "SERVER_DEPLOY_ARM_CONFIRMATION_REQUIRED", SERVER_DEPLOY_ARM_PHRASE)
            self.ctx.arm_server_deploy(int(body.get("seconds") or 300))
            return self._json(200, {"ok": True, "server_deploy_armed": True, "server_deploy_armed_until": self.ctx.server_deploy_armed_until})
        if u.path == "/api/safety/server-deploy-disarm":
            self.ctx.disarm_server_deploy()
            return self._json(200, {"ok": True, "server_deploy_armed": False})
        if u.path in {"/api/asset-compiler/plan", "/api/asset-compiler/build"}:
            recipe = body.get("recipe") if isinstance(body.get("recipe"), dict) else body
            try:
                if u.path.endswith("/plan"):
                    result = plan_compiler_input(recipe, client_root=self.ctx.client_root, server_root=self.ctx.server_root)
                    return self._json(200, {"ok": True, "result": result})
                if not self.ctx.write_armed:
                    return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme workspace/build antes de compilar o asset para pt_build.")
                result = compile_compiler_input(self.ctx.project_root, recipe, client_root=self.ctx.client_root, server_root=self.ctx.server_root)
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "ASSET_COMPILER_REJECTED", f"{type(exc).__name__}:{exc}")
        if u.path in {"/api/asset-compiler/publish", "/api/asset-compiler/restore"}:
            if not self.ctx.server_deploy_armed:
                return self._error(409, "ASSET_DEPLOY_NOT_ARMED", "Arme temporariamente o deploy de Asset Bundle antes desta transação.")
            try:
                raw_manifest = str(body.get("manifest") or "").strip()
                manifest = pathlib.Path(raw_manifest).expanduser().resolve() if raw_manifest else latest_bundle_manifest(self.ctx.project_root)
                if manifest is None:
                    return self._error(404, "ASSET_BUNDLE_MANIFEST_NOT_FOUND")
                if u.path.endswith("/publish"):
                    result = publish_asset_bundle(
                        self.ctx.project_root, self.ctx.client_root, self.ctx.server_root, manifest,
                        confirm=ASSET_BUNDLE_APPLY_CONFIRM,
                    )
                else:
                    result = restore_asset_bundle(
                        self.ctx.project_root, self.ctx.client_root, self.ctx.server_root, manifest,
                        confirm=ASSET_BUNDLE_RESTORE_CONFIRM,
                    )
                self.ctx.disarm_server_deploy()
                return self._json(200, {"ok": True, "result": result, "server_deploy_armed": False})
            except Exception as exc:
                self.ctx.disarm_server_deploy()
                return self._error(400, "ASSET_BUNDLE_DEPLOY_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/contracts/config":
            source_raw = str(body.get("source_root") or "").strip()
            reference_raw = str(body.get("reference_source_root") or "").strip()
            donor_raw = body.get("donor_clients") if isinstance(body.get("donor_clients"), list) else []
            donor_server_raw = body.get("donor_servers") if isinstance(body.get("donor_servers"), list) else []
            try:
                source = pathlib.Path(source_raw).expanduser().resolve() if source_raw else None
                reference = pathlib.Path(reference_raw).expanduser().resolve() if reference_raw else None
                root_issues: list[dict[str, Any]] = []
                if source is not None and not source.is_dir():
                    root_issues.append({"field": "source_root", "code": "SOURCE_ROOT_NOT_DIRECTORY", "message": f"Source Summit não existe ou não é uma pasta: {source}"})
                if reference is not None and not reference.is_dir():
                    root_issues.append({"field": "reference_source_root", "code": "REFERENCE_SOURCE_ROOT_NOT_DIRECTORY", "message": f"Source EU de referência não existe ou não é uma pasta: {reference}"})
                client_validation = validate_contract_donor_specs(donor_raw, "client", require_existing=True)
                server_validation = validate_contract_donor_specs(donor_server_raw, "server", require_existing=True)
                issues = root_issues + list(client_validation["issues"]) + list(server_validation["issues"])
                if issues:
                    return self._json(400, {
                        "ok": False,
                        "error": "CONTRACT_SOURCE_CONFIG_INVALID",
                        "detail": "A configuração não foi salva. Corrija as linhas indicadas; nenhuma alteração parcial foi persistida.",
                        "issues": issues,
                        "accepted_formats": {
                            "client": client_validation["accepted_formats"],
                            "server": server_validation["accepted_formats"],
                        },
                    })
                # One atomic config replacement: roots and donors can never be partially saved.
                persisted = save_contract_source_config(
                    self.ctx.project_root, source, reference,
                    client_validation["normalized"], server_validation["normalized"],
                )
                persisted_donors = list(persisted["donor_clients"])
                persisted_server_donors = list(persisted["donor_servers"])
                self.ctx.set_contract_sources(source, reference, persisted_donors, persisted_server_donors)
                readiness = build_general_census_readiness(
                    self.ctx.project_root, self.ctx.client_root, self.ctx.server_root,
                    self.ctx.source_root, self.ctx.reference_source_root,
                    self.ctx.contract_donor_clients, self.ctx.contract_donor_servers,
                )
                return self._json(200, {
                    "ok": True,
                    "source_root": str(self.ctx.source_root) if self.ctx.source_root else None,
                    "reference_source_root": str(self.ctx.reference_source_root) if self.ctx.reference_source_root else None,
                    "donor_clients": list(self.ctx.contract_donor_clients),
                    "donor_servers": list(self.ctx.contract_donor_servers),
                    "validation": {"client": client_validation, "server": server_validation},
                    "general_census_readiness": readiness,
                })
            except Exception as exc:
                return self._error(400, "CONTRACT_SOURCE_CONFIG_FAILED", str(exc))
        if u.path == "/api/client/analyze":
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "audit", "client-enrichment",
            ]
            job = self.ctx.jobs.submit(
                "client_enrichment", None, cmd,
                surface="client", workflow="validation", result_anchor="clientValidationPanel",
            )
            return self._json(202, {"ok": True, "job": job.public(), "mode": "client_enrichment"})
        if u.path == "/api/enhancement/batch-run":
            if not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme as ações de workspace/build antes de gerar o enhancement global.")
            if self.ctx.jobs.has_active(None):
                return self._error(409, "GLOBAL_JOB_ALREADY_RUNNING", "Já existe uma tarefa ativa. Aguarde ou cancele antes de iniciar o enhancement global.")
            tcaps = texture_upscale_capability_status()
            backend = str(body.get("backend") or "realesrgan").strip().lower()
            profile = str(body.get("profile") or "detail").strip().lower()
            scale = str(body.get("scale") or "4").strip()
            if scale not in {"2", "3", "4"}:
                return self._error(400, "TEXTURE_UPSCALE_SCALE_INVALID")
            if backend not in {"auto", "lanczos", "realesrgan"}:
                return self._error(400, "TEXTURE_UPSCALE_BACKEND_INVALID")
            if profile not in {"faithful", "balanced", "detail", "pixel-art"}:
                return self._error(400, "TEXTURE_QUALITY_PROFILE_INVALID")
            if backend == "realesrgan" and not bool(tcaps.get("realesrgan_ready")):
                return self._error(409, "TEXTURE_UPSCALE_REALESRGAN_UNAVAILABLE", "Real-ESRGAN não está disponível neste ambiente.")
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "texture-upscale", "run", "--all", "--include-ui",
                "--scale", scale, "--backend", backend, "--profile", profile,
                "--gpu", str(int(body.get("gpu") or 0)),
                "--model", str(body.get("model") or "realesrgan-x4plus"),
            ]
            job = self.ctx.jobs.submit("enhancement_batch_run", None, cmd, surface="client", workflow="enhancement", result_anchor="clientEnhancementBatchSummary")
            return self._json(202, {"ok": True, "job": job.public(), "mode": "enhancement_batch_run"})
        if u.path == "/api/enhancement/batch-resume":
            if not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme as ações de workspace/build antes de retomar o enhancement global.")
            if self.ctx.jobs.has_active(None):
                return self._error(409, "GLOBAL_JOB_ALREADY_RUNNING", "Já existe uma tarefa ativa. Aguarde ou cancele antes de retomar o enhancement global.")
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "texture-upscale", "resume",
            ]
            job = self.ctx.jobs.submit("enhancement_batch_resume", None, cmd, surface="client", workflow="enhancement", result_anchor="clientEnhancementBatchSummary")
            return self._json(202, {"ok": True, "job": job.public(), "mode": "enhancement_batch_resume"})
        if u.path == "/api/enhancement/batch-publish":
            if not self.ctx.deploy_armed:
                return self._error(409, "CLIENT_DEPLOY_NOT_ARMED", "Arme explicitamente o deploy do client antes de publicar o lote de enhancement.")
            if self.ctx.jobs.has_active(None):
                return self._error(409, "GLOBAL_JOB_ALREADY_RUNNING", "Já existe uma tarefa ativa. Aguarde ou cancele antes de publicar o lote.")
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "texture-upscale", "publish-batch",
                "--confirm", "APPLY CLIENT ENHANCEMENT BATCH",
            ]
            job = self.ctx.jobs.submit("enhancement_batch_publish", None, cmd, surface="client", workflow="enhancement", result_anchor="clientEnhancementBatchSummary")
            self.ctx.disarm_deploy()
            return self._json(202, {"ok": True, "job": job.public(), "mode": "enhancement_batch_publish"})
        if u.path == "/api/enhancement/batch-restore":
            if not self.ctx.deploy_armed:
                return self._error(409, "CLIENT_DEPLOY_NOT_ARMED", "Arme explicitamente o deploy do client antes de restaurar o lote de enhancement.")
            if self.ctx.jobs.has_active(None):
                return self._error(409, "GLOBAL_JOB_ALREADY_RUNNING", "Já existe uma tarefa ativa. Aguarde ou cancele antes de restaurar o lote.")
            cmd = [
                "python3", str(self.ctx.project_root / "pt_asset.py"),
                "--client-root", str(self.ctx.client_root),
                "texture-upscale", "restore-batch",
                "--confirm", "RESTORE CLIENT ENHANCEMENT BATCH",
            ]
            job = self.ctx.jobs.submit("enhancement_batch_restore", None, cmd, surface="client", workflow="enhancement", result_anchor="clientEnhancementBatchSummary")
            self.ctx.disarm_deploy()
            return self._json(202, {"ok": True, "job": job.public(), "mode": "enhancement_batch_restore"})
        if u.path == "/api/particles/stage-edit":
            try:
                result = particle_service.apply_stage_edit(
                    self.ctx.client_root, self.ctx.project_root / "pt_build" / "devtest", body
                )
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "PARTICLE_STAGE_EDIT_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/particles/preview-plan":
            try:
                result = particle_service.build_effect_preview(
                    self.ctx.client_root, self.ctx.project_root / "pt_build" / "devtest",
                    self.ctx.project_root, str(body.get("asset") or "")
                )
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "PARTICLE_PREVIEW_PLAN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/particles/preview-run":
            try:
                result = particle_service.run_effect_preview(
                    self.ctx.client_root, self.ctx.project_root / "pt_build" / "devtest",
                    self.ctx.project_root, str(body.get("asset") or ""), self.ctx.particle_preview_lock
                )
                return self._json(200, {"ok": True, "result": result})
            except FileNotFoundError as exc:
                return self._error(409, "PARTICLE_BLENDER_DEPENDENCY_MISSING", str(exc))
            except Exception as exc:
                return self._error(400, "PARTICLE_PREVIEW_RUN_FAILED", f"{type(exc).__name__}:{exc}")
        if u.path == "/api/contracts/analyze":
            if self.ctx.source_root is None or not self.ctx.source_root.is_dir():
                return self._error(409, "SOURCE_ROOT_REQUIRED", "Configure o source Summit primeiro.")
            if self.ctx.reference_source_root is None or not self.ctx.reference_source_root.is_dir():
                return self._error(409, "REFERENCE_SOURCE_ROOT_REQUIRED", "Configure o source EU de referência primeiro.")
            mode = str(body.get("mode") or "source").strip().lower()
            surface = str(body.get("surface") or "server").strip().lower()
            if surface not in {"server", "client"}:
                return self._error(400, "CONTRACT_ANALYSIS_SURFACE_INVALID")
            if mode not in {"source", "player_classes", "aggregate_player_classes", "aggregate_summit", "general_census"}:
                return self._error(400, "CONTRACT_ANALYSIS_MODE_INVALID")
            census_preflight = None
            if mode == "general_census":
                census_preflight = build_general_census_readiness(
                    self.ctx.project_root, self.ctx.client_root, self.ctx.server_root,
                    self.ctx.source_root, self.ctx.reference_source_root,
                    self.ctx.contract_donor_clients, self.ctx.contract_donor_servers,
                )
                if not census_preflight.get("can_run"):
                    return self._error(409, "GENERAL_CENSUS_PREFLIGHT_BLOCKED", "O Censo geral está bloqueado pelo preflight. Corrija os roots/donors mostrados na aba Servidor e salve novamente.")
                if self.ctx.jobs.has_active(None, "contracts_general_census"):
                    return self._error(409, "GENERAL_CENSUS_ALREADY_RUNNING", "Já existe um Censo geral iniciado pela GUI em execução. Acompanhe-o na área de Atividade do workflow que o iniciou.")
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
            workflow_map = {
                "source": ("diagnostics", "sourceContractsSummary"),
                "player_classes": ("diagnostics", "playerContractsSummary"),
                "aggregate_player_classes": ("census", "playerAggregateSummary"),
                "aggregate_summit": ("census", "summitAggregateSummary"),
                "general_census": ("census", "generalCensusPanel"),
            }
            workflow, result_anchor = workflow_map[mode]
            if surface == "client":
                client_workflow_map = {
                    "source": ("diagnostics", "clientFullEnrichmentSummary"),
                    "player_classes": ("diagnostics", "clientPlayerSummary"),
                    "aggregate_player_classes": ("census", "clientCensusPanel"),
                    "aggregate_summit": ("census", "clientCensusPanel"),
                    "general_census": ("census", "clientCensusPanel"),
                }
                workflow, result_anchor = client_workflow_map[mode]
            job = self.ctx.jobs.submit(
                f"contracts_{mode}", None, cmd,
                surface=surface, workflow=workflow, result_anchor=result_anchor,
            )
            payload = {"ok": True, "job": job.public(), "mode": mode}
            if census_preflight is not None:
                payload["preflight"] = census_preflight
            return self._json(202, payload)
        if u.path == "/api/legacy-authoring/stage":
            if self.ctx.server_root is None or not self.ctx.server_root.is_dir():
                return self._error(409, "SERVER_ROOT_REQUIRED", "Configure a raiz do servidor primeiro.")
            if not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme workspace/build antes de criar o draft de authoring.")
            spec = body.get("spec") if isinstance(body.get("spec"), dict) else body
            try:
                result = stage_authoring(self.ctx.project_root, self.ctx.server_root, self.ctx.client_root, spec)
                return self._json(200, {"ok": True, "result": result})
            except Exception as exc:
                return self._error(400, "LEGACY_AUTHORING_STAGE_REJECTED", f"{type(exc).__name__}:{exc}")
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
            surface = str(body.get("surface") or "server").strip().lower()
            if surface not in {"server", "client"}:
                return self._error(400, "SERVER_ANALYSIS_SURFACE_INVALID")
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
            workflow_map = {
                "environment": ("diagnostics", "serverEnvironmentSummary"),
                "inventory": ("diagnostics", "serverInventorySummary"),
                "vendor_plan": ("census", "serverVendorPlanSummary"),
                "vendor_graph": ("census", "serverVendorGraphSummary"),
                "design": ("validation", "serverMetrics"),
                "integration": ("validation", "serverIntegrationSummary"),
                # API compatibility: these reports still exist, but authoring/exploration
                # is surfaced only in Management Legacy.
                "entities": ("validation", "serverEntitiesSummary"),
                "fields": ("validation", "serverFieldsSummary"),
                "items": ("validation", "serverItemsSummary"),
            }
            workflow, result_anchor = workflow_map[mode]
            if surface == "client":
                client_workflow_map = {
                    "environment": ("diagnostics", "clientFullEnrichmentSummary"),
                    "inventory": ("diagnostics", "clientRegistrySummary"),
                    "vendor_plan": ("census", "clientCensusPanel"),
                    "vendor_graph": ("census", "clientGraphSummary"),
                    "design": ("validation", "clientValidationPanel"),
                    "integration": ("validation", "clientValidationPanel"),
                    "entities": ("validation", "clientValidationPanel"),
                    "fields": ("validation", "clientValidationPanel"),
                    "items": ("validation", "clientValidationPanel"),
                }
                workflow, result_anchor = client_workflow_map[mode]
            job = self.ctx.jobs.submit(
                f"server_{mode}", None, cmd,
                surface=surface, workflow=workflow, result_anchor=result_anchor,
            )
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
                    result = stage_spc_native(
                        self.ctx.project_root, self.ctx.server_root, rel,
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
                backend = str(options.get("backend") or "auto").strip().lower()
                profile = str(options.get("profile") or "balanced").strip().lower()
                if backend not in {"auto", "lanczos", "realesrgan"}:
                    return self._error(400, "TEXTURE_UPSCALE_BACKEND_INVALID")
                if profile not in {"faithful", "balanced", "detail", "pixel-art"}:
                    return self._error(400, "TEXTURE_QUALITY_PROFILE_INVALID")
                if profile == "pixel-art" and backend == "realesrgan":
                    return self._error(400, "TEXTURE_PIXEL_ART_AI_INVALID", "pixel-art deve usar auto ou Lanczos.")
                if backend == "realesrgan" and not bool(tcaps.get("realesrgan_ready")):
                    return self._error(409, "TEXTURE_UPSCALE_REALESRGAN_UNAVAILABLE", "realesrgan-ncnn-vulkan não foi encontrado; use Auto/Lanczos ou instale/configure o executável.")
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
            if spec.mutates_client and not self.ctx.deploy_armed:
                return self._error(409, "CLIENT_DEPLOY_NOT_ARMED", "Arme explicitamente o deploy do client antes de publicar/restaurar um bundle.")
            # A client-deploy arm is stronger and one-shot; it also authorizes the
            # pt_build transaction preparation required by publish/restore.
            if spec.mutates_build and not spec.mutates_client and not self.ctx.write_armed:
                return self._error(409, "BUILD_WRITE_NOT_ARMED", "Arme temporariamente as ações de workspace/build no painel de Segurança.")
            if spec.mutates_build and self.ctx.jobs.has_active(rel):
                return self._error(409, "ASSET_EDIT_ALREADY_RUNNING", "Já existe uma tarefa ativa para este asset; aguarde ou cancele-a antes de iniciar outra edição/build.")
            try:
                cmd = build_command(self.ctx.project_root, action, rel, options)
            except Exception as exc:
                return self._error(400, "ACTION_BUILD_FAILED", str(exc))
            job = self.ctx.jobs.submit(action, rel, cmd, interactive=spec.interactive)
            if spec.mutates_client:
                self.ctx.disarm_deploy()
            return self._json(202, {"ok": True, "job": job.public(), "write_armed": self.ctx.write_armed, "deploy_armed": self.ctx.deploy_armed})
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
