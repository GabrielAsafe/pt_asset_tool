from __future__ import annotations

from collections import Counter
from typing import Any

SZ_OBJ = 2236
SZ_VERT = 24
SZ_FACE = 36
SZ_TEX = 32


def _object_residual(obj: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return bytes after geometry/face/TexLink arrays in a no-Physique object.

    For Model0.62 static objects the proven serialized layout is:
      object header + vertices + faces + texlinks +
      rot_keys(20) + pos_keys(16) + scale_keys(16) + prevrot(64 * rot_keys)

    Therefore residual == 84*nRot + 16*nPos + 16*nScale.  A positive
    residual proves at least one object-local transform animation array exists,
    even though the inventory survey did not retain the individual key counts.
    """
    try:
        length = int(obj["length"])
        nv = int(obj["nVertex"])
        nf = int(obj["nFace"])
        nt = int(obj["nTexLink"])
    except Exception as exc:
        return None, f"MISSING_OBJECT_LAYOUT_FIELD:{type(exc).__name__}"
    if not obj.get("bounds_ok"):
        return None, "OBJECT_BOUNDS_NOT_VERIFIED"
    base = SZ_OBJ + nv * SZ_VERT + nf * SZ_FACE + nt * SZ_TEX
    residual = length - base
    if residual < 0:
        return None, f"NEGATIVE_SERIALIZED_RESIDUAL:{residual}"
    return residual, None


def audit_object_local(records: list[dict[str, Any]], limit: int = 50) -> dict[str, Any]:
    static = [r for r in records if r.get("compatibility_family") == "SMD_MODEL_062_STATIC"]
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    total_objects = 0
    animated_objects = 0
    static_only_objects = 0
    residual_bytes = 0

    for r in static:
        rel = str(r.get("relative_path") or "")
        hits = []
        objects = r.get("objects") or []
        for idx, obj in enumerate(objects):
            total_objects += 1
            residual, err = _object_residual(obj)
            if err:
                errors.append({"path": rel, "object_index": idx, "object": obj.get("name", ""), "error": err})
                continue
            if residual:
                animated_objects += 1
                residual_bytes += residual
                hits.append({
                    "index": idx,
                    "name": str(obj.get("name") or ""),
                    "serialized_animation_bytes": residual,
                })
            else:
                static_only_objects += 1
        if hits:
            cat = str(r.get("category_hint") or "UNKNOWN")
            category_counts[cat] += 1
            candidates.append({
                "path": rel,
                "category": cat,
                "object_count": int(r.get("object_count") or len(objects)),
                "animated_object_count": len(hits),
                "total_vertices": int(r.get("total_vertices") or 0),
                "total_faces": int(r.get("total_faces") or 0),
                "material_count": int(r.get("material_count") or 0),
                "objects": hits,
            })

    candidates.sort(key=lambda x: (x["category"], x["total_vertices"], x["object_count"], x["path"].lower()))
    representatives = []
    for category in ("WEAPON_ITEM", "EFFECT", "MAP_STAGE", "MOB_MONSTER", "UNKNOWN"):
        rows = [x for x in candidates if x["category"] == category]
        if rows:
            representatives.append(rows[0])

    complete = len(errors) == 0 and total_objects == sum(int(r.get("object_count") or 0) for r in static)
    return {
        "format": "PT_OBJECT_LOCAL_ANIMATION_DISCOVERY_V1",
        "status": "OBJECT_LOCAL_ANIMATION_CANDIDATES_FOUND" if complete and candidates else ("NO_OBJECT_LOCAL_CANDIDATES" if complete else "OBJECT_LOCAL_AUDIT_INCOMPLETE"),
        "discovery_gate": "PASS" if complete else "FAIL",
        "static_model062_files": len(static),
        "static_object_headers_audited": total_objects,
        "object_local_candidate_files": len(candidates),
        "object_local_candidate_objects": animated_objects,
        "plain_static_objects": static_only_objects,
        "serialized_animation_bytes_total": residual_bytes,
        "category_counts": dict(sorted(category_counts.items())),
        "representatives": representatives,
        "candidates": candidates[:max(0, int(limit))],
        "candidate_output_truncated": len(candidates) > max(0, int(limit)),
        "errors": errors,
        "semantics_note": "Positive residual proves object-local rot/pos/scale arrays exist under the known Model0.62 static object layout; exact nRot/nPos/nScale requires the physical SMD header.",
    }
