from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

from .server_bundle_census import audit_server_entity_bundles
from .server_environment_validation import run_server_environment_validation
from .server_field_census import audit_server_field_bundles
from .server_item_census import audit_server_item_bundles
from .server_inventory import audit_server_inventory

FORMAT = "PT_ASSET_SERVER_DESIGN_AUTO_V1"


def run_server_design_auto(
    settings,
    *,
    server_root: str | pathlib.Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(server_root or getattr(settings, "server_root", "")).expanduser().resolve() if (server_root or getattr(settings, "server_root", None)) else None
    project = pathlib.Path(settings.project_root).resolve()
    client = pathlib.Path(settings.client_root).resolve()
    report_dir = project / "pt_build" / "devtest" / "server_design_auto"
    report_path = report_dir / "result.json"

    def emit(msg: str):
        if progress:
            progress(msg)

    emit("START environment")
    environment = run_server_environment_validation(settings, server_root=root)
    emit(f"DONE environment status={environment.get('status')}")
    if environment.get("status") != "PASS" or root is None:
        result = {
            "format": FORMAT,
            "status": "FAIL",
            "server_design_catalog_ready": False,
            "environment": environment,
            "server_write_authorized": False,
            "client_write_authorized": False,
            "report": str(report_path),
        }
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    emit("START inventory")
    inventory = audit_server_inventory(
        project, root, progress_every=10000, sample_limit=12, progress=lambda m: emit(m)
    )
    emit(f"DONE inventory status={inventory.get('status')} files={inventory.get('total_files')}")

    emit("START entity_bundles")
    entities = audit_server_entity_bundles(project, root, client, progress=lambda m: emit(m))
    emit(f"DONE entity_bundles unresolved={entities.get('unresolved_count')}")

    emit("START field_bundles")
    fields = audit_server_field_bundles(project, root, progress=lambda m: emit(m))
    emit(f"DONE field_bundles unresolved={fields.get('unresolved_count')}")

    emit("START item_bundles")
    items = audit_server_item_bundles(project, root, progress=lambda m: emit(m))
    emit(f"DONE item_bundles review={items.get('review_count')}")

    unresolved = int(entities.get("unresolved_count") or 0) + int(fields.get("unresolved_count") or 0) + int(items.get("review_count") or 0)
    result = {
        "format": FORMAT,
        "status": "PASS",
        "server_design_catalog_ready": True,
        "bundle_closure_complete": unresolved == 0,
        "unresolved_or_review_count": unresolved,
        "environment": {
            "status": environment.get("status"),
            "report": environment.get("report"),
            "shared_sample_count": len(environment.get("client_server_shared_samples") or []),
        },
        "inventory": {
            "status": inventory.get("status"),
            "total_files": inventory.get("total_files"),
            "total_bytes": inventory.get("total_bytes"),
            "asset_candidate_files": inventory.get("asset_candidate_files"),
            "design_visible_files": inventory.get("design_visible_files"),
            "hard_excluded_files": inventory.get("hard_excluded_files"),
            "lifecycle_counts": inventory.get("lifecycle_counts"),
            "layout_counts": inventory.get("layout_counts"),
            "report": inventory.get("report"),
        },
        "entity_bundles": {
            "definition_count": entities.get("definition_count"),
            "resolved_visual_entry_count": entities.get("resolved_visual_entry_count"),
            "unresolved_count": entities.get("unresolved_count"),
            "reason_counts": entities.get("reason_counts"),
            "report": entities.get("report"),
        },
        "field_bundles": {
            "field_bundle_count": fields.get("field_bundle_count"),
            "resolved_count": fields.get("resolved_count"),
            "unresolved_count": fields.get("unresolved_count"),
            "status_counts": fields.get("status_counts"),
            "report": fields.get("report"),
        },
        "item_bundles": {
            "item_definition_count": items.get("item_definition_count"),
            "identity_parsed_count": items.get("identity_parsed_count"),
            "review_count": items.get("review_count"),
            "duplicate_code_count": items.get("duplicate_code_count"),
            "reason_counts": items.get("reason_counts"),
            "report": items.get("report"),
        },
        "policy": {
            "server_tree_is_separate_root": True,
            "persistence_logs_security_excluded": True,
            "configs_review_only": True,
            "shared_3d_requires_reference_and_pt_asset_validation": True,
            "this_gate_is_catalog_discovery_not_authoring_certification": True,
        },
        "server_write_authorized": False,
        "persistence_write_authorized": False,
        "client_write_authorized": False,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
