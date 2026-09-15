from __future__ import annotations

from collections import Counter
from typing import Any


def _raw_physique_mode(record: dict[str, Any]) -> tuple[str, int, int, str | None]:
    """Derive mode from per-object serialized Physique pointers.

    This deliberately does not trust compatibility_family.  A corpus absence
    claim is only valid when every Model0.62 object's header is represented in
    the inventory with a readable Physique pointer.
    """
    try:
        object_count = int(record.get("object_count") or 0)
    except Exception:
        return "UNKNOWN", 0, 0, "INVALID_OBJECT_COUNT"
    objects = record.get("objects") or []
    if object_count <= 0:
        return "UNKNOWN", object_count, 0, "ZERO_OR_MISSING_OBJECT_COUNT"
    if len(objects) != object_count:
        return "UNKNOWN", object_count, 0, f"OBJECT_HEADER_COUNT_MISMATCH:{len(objects)}"

    flags: list[bool] = []
    for i, obj in enumerate(objects):
        if not isinstance(obj, dict):
            return "UNKNOWN", object_count, sum(flags), f"OBJECT_HEADER_NOT_DICT:{i}"
        # The survey records bounds_ok and nVertex only after the Model0.62
        # object header has been read successfully.  Require both so a missing
        # ptr cannot silently become STATIC via dict.get(..., 0).
        if not obj.get("bounds_ok") or obj.get("nVertex") is None:
            return "UNKNOWN", object_count, sum(flags), f"OBJECT_HEADER_INCOMPLETE:{i}"
        if "physique_ptr" not in obj:
            return "UNKNOWN", object_count, sum(flags), f"PHYSIQUE_PTR_MISSING:{i}"
        flags.append(int(obj.get("physique_ptr") or 0) != 0)

    physique_count = sum(flags)
    if physique_count == object_count:
        return "RIGID", object_count, physique_count, None
    if physique_count == 0:
        return "STATIC", object_count, physique_count, None
    return "MIXED", object_count, physique_count, None


def audit_physique_modes(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit canonical SMD Model0.62 records for mixed Physique/static files."""
    smds = [r for r in records if r.get("kind") == "SMD_MODEL_062"]
    family_counts = Counter(str(r.get("compatibility_family") or "") for r in smds)
    raw_counts: Counter[str] = Counter()
    total_objects = 0
    total_physique_objects = 0
    mixed_files: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    family_mismatches: list[dict[str, Any]] = []
    variants: list[dict[str, Any]] = []

    expected_family = {
        "RIGID": "SMD_MODEL_062_RIGID_PHYSIQUE",
        "STATIC": "SMD_MODEL_062_STATIC",
        "MIXED": "SMD_MODEL_062_MIXED_PHYSIQUE",
    }

    for r in smds:
        mode, object_count, physique_count, error = _raw_physique_mode(r)
        rel = str(r.get("relative_path") or "")
        family = str(r.get("compatibility_family") or "")
        if error:
            incomplete.append({"path": rel, "error": error, "family": family})
            continue
        raw_counts[mode] += 1
        total_objects += object_count
        total_physique_objects += physique_count
        if mode == "MIXED":
            mixed_files.append({
                "path": rel,
                "object_count": object_count,
                "physique_objects": physique_count,
                "family": family,
            })
        if family == "SMD_MODEL_062_VARIANT_OR_DAMAGED":
            variants.append({
                "path": rel,
                "raw_physique_mode": mode,
                "object_count": object_count,
                "physique_objects": physique_count,
                "issues": r.get("issues") or [],
            })
        elif family != expected_family[mode]:
            family_mismatches.append({
                "path": rel,
                "raw_physique_mode": mode,
                "family": family,
                "expected_family": expected_family[mode],
            })

    unknown_smd = [r for r in records if r.get("kind") == "SMD_UNKNOWN"]
    stage_smd = [r for r in records if r.get("kind") == "SMD_STAGE_072"]

    complete = len(incomplete) == 0
    consistent = len(family_mismatches) == 0
    mixed_count = int(raw_counts.get("MIXED", 0))
    if not complete:
        status = "PHYSIQUE_AUDIT_INCOMPLETE"
        gate = "FAIL"
    elif not consistent:
        status = "PHYSIQUE_FAMILY_MISMATCH"
        gate = "FAIL"
    elif mixed_count:
        status = "MIXED_PHYSIQUE_PRESENT_UNSUPPORTED"
        gate = "FAIL"
    else:
        status = "NO_MIXED_MODEL_062_IN_CANONICAL_CORPUS"
        gate = "PASS"

    return {
        "format": "PT_PHYSIQUE_MODE_AUDIT_V1",
        "status": status,
        "compatibility_gate": gate,
        "smd_model_062_total": len(smds),
        "raw_mode_counts": {
            "RIGID": int(raw_counts.get("RIGID", 0)),
            "STATIC": int(raw_counts.get("STATIC", 0)),
            "MIXED": mixed_count,
            "UNKNOWN": len(incomplete),
        },
        "inventory_family_counts": dict(sorted(family_counts.items())),
        "object_headers_audited": total_objects,
        "physique_object_headers": total_physique_objects,
        "mixed_files": mixed_files,
        "incomplete_files": incomplete,
        "family_mismatches": family_mismatches,
        "variant_or_damaged_model062": variants,
        "stage_072_excluded": len(stage_smd),
        "unknown_smd_excluded": len(unknown_smd),
        "scope_note": "Stage0.72 and SMD_UNKNOWN are separate format/outlier scopes; this gate covers canonical SMD Model0.62 only.",
        "engineering_decision": (
            "Do not implement or certify mixed Physique authoring without a real canonical representative. "
            "Keep mixed input fail-closed; rerun this audit when the corpus changes."
        ),
    }
