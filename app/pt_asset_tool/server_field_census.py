from __future__ import annotations

import collections
import json
import os
import pathlib
from typing import Any, Callable

from .server_bundle_census import _ci_resolve

FORMAT = "PT_ASSET_SERVER_FIELD_BUNDLE_CENSUS_V2"


def _runtime_basename(name: str) -> str:
    """Normalize stage companions generated from a configured logical stage.

    Real deployments contain forms such as ``ancientw.ase.spp``.  The runtime
    derives the companion key from the logical stage basename, so both
    ``ancientw.spp`` and ``ancientw.ase.spp`` map to ``ancientw``.
    """
    p = pathlib.PurePosixPath(name)
    stem = p.stem
    nested = pathlib.PurePosixPath(stem)
    if nested.suffix.casefold() in {".ase", ".smd"}:
        stem = nested.stem
    return stem.casefold()


def _field_stage_basename_index(server_root: pathlib.Path) -> dict[str, list[str]]:
    base = _ci_resolve(server_root, "Field", want_dir=True)
    out: dict[str, list[str]] = collections.defaultdict(list)
    if base is None:
        return out
    for walk_base, dirs, files in os.walk(base):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in files:
            ext = pathlib.PurePosixPath(name).suffix.casefold()
            if ext not in {".smd", ".ase"}:
                continue
            p = pathlib.Path(walk_base) / name
            rel = p.relative_to(server_root).as_posix()
            out[_runtime_basename(name)].append(rel)
    return out


def _select_runtime_stage(candidates: list[str]) -> tuple[str | None, str, list[str]]:
    """Mirror smSTAGE3D_ReadASE preference: compiled SMD before textual ASE."""
    smd = sorted([x for x in candidates if pathlib.PurePosixPath(x).suffix.casefold() == ".smd"], key=str.casefold)
    ase = sorted([x for x in candidates if pathlib.PurePosixPath(x).suffix.casefold() == ".ase"], key=str.casefold)
    if len(smd) == 1:
        return smd[0], "UNIQUE_SMD_RUNTIME_PREFERENCE", []
    if len(smd) > 1:
        return None, "AMBIGUOUS_MULTIPLE_SMD", ["AMBIGUOUS_STAGE_BASENAME"]
    if len(ase) == 1:
        return ase[0], "UNIQUE_ASE_FALLBACK", []
    if len(ase) > 1:
        return None, "AMBIGUOUS_MULTIPLE_ASE", ["AMBIGUOUS_STAGE_BASENAME"]
    return None, "NONE", ["NO_STAGE_BASENAME_MATCH"]


def audit_server_field_bundles(
    project_root: pathlib.Path,
    server_root: pathlib.Path,
    *,
    sample_limit: int = 50,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    server_root = pathlib.Path(server_root).resolve()
    meta_root = _ci_resolve(server_root, "GameServer/Field", want_dir=True)
    report_dir = project_root / "pt_build" / "devtest" / "server_field_census"
    report_path = report_dir / "result.json"

    companions: dict[str, dict[str, pathlib.Path]] = collections.defaultdict(dict)
    if meta_root is not None:
        for walk_base, dirs, files in os.walk(meta_root):
            dirs.sort(key=str.casefold)
            files.sort(key=str.casefold)
            for name in files:
                p = pathlib.Path(walk_base) / name
                ext = p.suffix.casefold()
                if ext in {".spm", ".spp", ".spc"}:
                    key = _runtime_basename(name)
                    # Duplicate same-type companions for one basename are not
                    # silently overwritten; encode them as an ambiguity later.
                    if ext in companions[key]:
                        companions[key][f"{ext}#duplicate"] = p
                    else:
                        companions[key][ext] = p

    stage_index = _field_stage_basename_index(server_root)
    rows: list[dict[str, Any]] = []
    status_counts: collections.Counter[str] = collections.Counter()
    stage_selection_counts: collections.Counter[str] = collections.Counter()

    for idx, stem in enumerate(sorted(companions), start=1):
        c = companions[stem]
        spp = c.get(".spp")
        spc = c.get(".spc")
        spm = c.get(".spm")
        spp_size = spp.stat().st_size if spp else None
        spc_size = spc.stat().st_size if spc else None
        stages = sorted(stage_index.get(stem, []), key=str.casefold)
        selected_stage, selection_basis, stage_reasons = _select_runtime_stage(stages)
        stage_selection_counts[selection_basis] += 1

        reasons: list[str] = list(stage_reasons)
        if any(k.endswith("#duplicate") for k in c):
            reasons.append("DUPLICATE_COMPANION_TYPE")
        if spp and spp_size != 2400:
            reasons.append("SPP_NON_SUMMIT_2400_LAYOUT")
        if spc and spc_size != 50400:
            reasons.append("SPC_NON_SUMMIT_50400_LAYOUT")
        if not spm:
            reasons.append("SPM_NOT_PRESENT")
        if not spp:
            reasons.append("SPP_NOT_PRESENT")
        if not spc:
            reasons.append("SPC_NOT_PRESENT")

        if not reasons:
            status = "COMPANIONS_AND_STAGE_RESOLVED"
        elif any(
            r.startswith("SPP_NON")
            or r.startswith("SPC_NON")
            or r.startswith("AMBIGUOUS")
            or r == "DUPLICATE_COMPANION_TYPE"
            for r in reasons
        ):
            status = "REVIEW_LAYOUT_OR_STAGE_AMBIGUITY"
        else:
            status = "PARTIAL_BUNDLE"
        status_counts[status] += 1
        rows.append({
            "basename": stem,
            "status": status,
            "spm": spm.relative_to(server_root).as_posix() if spm else None,
            "spp": spp.relative_to(server_root).as_posix() if spp else None,
            "spp_size": spp_size,
            "spp_layout": "SUMMIT_200x12" if spp_size == 2400 else ("LEGACY_50x12" if spp_size == 600 else ("OTHER" if spp else None)),
            "spc": spc.relative_to(server_root).as_posix() if spc else None,
            "spc_size": spc_size,
            "spc_layout": "SUMMIT_100x504" if spc_size == 50400 else ("OTHER" if spc else None),
            "stage_candidates": stages,
            "selected_stage": selected_stage,
            "stage_selection_basis": selection_basis,
            "reasons": reasons,
        })
        if progress and (idx == 1 or idx == len(companions) or idx % 25 == 0):
            progress(f"SERVER_FIELDS {idx}/{len(companions)} {stem}")

    unresolved = [r for r in rows if r["status"] != "COMPANIONS_AND_STAGE_RESOLVED"]
    result = {
        "format": FORMAT,
        "status": "PASS",
        "audit_completed": True,
        "server_root": str(server_root),
        "field_bundle_count": len(rows),
        "resolved_count": status_counts.get("COMPANIONS_AND_STAGE_RESOLVED", 0),
        "unresolved_count": len(unresolved),
        "status_counts": dict(sorted(status_counts.items())),
        "stage_selection_counts": dict(sorted(stage_selection_counts.items())),
        "unresolved_sample": unresolved[:sample_limit],
        "rows": rows,
        "scope": {
            "stage_match": "RUNTIME_LOGICAL_BASENAME; SMD preferred over ASE as smSTAGE3D_ReadASE does",
            "companion_normalization": "foo.ext and foo.ase.ext both map to logical basename foo",
            "spp_expected_layout": "200x12=2400 bytes",
            "spc_expected_layout": "100x504=50400 bytes",
            "stage072_server_write_certified": False,
            "spc_free_authoring_certified": False,
        },
        "server_write_authorized": False,
        "report": str(report_path),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
