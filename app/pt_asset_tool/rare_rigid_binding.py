from __future__ import annotations

import json
import pathlib
import zipfile
from typing import Any

from .motion_core import load_smb_evaluator, parse_inx_link_header, verified_inx_link_target
from .rare_rigid_context import RARE_SMD_FILES, parse_model062_physique_context
from .rare_support import prepare_model062_tooling_source
from .utils import low_path, norm_path, sha256_file, truth


def _row_model(reg, row: dict) -> str:
    try:
        return norm_path(reg._row_model(row))
    except Exception:
        return norm_path(row.get("model_smd") or "")


def _row_motion(reg, row: dict) -> str:
    try:
        return norm_path(reg._row_motion(row))
    except Exception:
        return norm_path(row.get("motion_smb") or "")


def _row_inx(row: dict) -> str:
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


def _pair_rows_by_inx(reg) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in reg.pairing:
        inx = _row_inx(row)
        if inx:
            out.setdefault(low_path(inx), []).append(row)
    return out


def audit_rare_rigid_binding(reg, resolver, *, project_root: pathlib.Path, work: pathlib.Path, bundle: str | None = None) -> dict[str, Any]:
    """Resolve the six rare rigid Model0.62 files through their serialized INX LinkFile chain.

    Evidence chain required for authorization:
      rare SMD -> exact paired source INX -> verified SpeedSum LinkFile -> physical target INX
      -> target file_code == source link_code -> unique target motion SMB from physical pairing
      -> physical SMB contains every serialized Physique bone name.

    No basename/path similarity participates in the decision.
    """
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    prepared_root = work / "prepared_model062"
    prepared_root.mkdir(parents=True, exist_ok=True)
    by_inx = _pair_rows_by_inx(reg)
    evaluator = load_smb_evaluator(project_root)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    bundle_files: dict[str, pathlib.Path] = {}

    for logical in RARE_SMD_FILES:
        try:
            src = pathlib.Path(resolver.resolve(logical, required=True))
            prepared = prepared_root / pathlib.PurePosixPath(logical)
            prep = prepare_model062_tooling_source(src, prepared)
            phys = parse_model062_physique_context(prepared)
            rare_bones = set(phys["bind_bones"])

            source_pairings = []
            for prow in reg.pairing:
                if low_path(_row_model(reg, prow)) != low_path(logical):
                    continue
                inx = _row_inx(prow)
                if inx:
                    source_pairings.append(inx)
            source_pairings = sorted(set(source_pairings), key=str.lower)
            if not source_pairings:
                raise ValueError("no exact source INX pairing")

            links: list[dict[str, Any]] = []
            resolved_motion_set: set[str] = set()
            all_link_bones_ok = True
            for source_inx in source_pairings:
                source_path = _resolve_optional(resolver, source_inx)
                if source_path is None or not source_path.is_file():
                    raise ValueError(f"source INX missing: {source_inx}")
                link = verified_inx_link_target(source_path)
                if link.get("status") != "VERIFIED":
                    raise ValueError(f"source INX LinkFile not verified: {source_inx}: {link.get('status')}")
                target_inx = norm_path(str(link.get("target") or ""))
                target_path = _resolve_optional(resolver, target_inx)
                if target_path is None or not target_path.is_file():
                    raise ValueError(f"verified target INX missing: {target_inx}")
                target_header = parse_inx_link_header(target_path)
                if int(target_header.get("file_code") or -1) != int(link.get("link_code") or -2):
                    raise ValueError(f"target file_code mismatch: {source_inx} -> {target_inx}")

                target_pair_rows = by_inx.get(low_path(target_inx), [])
                motions = sorted({_row_motion(reg, r) for r in target_pair_rows if _row_motion(reg, r)}, key=str.lower)
                roots = sorted({
                    _row_model(reg, r) for r in target_pair_rows
                    if _row_model(reg, r) and ("model_resolved" not in r or truth(r.get("model_resolved")))
                }, key=str.lower)
                if len(motions) != 1:
                    raise ValueError(f"target INX motion {'ambiguous' if motions else 'unresolved'}: {target_inx}: {motions}")
                motion = motions[0]
                motion_path = _resolve_optional(resolver, motion)
                if motion_path is None or not motion_path.is_file():
                    raise ValueError(f"target motion SMB missing: {motion}")

                smb = evaluator.parse_smb(motion_path)
                smb_bones = [str(b.get("name") or "") for b in smb.get("bones", [])]
                smb_bone_set = {b for b in smb_bones if b}
                missing_bones = sorted(rare_bones - smb_bone_set, key=str.lower)
                bones_ok = not missing_bones
                all_link_bones_ok = all_link_bones_ok and bones_ok
                resolved_motion_set.add(motion)

                physical_roots = []
                for root in roots:
                    rp = _resolve_optional(resolver, root)
                    if rp is not None and rp.is_file():
                        physical_roots.append(root)
                        bundle_files[f"binding_roots/{root}"] = rp

                links.append({
                    "source_inx": source_inx,
                    "source_inx_sha256": sha256_file(source_path),
                    "source_file_code": int(link.get("file_code") or 0),
                    "serialized_link_file": str(link.get("link_file") or ""),
                    "link_code": int(link.get("link_code") or 0),
                    "link_status": "VERIFIED",
                    "target_inx": target_inx,
                    "target_inx_sha256": sha256_file(target_path),
                    "target_file_code": int(target_header.get("file_code") or 0),
                    "target_code_exact": True,
                    "motion_smb": motion,
                    "motion_smb_sha256": sha256_file(motion_path),
                    "motion_bone_count": len(smb_bones),
                    "rare_bind_bones_missing_from_motion": missing_bones,
                    "rare_bind_bones_subset_motion": bones_ok,
                    "root_models": roots,
                    "physical_root_models": physical_roots,
                })
                bundle_files[f"source_context/{source_inx}"] = source_path
                bundle_files[f"target_context/{target_inx}"] = target_path
                bundle_files[f"target_context/{motion}"] = motion_path

            if len(resolved_motion_set) != 1:
                raise ValueError(f"source INXs resolve to multiple motion SMBs: {sorted(resolved_motion_set)}")
            resolved_motion = next(iter(resolved_motion_set))
            authorized = all_link_bones_ok and bool(links)
            row = {
                "logical": logical,
                "source_sha256": sha256_file(src),
                "physical_family": prep["family"],
                "physique_mode": phys["physique_mode"],
                "bind_bones": phys["bind_bones"],
                "bind_bone_count": phys["bind_bone_count"],
                "source_inx_count": len(source_pairings),
                "source_inxs": source_pairings,
                "verified_links": links,
                "resolved_motion_smb": resolved_motion,
                "binding_status": "VERIFIED_INX_LINK_SKELETON" if authorized else "BONE_SET_MISMATCH",
                "preview_binding_authorized": authorized,
                "binding_write_authorized": False,
                "client_modified": False,
            }
            rows.append(row)
            bundle_files[f"client/{logical}"] = src
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})

    expected = len(RARE_SMD_FILES)
    verified = sum(r.get("binding_status") == "VERIFIED_INX_LINK_SKELETON" for r in rows)
    all_links = sum(len(r.get("verified_links") or []) for r in rows)
    motions = sorted({r.get("resolved_motion_smb") for r in rows if r.get("resolved_motion_smb")}, key=str.lower)
    status = "PASS" if len(rows) == expected and verified == expected and not errors else "FAIL"
    result = {
        "format": "PT_RARE_MODEL062_RIGID_BINDING_V1",
        "status": status,
        "expected_rare_model062": expected,
        "physically_audited": len(rows),
        "verified_binding_files": verified,
        "verified_source_links": all_links,
        "resolved_motion_smb_count": len(motions),
        "resolved_motion_smb": motions,
        "errors": errors,
        "rare_rigid_binding_resolution_complete_candidate": status == "PASS",
        "preview_integration_authorized": status == "PASS",
        "binding_write_authorized": False,
        "policy": {
            "authority": "serialized source INX LinkFile + SpeedSum code + physical target INX file_code + exact target pairing motion",
            "bone_gate": "every serialized rare Physique bone name must exist in the resolved physical SMB",
            "preview": "binding may be used for read-only Blender preview only after all gates pass",
            "write": "no Model0.62 geometry/Physique write authorization is implied",
            "client_modified": False,
        },
        "rows": rows,
    }
    report_path = work / "rare_rigid_binding_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(report_path)

    if bundle:
        bundle_path = pathlib.Path(bundle).expanduser()
        if not bundle_path.is_absolute():
            bundle_path = pathlib.Path.cwd() / bundle_path
        bundle_path = bundle_path.resolve()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = dict(result)
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("RARE_RIGID_BINDING_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for arc, physical in sorted(bundle_files.items(), key=lambda kv: kv[0].lower()):
                zf.write(physical, arcname=arc)
        result["bundle"] = str(bundle_path)
    return result
