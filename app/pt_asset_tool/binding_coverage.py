from __future__ import annotations

import collections
import pathlib

from .semantic_path import entity_folder_for_path, semantic_group_for_path
from typing import Any

FORMAT = "PT_BINDING_COVERAGE_AUDIT_V1"


def _semantic_group(path: str, fallback: str = "") -> str:
    return semantic_group_for_path(path, fallback)


def _entity_folder(path: str) -> str:
    return entity_folder_for_path(path)

def _note_key(note: str) -> str:
    raw = str(note or "").strip()
    if not raw:
        return "UNSPECIFIED"
    return raw.split("=", 1)[0].strip().upper() or "UNSPECIFIED"


def audit_binding_coverage(registry, *, category: str | None = None, sample_limit: int = 50) -> dict[str, Any]:
    """Summarize rigid Model0.62 binding readiness without changing evidence.

    The report deliberately does not promote folder/name similarity into a
    binding.  Entity folders are included only as navigation/triage context for
    unresolved assets; verified LinkFile/config/cache evidence remains the
    authority used by :class:`AssetRegistry`.
    """
    category_q = str(category or "").strip().upper()
    rows = [a for a in registry.assets if a.family == "SMD_MODEL_062_RIGID_PHYSIQUE"]
    if category_q:
        rows = [a for a in rows if _semantic_group(a.primary_path, a.category) == category_q]

    mode_counts = collections.Counter(str(a.binding_mode or "NONE") for a in rows)
    source_counts = collections.Counter(str(a.binding_source or "NONE") for a in rows)
    reason_counts: collections.Counter[str] = collections.Counter()
    unresolved = []
    for asset in rows:
        if asset.rigid_binding_ready:
            continue
        notes = list(asset.binding_notes or [])
        if notes:
            for note in notes:
                reason_counts[_note_key(note)] += 1
        else:
            reason_counts[f"BINDING_MODE_{str(asset.binding_mode or 'NONE').upper()}"] += 1
        unresolved.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "category": asset.category,
            "semantic_group": _semantic_group(asset.primary_path, asset.category),
            "entity_folder": _entity_folder(asset.primary_path),
            "config_count": len(asset.configs),
            "binding_mode": asset.binding_mode,
            "binding_source": asset.binding_source,
            "binding_notes": notes,
        })

    entity_counts = collections.Counter(
        row["entity_folder"] for row in unresolved if row.get("entity_folder")
    )
    ready = sum(1 for a in rows if a.rigid_binding_ready)
    animation_ready = sum(1 for a in rows if a.animation_binding_ready)
    physical_rows = [registry.physical_dependency_status(a) for a in rows]
    physical_ready = sum(1 for row in physical_rows if row.get("rigid_binding_ready_physical"))
    physical_animation_ready = sum(1 for row in physical_rows if row.get("animation_binding_ready_physical"))
    missing_dependency_counts = collections.Counter(
        item for row in physical_rows for item in (row.get("missing") or [])
    )
    total = len(rows)
    return {
        "format": FORMAT,
        "status": "PASS",
        "scope": "DIAGNOSTIC_ONLY_NO_BINDING_PROMOTION",
        "category_filter": category_q or None,
        "rigid_asset_count": total,
        "rigid_binding_ready_count": ready,
        "animation_binding_ready_count": animation_ready,
        "physical_rigid_binding_ready_count": physical_ready,
        "physical_animation_binding_ready_count": physical_animation_ready,
        "config_only_count": int(mode_counts.get("CONFIG_ONLY", 0)),
        "unresolved_binding_count": len(unresolved),
        "binding_ready_percent": round((ready * 100.0 / total), 3) if total else 0.0,
        "animation_ready_percent": round((animation_ready * 100.0 / total), 3) if total else 0.0,
        "physical_binding_ready_percent": round((physical_ready * 100.0 / total), 3) if total else 0.0,
        "physical_animation_ready_percent": round((physical_animation_ready * 100.0 / total), 3) if total else 0.0,
        "binding_mode_counts": dict(sorted(mode_counts.items())),
        "binding_source_counts": dict(sorted(source_counts.items())),
        "unresolved_reason_counts": dict(sorted(reason_counts.items())),
        "missing_physical_dependency_counts": dict(sorted(missing_dependency_counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))),
        "unresolved_entity_folder_counts": dict(sorted(entity_counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))),
        "unresolved_sample": unresolved[: max(0, int(sample_limit))],
        "unresolved_total": len(unresolved),
        "policy": {
            "folder_identity_is_binding_evidence": False,
            "filename_similarity_is_binding_evidence": False,
            "registry_binding_rules_unchanged": True,
        },
        "client_modified": False,
    }
