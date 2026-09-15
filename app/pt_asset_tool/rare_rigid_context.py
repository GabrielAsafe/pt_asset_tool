from __future__ import annotations

import collections
import difflib
import json
import pathlib
import struct
import zipfile
from typing import Any

from .rare_support import ALT_MAGIC_SMD_FILES, LEGACY_NAME_MISMATCH_SMD_FILES, prepare_model062_tooling_source
from .utils import low_path, norm_path, sha256_file

SMD_HEADER = b"SMD Model data Ver 0.62"
SH, SI, SO = 556, 40, 2236
SV, SF, ST, SR, SP, SS, SM = 24, 36, 32, 20, 16, 16, 64
O_PHYS, O_NV, O_NF, O_NT, O_NR, O_NP, O_NS = 16, 84, 88, 92, 684, 688, 692

RARE_SMD_FILES = ALT_MAGIC_SMD_FILES + LEGACY_NAME_MISMATCH_SMD_FILES


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _cstring(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin1", "replace")


def parse_model062_physique_context(path: pathlib.Path) -> dict[str, Any]:
    """Read the serialized Physique tail without requiring a skeleton.

    This mirrors PT_CHARACTER_STRUCTURAL_GATE_V2's physical layout.  Pointer
    values are treated only as presence flags.  The actual per-vertex 32-byte
    bone-name strings are source truth for the dependency set.
    """
    data = pathlib.Path(path).read_bytes()
    if len(data) < SH or not data.startswith(SMD_HEADER):
        raise ValueError("not normalized SMD Model data Ver 0.62")
    object_count = _i32(data, 24)
    if object_count <= 0 or SH + object_count * SI > len(data):
        raise ValueError(f"invalid object_count={object_count}")

    objects = []
    all_bones: set[str] = set()
    physique_objects = 0
    total_vertices = 0
    total_faces = 0
    for idx in range(object_count):
        io = SH + idx * SI
        table_name = _cstring(data[io:io+32])
        obj_len = _i32(data, io + 32)
        obj_off = _i32(data, io + 36)
        if obj_off < 0 or obj_len < SO or obj_off + obj_len > len(data):
            raise ValueError(f"object[{idx}] invalid bounds")
        raw = data[obj_off:obj_off+SO]
        nv, nf, nt, nr, np, ns = [_i32(raw, o) for o in (O_NV, O_NF, O_NT, O_NR, O_NP, O_NS)]
        if min(nv, nf, nt, nr, np, ns) < 0:
            raise ValueError(f"object[{idx}] negative count")
        phys = _u32(raw, O_PHYS) != 0
        cur = obj_off + SO + nv*SV + nf*SF + nt*ST + nr*SR + np*SP + ns*SS + nr*SM
        bones: list[str] = []
        if phys:
            physique_objects += 1
            end = cur + nv * 32
            if end > obj_off + obj_len:
                raise ValueError(f"object[{idx}] Physique names truncated")
            for vi in range(nv):
                name = _cstring(data[cur + vi*32: cur + (vi+1)*32])
                if name:
                    bones.append(name)
                    all_bones.add(name)
            cur = end
        if cur != obj_off + obj_len:
            raise ValueError(f"object[{idx}] block length mismatch expected={obj_off+obj_len} got={cur}")
        total_vertices += nv
        total_faces += nf
        objects.append({
            "index": idx,
            "table_name": table_name,
            "vertices": nv,
            "faces": nf,
            "texlinks": nt,
            "physique": phys,
            "bind_bones": sorted(set(bones), key=str.lower),
        })

    mode = "RIGID" if physique_objects == object_count else ("STATIC" if physique_objects == 0 else "MIXED")
    return {
        "object_count": object_count,
        "physique_objects": physique_objects,
        "physique_mode": mode,
        "total_vertices": total_vertices,
        "total_faces": total_faces,
        "bind_bone_count": len(all_bones),
        "bind_bones": sorted(all_bones, key=str.lower),
        "objects": objects,
    }


def _pair_model(reg, row: dict) -> str:
    try:
        return norm_path(reg._row_model(row))
    except Exception:
        for key in ("model_smd", "model_smd_candidate", "model", "model_ref"):
            v = norm_path(row.get(key) or "")
            if v.lower().endswith(".smd"):
                return v
        return ""


def _pair_motion(reg, row: dict) -> str:
    try:
        return norm_path(reg._row_motion(row))
    except Exception:
        for key in ("motion_smb", "motion_smb_candidate", "motion", "motion_ref"):
            v = norm_path(row.get(key) or "")
            if v.lower().endswith(".smb"):
                return v
        return ""


def _pair_inx(row: dict) -> str:
    return norm_path(row.get("inx") or row.get("relative_path") or "")


def _resolve_optional(resolver, logical: str) -> pathlib.Path | None:
    if not logical:
        return None
    try:
        p = resolver.resolve(logical, required=False)
    except TypeError:
        try:
            p = resolver.resolve(logical)
        except Exception:
            return None
    except Exception:
        return None
    return pathlib.Path(p) if p else None


def _peer_similarity(a: str, b: str) -> float:
    aa = pathlib.PurePosixPath(a).stem.lower()
    bb = pathlib.PurePosixPath(b).stem.lower()
    return difflib.SequenceMatcher(a=aa, b=bb).ratio()


def audit_rare_rigid_context(reg, resolver, *, work: pathlib.Path, bundle: str | None = None) -> dict[str, Any]:
    work = pathlib.Path(work)
    prepared_root = work / "prepared_model062"
    prepared_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    # Parse the same-directory standard Model0.62 population once.  Exact bind
    # bone-set peers are diagnostic compatibility evidence, not binding proof.
    peer_pool: list[dict[str, Any]] = []
    rare_keys = {low_path(x) for x in RARE_SMD_FILES}
    for rec in reg.records:
        rel = norm_path(rec.get("relative_path") or "")
        if not rel or low_path(rel) in rare_keys or not rel.lower().startswith("char/tmabcd/") or not rel.lower().endswith(".smd"):
            continue
        src = _resolve_optional(resolver, rel)
        if src is None or not src.is_file():
            continue
        try:
            if src.read_bytes()[:24] != SMD_HEADER[:24]:
                continue
            ctx = parse_model062_physique_context(src)
        except Exception:
            continue
        if ctx["physique_mode"] != "RIGID":
            continue
        asset = getattr(reg, "by_primary", {}).get(low_path(rel))
        peer_pool.append({
            "logical": rel,
            "bind_bones": ctx["bind_bones"],
            "bind_bone_count": ctx["bind_bone_count"],
            "object_count": ctx["object_count"],
            "binding_mode": getattr(asset, "binding_mode", "") if asset else "",
            "binding_source": getattr(asset, "binding_source", "") if asset else "",
            "binding_skeleton_smb": getattr(asset, "binding_skeleton_smb", "") if asset else "",
            "binding_root_models": list(getattr(asset, "binding_root_models", []) or []) if asset else [],
            "family": getattr(asset, "family", "") if asset else norm_path(rec.get("compatibility_family") or ""),
        })

    bundle_files: dict[str, pathlib.Path] = {}
    for logical in RARE_SMD_FILES:
        try:
            src = resolver.resolve(logical, required=True)
            prepared = prepared_root / pathlib.PurePosixPath(logical)
            prep = prepare_model062_tooling_source(pathlib.Path(src), prepared)
            ctx = parse_model062_physique_context(prepared)
            exact_pairings = []
            inx_paths: list[str] = []
            motion_refs: list[str] = []
            for prow in reg.pairing:
                if low_path(_pair_model(reg, prow)) != low_path(logical):
                    continue
                inx = _pair_inx(prow)
                motion = _pair_motion(reg, prow)
                exact_pairings.append({
                    "inx": inx,
                    "model": _pair_model(reg, prow),
                    "motion_smb": motion,
                    "has_motion_ref": bool(motion),
                })
                if inx:
                    inx_paths.append(inx)
                if motion:
                    motion_refs.append(motion)

            same_bones = [p for p in peer_pool if p["bind_bones"] == ctx["bind_bones"]]
            for p in same_bones:
                p["similarity"] = round(_peer_similarity(logical, p["logical"]), 6)
            same_bones.sort(key=lambda p: (-p["similarity"], p["logical"].lower()))
            known_skeletons = collections.Counter(
                norm_path(p.get("binding_skeleton_smb") or "") for p in same_bones if p.get("binding_skeleton_smb")
            )
            known_sources = collections.Counter(
                str(p.get("binding_source") or "") for p in same_bones if p.get("binding_skeleton_smb")
            )

            inf_candidates = []
            stem_inf = str(pathlib.PurePosixPath(logical).with_suffix(".inf"))
            if _resolve_optional(resolver, stem_inf):
                inf_candidates.append(stem_inf)
            for inx in inx_paths:
                ii = str(pathlib.PurePosixPath(inx).with_suffix(".inf"))
                if ii not in inf_candidates and _resolve_optional(resolver, ii):
                    inf_candidates.append(ii)

            row = {
                "logical": logical,
                "source_sha256": sha256_file(pathlib.Path(src)),
                "physical_family": prep["family"],
                **ctx,
                "exact_pairing_count": len(exact_pairings),
                "exact_pairings": exact_pairings,
                "model_only_inx_count": sum(not x["has_motion_ref"] for x in exact_pairings),
                "motion_ref_inx_count": sum(x["has_motion_ref"] for x in exact_pairings),
                "inf_files": sorted(set(inf_candidates), key=str.lower),
                "exact_bindbone_peer_count": len(same_bones),
                "exact_bindbone_peer_sample": same_bones[:12],
                "peer_known_skeleton_counts": dict(sorted(known_skeletons.items())),
                "peer_binding_source_counts": dict(sorted(known_sources.items())),
                "binding_status": (
                    "EXPLICIT_MOTION_CONTEXT_PRESENT" if motion_refs else
                    "HEAD_ATTACHMENT_CONTEXT_REQUIRED" if ctx["bind_bones"] == ["Bip01 Head"] else
                    "MODEL_ONLY_CONFIG_CONTEXT_REQUIRED"
                ),
                "binding_write_authorized": False,
                "client_modified": False,
            }
            rows.append(row)

            bundle_files[f"client/{logical}"] = pathlib.Path(src)
            for inx in inx_paths:
                p = _resolve_optional(resolver, inx)
                if p and p.is_file():
                    bundle_files[f"client/{inx}"] = p
            for inf in inf_candidates:
                p = _resolve_optional(resolver, inf)
                if p and p.is_file():
                    bundle_files[f"client/{inf}"] = p
            # Include only a few exact-bindbone standard peers as physical controls.
            for peer in same_bones[:4]:
                p = _resolve_optional(resolver, peer["logical"])
                if p and p.is_file():
                    bundle_files[f"peer_controls/{peer['logical']}"] = p
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})

    expected = len(RARE_SMD_FILES)
    rigid_count = sum(r.get("physique_mode") == "RIGID" for r in rows)
    head_only = sum(r.get("bind_bones") == ["Bip01 Head"] for r in rows)
    body_rigid = sum(r.get("bind_bone_count", 0) > 1 for r in rows)
    pairings_found = sum(r.get("exact_pairing_count", 0) > 0 for r in rows)
    status = "PASS" if len(rows) == expected and rigid_count == expected and not errors else "FAIL"
    binding_complete = all(r.get("binding_status") == "EXPLICIT_MOTION_CONTEXT_PRESENT" for r in rows)
    result = {
        "format": "PT_RARE_MODEL062_RIGID_CONTEXT_V1",
        "status": status,
        "expected_rare_model062": expected,
        "physically_audited": len(rows),
        "rigid_physique_files": rigid_count,
        "head_only_bip01_head_files": head_only,
        "body_rigid_files": body_rigid,
        "files_with_exact_pairing_context": pairings_found,
        "errors": errors,
        "rare_rigid_physical_context_complete_candidate": status == "PASS",
        "rare_rigid_binding_resolution_complete_candidate": binding_complete,
        "preview_integration_authorized": binding_complete,
        "policy": {
            "physique": "all six rare Model0.62 files must be classified from serialized per-object Physique presence and per-vertex bone-name tails",
            "peer_controls": "exact bind-bone-set peers are diagnostic compatibility evidence only; they do not authorize a skeleton binding",
            "preview": "do not feed these files to the static/generic Model0.62 preview path until binding/attachment context is physically proven",
            "client_modified": False,
        },
        "rows": rows,
    }
    report_path = work / "rare_rigid_context_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(report_path)

    if bundle:
        bundle_path = pathlib.Path(bundle).expanduser()
        if not bundle_path.is_absolute():
            bundle_path = pathlib.Path.cwd() / bundle_path
        bundle_path = bundle_path.resolve()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = dict(result)
        manifest["rows"] = rows
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("RARE_RIGID_CONTEXT_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for arc, physical in sorted(bundle_files.items(), key=lambda kv: kv[0].lower()):
                zf.write(physical, arcname=arc)
        result["bundle"] = str(bundle_path)
    return result
