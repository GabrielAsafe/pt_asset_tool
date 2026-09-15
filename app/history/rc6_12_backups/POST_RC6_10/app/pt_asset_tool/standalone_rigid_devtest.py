from __future__ import annotations

import json
import pathlib
import re
import shutil
from collections import defaultdict
from typing import Any

from .authoring import authoring_plan, build_selected_authoring_context, build_standalone_rigid_authoring_context
from .blender_workspace import asset_workspace_name
from .build_provenance import sha256_file, write_build_provenance
from .release_1_coverage import content_domain
from .rigid_model_info import usable_model_info_configs, lod_model_info_configs, lod_node_coverage, effective_lod_node_coverage
from .rigid_authoring_candidate import build_rigid_candidate_blender_command
from .rigid_authoring_stress import validate_rigid_profile_stress_output
from .static_roundtrip import _parse as parse_model062_bytes
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_STANDALONE_RIGID_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_STANDALONE_RIGID_AUTOMATED_DEVTEST_BATCH_V1"
PROBE_FORMAT = "PT_STANDALONE_RIGID_SIBLING_SMB_PROBE_V1"


def _norm(value: str | None) -> str:
    return str(value or "").replace("\\", "/").strip("/")




def authorable_lod_model_info_contexts(asset, *, require_motion_smb: bool = False) -> list[dict[str, Any]]:
    """Return exact SMD-representable INX/LOD contexts for this rigid asset.

    LOD identity is independent from skeleton resolution.  When
    ``require_motion_smb`` is true this reduces to the legacy self-contained
    character context; otherwise equipment/model-info INX rows are included.
    """
    configs = usable_model_info_configs(asset) if require_motion_smb else lod_model_info_configs(asset)
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        for lod in ("high", "default", "low"):
            nodes = list((cfg.get("lod_groups") or {}).get(lod) or [])
            if not nodes:
                continue
            coverage = effective_lod_node_coverage(asset, cfg, lod)
            if coverage.get("status") == "PASS":
                rows.append({
                    "cfg": cfg, "inx": _norm(cfg.get("inx")), "lod": lod,
                    "nodes": list(coverage.get("effective_selected_nodes") or nodes), "coverage": coverage,
                    "motion_smb": _norm(cfg.get("motion_smb")),
                })
    return rows


def model_info_lod_context_available(asset) -> bool:
    """Whether a self-contained INX+skeleton context has an exact LOD."""
    return bool(authorable_lod_model_info_contexts(asset, require_motion_smb=True))


def model_info_lod_config_available(asset) -> bool:
    """Whether any associated INX has an exact LOD, regardless of skeleton source."""
    return bool(authorable_lod_model_info_contexts(asset, require_motion_smb=False))


def standalone_rigid_context_eligible(asset) -> bool:
    """Whether a rigid asset may use an explicit structural-skeleton context.

    This path is for rigid sources that lack a usable model-info+LOD authoring
    context.  An INX with no motion_smb or with no usable LOD groups does not,
    by itself, make the mesh authorable.  Conversely, a real model-info+LOD
    context must not be bypassed through the standalone path.
    """
    return (
        asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE"
        and not model_info_lod_context_available(asset)
    )


def _series_family_key(asset) -> tuple[str, str] | None:
    """Return (parent, alpha-prefix) for numbered rigid asset series.

    Examples: CmfbB01 -> (char/tmABCD, CmfbB), CtfbD010 -> (..., CtfbD).
    Names without a terminal numeric component deliberately have no series key.
    """
    rel = pathlib.PurePosixPath(_norm(asset.primary_path))
    m = re.match(r"^(.*?)(\d+)$", rel.stem)
    if not m or not m.group(1):
        return None
    return rel.parent.as_posix().casefold(), m.group(1).casefold()


def _resolved_skeleton_evidence(asset) -> set[str]:
    """Collect already-proven skeleton identities from one sibling asset."""
    out: set[str] = set()
    bound = _norm(getattr(asset, "binding_skeleton_smb", ""))
    if bound:
        out.add(bound.casefold())
    for ctx in authorable_lod_model_info_contexts(asset, require_motion_smb=True):
        smb = _norm(ctx.get("motion_smb"))
        if smb:
            out.add(smb.casefold())
    return out


def series_sibling_consensus_candidate(registry, asset, *, min_resolved_siblings: int = 3) -> dict[str, Any]:
    """Infer a skeleton hypothesis only from unanimous already-resolved siblings.

    This is planning evidence, never binding evidence.  The caller must still
    execute the physical SMD-vs-SMB structural gate before using the context.
    """
    key = _series_family_key(asset)
    if key is None:
        return {
            "candidate_available": False, "candidate_smb": "",
            "candidate_basis": "NO_NUMBERED_SERIES", "binding_proven": False,
            "requires_structural_gate": False, "series_resolved_sibling_count": 0,
        }
    parent, prefix = key
    evidence: list[dict[str, Any]] = []
    for sibling in registry.assets:
        if sibling is asset or str(getattr(sibling, "family", "")) != "SMD_MODEL_062_RIGID_PHYSIQUE":
            continue
        skey = _series_family_key(sibling)
        if skey != key:
            continue
        skeletons = _resolved_skeleton_evidence(sibling)
        if len(skeletons) != 1:
            continue
        evidence.append({
            "asset": sibling.primary_path,
            "skeleton_smb": next(iter(skeletons)),
        })
    evidence.sort(key=lambda r: str(r["asset"]).casefold())
    unique = sorted({str(r["skeleton_smb"]) for r in evidence})
    if len(evidence) < int(min_resolved_siblings):
        basis = "SERIES_CONSENSUS_INSUFFICIENT"
        chosen = ""
    elif len(unique) != 1:
        basis = "SERIES_CONSENSUS_CONFLICT"
        chosen = ""
    else:
        basis = "SERIES_SIBLING_CONSENSUS"
        chosen = unique[0]
    return {
        "format": PROBE_FORMAT,
        "asset": asset.primary_path,
        "domain": content_domain(asset),
        "candidate_smb": chosen,
        "candidate_basis": basis,
        "candidate_available": bool(chosen),
        "binding_proven": False,
        "requires_structural_gate": bool(chosen),
        "series_parent": parent,
        "series_prefix": prefix,
        "series_resolved_sibling_count": len(evidence),
        "series_unique_skeleton_count": len(unique),
        "series_skeletons": unique,
        "series_evidence_sample": evidence[:50],
        "client_modified": False,
    }


def explicit_skeleton_candidate(registry, asset) -> dict[str, Any]:
    """Return the safest explicit skeleton hypothesis for a non-LOD rigid asset."""
    if not standalone_rigid_context_eligible(asset):
        return {
            "candidate_smb": "", "candidate_basis": "MODEL_INFO_LOD_CONTEXT_AVAILABLE",
            "candidate_available": False, "binding_proven": False,
            "requires_structural_gate": False,
        }
    bound = _norm(getattr(asset, "binding_skeleton_smb", ""))
    if bound:
        return {
            "format": PROBE_FORMAT, "asset": asset.primary_path, "domain": content_domain(asset),
            "sibling_smbs": [], "exact_stem_smbs": [],
            "candidate_smb": bound, "candidate_basis": "RESOLVED_BINDING_SKELETON",
            "candidate_available": True, "binding_proven": True,
            "requires_structural_gate": True, "client_modified": False,
        }
    direct = sibling_smb_candidates(registry, asset)
    if direct.get("candidate_available"):
        return direct
    # PT_RC6_10_SERIES_SIBLING_CONSENSUS
    consensus = series_sibling_consensus_candidate(registry, asset)
    if consensus.get("candidate_available"):
        return consensus
    return direct

def sibling_smb_candidates(registry, asset) -> dict[str, Any]:
    """Return deterministic sibling-SMB hypotheses without claiming a binding.

    These assets have Physique but no INX rows in the canonical pairing. Naming
    and directory adjacency are useful hypotheses only; the physical structural
    gate must still PASS before the SMB can be used by any automated devtest.
    """
    rel = pathlib.PurePosixPath(_norm(asset.primary_path))
    parent = rel.parent.as_posix().casefold()
    stem = rel.stem.casefold()
    siblings: list[str] = []
    for row in registry.records:
        if str(row.get("extension") or "").lower() != ".smb":
            continue
        candidate = _norm(row.get("relative_path"))
        if pathlib.PurePosixPath(candidate).parent.as_posix().casefold() == parent:
            siblings.append(candidate)
    siblings = sorted(set(siblings), key=str.casefold)
    exact = [x for x in siblings if pathlib.PurePosixPath(x).stem.casefold() == stem]
    if len(exact) == 1:
        chosen = exact[0]
        basis = "EXACT_SIBLING_STEM"
    elif len(siblings) == 1:
        chosen = siblings[0]
        basis = "UNIQUE_DIRECTORY_SMB"
    else:
        chosen = ""
        basis = "AMBIGUOUS_OR_MISSING"
    return {
        "format": PROBE_FORMAT,
        "asset": asset.primary_path,
        "domain": content_domain(asset),
        "sibling_smbs": siblings,
        "exact_stem_smbs": exact,
        "candidate_smb": chosen,
        "candidate_basis": basis,
        "candidate_available": bool(chosen),
        "binding_proven": False,
        "requires_structural_gate": bool(chosen),
        "client_modified": False,
    }


def choose_standalone_rigid_representatives(registry, domain: str, *, limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in registry.assets:
        if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE" or content_domain(asset) != domain:
            continue
        # Do not treat an arbitrary INX row as a usable rigid context.  Many
        # equipment/model-info records have configs but no motion_smb.  The
        # standalone path is allowed only when no fully usable model-info
        # context exists; physical skeleton compatibility is still proven by
        # the structural gate before any build.
        if not standalone_rigid_context_eligible(asset):
            continue
        probe = explicit_skeleton_candidate(registry, asset)
        if not probe["candidate_available"]:
            continue
        rows.append({
            "asset_id": asset.asset_id,
            "asset": asset.primary_path,
            "domain": domain,
            "skeleton_smb": probe["candidate_smb"],
            "candidate_basis": probe["candidate_basis"],
            "sibling_smb_count": len(probe["sibling_smbs"]),
            "object_count": int(asset.object_count or 0),
            "total_vertices": int(asset.total_vertices or 0),
            "total_faces": int(asset.total_faces or 0),
        })
    # Exact sibling names are stronger hypotheses. Within each class cover both
    # small and complex assets so the external automatic gate is representative.
    rank = {"RESOLVED_BINDING_SKELETON": 0, "EXACT_SIBLING_STEM": 1, "UNIQUE_DIRECTORY_SMB": 2}
    rows.sort(key=lambda r: (rank.get(r["candidate_basis"], 9), -r["object_count"], -r["total_faces"], r["asset"].casefold()))
    if len(rows) <= int(limit):
        return rows
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for basis in ("RESOLVED_BINDING_SKELETON", "EXACT_SIBLING_STEM", "UNIQUE_DIRECTORY_SMB"):
        hit = next((r for r in rows if r["candidate_basis"] == basis and r["asset_id"] not in seen), None)
        if hit:
            out.append(hit); seen.add(hit["asset_id"])
            if len(out) >= int(limit):
                return out
    for row in rows:
        if row["asset_id"] in seen:
            continue
        out.append(row); seen.add(row["asset_id"])
        if len(out) >= int(limit):
            break
    return out


def choose_standalone_rigid_authorable_representatives(registry, resolver, domain: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Backfill standalone-rigid witnesses until their source has editable objects.

    Skeleton candidacy alone does not imply that the mesh contains an object the
    current guarded writer can edit.  The source-only authoring plan is therefore
    used as a preflight; structural skeleton compatibility is still re-proven by
    the real devtest before any candidate is built.
    """
    # Ask for the whole ordered pool, then retain only physically authorable rows.
    pool=choose_standalone_rigid_representatives(registry,domain,limit=10**9)
    out=[]
    for row in pool:
        try:
            asset=registry.resolve(row['asset'])
            source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
            plan=authoring_plan(asset,source)
            objects=list(((plan.get('channels') or {}).get('geometry') or {}).get('eligible_objects') or [])
            if not objects:
                objects=list((plan.get('source_analysis') or {}).get('rigid_saved_blender_candidate_objects') or [])
            lod_config=choose_authorable_lod_config_for_explicit_skeleton(asset)
            if lod_config is not None:
                eligible={str(x).casefold() for x in objects}
                selected=[]
                for lod in ('high','default','low'):
                    for name in (lod_config.get('lods') or {}).get(lod,[]):
                        if str(name).casefold() in eligible and str(name) not in selected:
                            selected.append(str(name))
                objects=selected
            if not objects:
                continue
            picked=dict(row); picked['physical_authoring_preflight']='PASS'; picked['eligible_objects']=objects
            out.append(picked)
            if len(out) >= int(limit): break
        except Exception:
            continue
    return out


def choose_authorable_lod_config_for_explicit_skeleton(asset) -> dict[str, Any] | None:
    """Choose one explicit INX config whose declared LOD tiers are exact SMD matches.

    This is deterministic test planning only. It never selects a skeleton; the
    caller must already have a structurally-proven explicit SMB.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in authorable_lod_model_info_contexts(asset, require_motion_smb=False):
        inx = _norm(row.get("inx"))
        g = grouped.setdefault(inx, {"inx": inx, "cfg": row["cfg"], "lods": {}, "selection_modes": {}, "node_count": 0})
        g["lods"][row["lod"]] = list(row.get("nodes") or [])
        g["selection_modes"][row["lod"]] = str((row.get("coverage") or {}).get("selection_mode") or "MODEL_GROUP_KEYS")
        g["node_count"] += len(row.get("nodes") or [])
    if not grouped:
        return None
    rows = list(grouped.values())
    rows.sort(key=lambda x: (-len(x["lods"]), -int(x["node_count"]), str(x["inx"]).casefold()))
    return rows[0]


def _work_root(project_root: pathlib.Path, domain: str, asset_path: str) -> pathlib.Path:
    return pathlib.Path(project_root).resolve() / "pt_build" / "devtest" / "standalone_rigid_auto" / domain.lower() / asset_workspace_name(asset_path)


def run_standalone_rigid_automated_devtest(
    settings, asset_registry, resolver, certifications, *,
    asset_path: str, skeleton_smb: str, domain: str, amplitude: float = 0.12,
) -> dict[str, Any]:
    asset = asset_registry.resolve(asset_path)
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"standalone rigid devtest requires rigid Model0.62, got {asset.family}")
    if not standalone_rigid_context_eligible(asset):
        raise RuntimeError("standalone rigid devtest is only for rigid assets without a usable model-info skeleton context")
    probe = explicit_skeleton_candidate(asset_registry, asset)
    wanted = _norm(skeleton_smb).casefold()
    if not probe.get("candidate_smb") or _norm(probe["candidate_smb"]).casefold() != wanted:
        raise RuntimeError(f"requested explicit SMB is not the proven/deterministic skeleton candidate: {skeleton_smb}")

    root = pathlib.Path(settings.project_root).resolve()
    work = _work_root(root, domain, asset.primary_path)
    if work.exists():
        shutil.rmtree(work)
    structural_work, import_work, edit_work, build_work, reimport_work = [work / x for x in ("00_structural", "01_import", "02_edit", "03_candidate", "04_reimport")]
    for p in (structural_work, import_work, edit_work, build_work, reimport_work):
        p.mkdir(parents=True, exist_ok=True)

    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    skeleton = pathlib.Path(resolver.resolve(skeleton_smb, required=True)).resolve()
    source_sha = sha256_file(source)
    skeleton_sha = sha256_file(skeleton)

    # The filename/directory relation is only a hypothesis. Structural PASS is
    # the authorization boundary for using this SMB in this devtest.
    structural_report = structural_work / "structural.json"
    run_logged([
        "python3", str(root / "pt_character_structural_gate_v2.py"),
        "--smd", str(source), "--smb", str(skeleton), "--report", str(structural_report),
    ], structural_work / "structural.log")
    structural = json.loads(structural_report.read_text(encoding="utf-8"))
    if str(structural.get("result") or structural.get("check") or structural.get("status")) not in {"PASS"}:
        raise RuntimeError(f"standalone sibling SMB structural gate did not PASS: {structural}")

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    overlay, texture_report = runner._texture_overlay(asset, import_work)
    pristine = import_work / "pristine_import.blend"
    importer = root / "history_py" / "pt_smd_blender_import_v3_static_armature.py"
    lod_config = choose_authorable_lod_config_for_explicit_skeleton(asset)
    import_cmd = settings.blender_command() + [
        "--background", "--python-exit-code", "1", "--python", str(importer), "--",
        "--smd", str(source), "--skeleton", str(skeleton),
    ]
    model_info_path = None
    if lod_config is not None:
        model_info_path = pathlib.Path(resolver.resolve(lod_config["inx"], required=True)).resolve()
        first_lod = next((x for x in ("default", "high", "low") if x in lod_config["lods"]), None)
        if first_lod is None:
            raise RuntimeError("explicit-skeleton LOD devtest selected config without an exact LOD")
        import_cmd += ["--model-info", str(model_info_path), "--lod", first_lod]
        if (lod_config.get("selection_modes") or {}).get(first_lod) == "SINGLE_TIER_FULL_CONTAINER":
            import_cmd.append("--single-tier-full-container")
    import_cmd += ["--client-root", str(overlay), "--out", str(pristine), "--no-pack"]
    run_logged(import_cmd, import_work / "01_import.log")

    base_plan = authoring_plan(asset, source)
    objects = list(((base_plan.get("channels") or {}).get("geometry") or {}).get("eligible_objects") or [])
    if not objects:
        objects = list((base_plan.get("source_analysis") or {}).get("rigid_saved_blender_candidate_objects") or [])
    if lod_config is not None:
        selected = []
        seen = set()
        eligible_keys = {str(x).casefold(): str(x) for x in objects}
        for lod in ("high", "default", "low"):
            for name in lod_config["lods"].get(lod, []):
                key = str(name).casefold()
                if key in eligible_keys and key not in seen:
                    selected.append(eligible_keys[key]); seen.add(key)
        objects = selected
    if not objects:
        raise RuntimeError("standalone rigid devtest has no eligible rigid candidate objects")

    edit_plan = {
        "format": "PT_STANDALONE_RIGID_AUTOMATED_EDIT_PLAN_V1",
        "asset": asset.primary_path,
        "domain": domain,
        "objects": objects,
        "amplitude": float(amplitude),
        "source_sha256": source_sha,
        "standalone_binding": {
            "skeleton_smb": _norm(skeleton_smb),
            "skeleton_sha256": skeleton_sha,
            "candidate_basis": probe.get("candidate_basis"),
            "structural_gate": "PASS",
            "model_info_inx": lod_config.get("inx") if lod_config else None,
            "exact_lods": sorted((lod_config.get("lods") or {}).keys()) if lod_config else [],
        },
    }
    edit_plan_path = edit_work / "edit_plan.json"
    edit_plan_path.write_text(json.dumps(edit_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    edited_blend = edit_work / "automatically_edited.blend"
    edit_report_path = edit_work / "edit_report.json"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "apply_rigid_profile_devtest.py"), "--",
        "--plan", str(edit_plan_path), "--out", str(edited_blend), "--report", str(edit_report_path),
    ], edit_work / "01_automatic_edit.log")
    edit_report = json.loads(edit_report_path.read_text(encoding="utf-8"))
    if edit_report.get("status") != "PASS" or int(edit_report.get("target_count") or 0) != len(objects):
        raise RuntimeError(f"standalone rigid automatic edit failed: {edit_report}")

    output = build_work / pathlib.PurePosixPath(asset.primary_path).name
    steps_dir = build_work / "steps"; steps_dir.mkdir(parents=True, exist_ok=True)
    current_source = source
    steps: list[dict[str, Any]] = []
    for idx, object_name in enumerate(objects, start=1):
        step_output = output if idx == len(objects) else steps_dir / f"{idx:02d}_{object_name}.smd"
        step_report = steps_dir / f"{idx:02d}_{object_name}.writer.json"
        candidate = {
            "status": "READY", "blend": str(edited_blend), "source": str(current_source),
            "source_sha256": sha256_file(current_source), "skeleton": str(skeleton),
            "object": object_name, "output": str(step_output),
        }
        run_logged(build_rigid_candidate_blender_command(settings, candidate, report=step_report), steps_dir / f"{idx:02d}_{object_name}.log")
        data = json.loads(step_report.read_text(encoding="utf-8"))
        steps.append({
            "index": idx, "object": object_name, "input_sha256": sha256_file(current_source),
            "output_sha256": sha256_file(step_output), "source_counts": data.get("source_counts"),
            "output_counts": data.get("output_counts"), "max_vertex_fit_error": data.get("max_vertex_fit_error"),
        })
        current_source = step_output.resolve()

    if lod_config is not None:
        context_lod = next((x for x in ("default", "high", "low") if x in lod_config["lods"]), None)
        selected_context = build_selected_authoring_context(
            model_info_logical=lod_config["inx"], model_info_path=model_info_path,
            skeleton_logical=_norm(skeleton_smb), skeleton_path=skeleton,
            lod=context_lod, lod_groups=lod_config["cfg"].get("lod_groups") or {},
            selected_lod_nodes=list((lod_config.get("lods") or {}).get(context_lod) or []),
            lod_selection_mode=str((lod_config.get("selection_modes") or {}).get(context_lod) or "MODEL_GROUP_KEYS"),
            selection_basis={
                "kind": "AUTOMATED_EXPLICIT_SKELETON_LOD",
                "roundtrip_target": asset.primary_path,
                "structural_gate": "PASS",
                "candidate_basis": probe.get("candidate_basis"),
            },
        )
    else:
        selected_context = build_standalone_rigid_authoring_context(
            asset_logical=asset.primary_path, source_path=source,
            skeleton_logical=_norm(skeleton_smb), skeleton_path=skeleton,
            selected_nodes=objects, structural_gate_report=structural_report,
            selection_basis={
                "kind": "AUTOMATED_STRUCTURAL_SKELETON",
                "roundtrip_target": asset.primary_path,
                "structural_gate": "PASS",
                "candidate_basis": probe.get("candidate_basis"),
            },
        )

    verification = validate_rigid_profile_stress_output(root, source, output, skeleton, objects)
    if verification.get("status") != "PASS":
        raise RuntimeError(f"standalone rigid combined candidate failed: {verification.get('errors')}")
    writer_summary = build_work / "writer_summary.json"
    writer_summary.write_text(json.dumps({
        "tool": "PT_STANDALONE_RIGID_AUTOMATED_DEVTEST_WRITER_V1",
        "step_count": len(steps), "steps": steps, "output_sha256": sha256_file(output),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = write_build_provenance(
        output, asset=asset, source=source, build_mode="CANDIDATE_RIGID_STANDALONE_AUTOMATED_DEVTEST",
        adapter="pt_blender_to_smd_free_mesh_v3.py", build_status="PASS", production_authorized=False,
        evidence={
            "automated_devtest": True, "semantic_domain": domain, "candidate_objects": objects,
            "standalone_binding": {"skeleton_smb": _norm(skeleton_smb), "skeleton_sha256": skeleton_sha, "candidate_basis": probe.get("candidate_basis"), "structural_gate": "PASS"},
            "all_target_edits_observed": bool(verification.get("all_target_edits_observed")),
            "non_target_changed": list(verification.get("non_target_changed") or []),
            "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}),
            "verification_errors": list(verification.get("errors") or []), "writer_summary": str(writer_summary),
        },
        selected_context=selected_context,
    )

    # Reimport the generated candidate.  When an exact INX LOD config exists,
    # exercise every exact tier from that config using the explicit skeleton.
    parsed = parse_model062_bytes(output.read_bytes())
    reimport_results: dict[str, Any] = {}
    check_script = root / "pt_asset_tool" / "blender" / "check_rigid_profile_devtest.py"
    if lod_config is not None:
        for lod in ("high", "default", "low"):
            expected_names = list(lod_config["lods"].get(lod) or [])
            if not expected_names:
                continue
            expected = {}
            for name in expected_names:
                obj = parsed["objects"].get(name)
                if obj is None:
                    raise RuntimeError(f"explicit-skeleton candidate missing {lod} object: {name}")
                expected[name] = {"vertices": int(obj["nv"]), "faces": int(obj["nf"])}
            expected_path = reimport_work / f"expected_{lod}.json"
            expected_path.write_text(json.dumps({"format":"PT_STANDALONE_RIGID_REIMPORT_EXPECTED_V2","lod":lod,"objects":expected}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            blend = reimport_work / f"candidate_{lod}.blend"
            reimport_cmd = settings.blender_command() + [
                "--background", "--python-exit-code", "1", "--python", str(importer), "--",
                "--smd", str(output), "--skeleton", str(skeleton), "--model-info", str(model_info_path),
                "--lod", lod, "--client-root", str(overlay), "--out", str(blend), "--no-pack",
            ]
            if (lod_config.get("selection_modes") or {}).get(lod) == "SINGLE_TIER_FULL_CONTAINER":
                reimport_cmd.append("--single-tier-full-container")
            run_logged(reimport_cmd, reimport_work / f"01_import_{lod}.log")
            check_report = reimport_work / f"check_{lod}.json"
            run_logged(settings.blender_command() + [
                "--background", str(blend), "--python-exit-code", "1", "--python", str(check_script), "--",
                "--expected", str(expected_path), "--report", str(check_report),
            ], reimport_work / f"02_check_{lod}.log")
            checked = json.loads(check_report.read_text(encoding="utf-8"))
            if checked.get("status") != "PASS":
                raise RuntimeError(f"explicit-skeleton {lod} candidate reimport failed: {checked.get('errors')}")
            reimport_results[lod] = {"status":"PASS","expected_objects":expected_names,"checked_object_count":checked.get("checked_object_count"),"blend":str(blend),"check_report":str(check_report)}
    else:
        expected = {name: {"vertices": int(parsed["objects"][name]["nv"]), "faces": int(parsed["objects"][name]["nf"])} for name in objects}
        expected_path = reimport_work / "expected.json"
        expected_path.write_text(json.dumps({"format": "PT_STANDALONE_RIGID_REIMPORT_EXPECTED_V1", "objects": expected}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        reimport_blend = reimport_work / "candidate_reimport.blend"
        run_logged(settings.blender_command() + [
            "--background", "--python-exit-code", "1", "--python", str(importer), "--",
            "--smd", str(output), "--skeleton", str(skeleton), "--client-root", str(overlay),
            "--out", str(reimport_blend), "--no-pack",
        ], reimport_work / "01_import.log")
        check_report = reimport_work / "check.json"
        run_logged(settings.blender_command() + [
            "--background", str(reimport_blend), "--python-exit-code", "1", "--python", str(check_script), "--",
            "--expected", str(expected_path), "--report", str(check_report),
        ], reimport_work / "02_check.log")
        checked = json.loads(check_report.read_text(encoding="utf-8"))
        if checked.get("status") != "PASS":
            raise RuntimeError(f"standalone rigid candidate reimport failed: {checked.get('errors')}")
        reimport_results["standalone"] = {"status":"PASS","checked_object_count":checked.get("checked_object_count"),"blend":str(reimport_blend),"check_report":str(check_report)}

    result = {
        "format": FORMAT, "status": "PASS", "domain": domain, "asset": asset.primary_path,
        "source_sha256": source_sha, "skeleton_smb": _norm(skeleton_smb), "skeleton_sha256": skeleton_sha,
        "binding_probe": {"candidate_basis": probe.get("candidate_basis"), "structural_gate": "PASS", "binding_proven_for_devtest": True},
        "selected_context": selected_context,
        "texture_ready": bool(texture_report.get("ready", True)),
        "automatic_edit": {"status": edit_report.get("status"), "target_count": edit_report.get("target_count"), "objects": objects, "report": str(edit_report_path)},
        "candidate": {"status": verification.get("status"), "artifact": str(output), "artifact_sha256": sha256_file(output), "provenance": str(provenance), "writer_step_count": len(steps), "all_target_edits_observed": bool(verification.get("all_target_edits_observed")), "non_target_changed": list(verification.get("non_target_changed") or []), "unknown_physique_bones_by_object": dict(verification.get("unknown_physique_bones_by_object") or {}), "errors": list(verification.get("errors") or []), "writer_summary": str(writer_summary)},
        "reimport": reimport_results,
        "explicit_skeleton_lod": {
            "used": lod_config is not None,
            "model_info_inx": lod_config.get("inx") if lod_config else None,
            "tested_lods": sorted(reimport_results.keys()),
        },
        "automatic_devtest_pass": True, "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False, "workdir": str(work),
    }
    report = work / "result.json"; result["report"] = str(report)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_standalone_rigid_automated_devtest_batch(settings, asset_registry, resolver, certifications, rows: list[dict[str, Any]], *, amplitude: float = 0.12) -> dict[str, Any]:
    passed: list[str] = []; failed: list[dict[str, Any]] = []; results: list[dict[str, Any]] = []
    for row in rows:
        try:
            res = run_standalone_rigid_automated_devtest(
                settings, asset_registry, resolver, certifications,
                asset_path=row["asset"], skeleton_smb=row["skeleton_smb"], domain=row["domain"], amplitude=amplitude,
            )
            results.append(res); passed.append(row["asset"])
        except Exception as exc:
            failed.append({"asset": row.get("asset"), "skeleton_smb": row.get("skeleton_smb"), "domain": row.get("domain"), "error": f"{type(exc).__name__}: {exc}"})
    status = "PASS" if rows and len(results) == len(rows) and not failed else ("EMPTY" if not rows else "FAIL")
    result = {"format": BATCH_FORMAT, "status": status, "requested": len(rows), "passed_assets": passed, "failed_assets": failed, "results": results, "automatic_only": True, "runtime_authorized": False, "production_authorized": False, "client_write_authorized": False, "client_modified": False}
    out = pathlib.Path(settings.project_root).resolve() / "pt_build" / "devtest" / "standalone_rigid_auto" / "batch_result.json"
    out.parent.mkdir(parents=True, exist_ok=True); result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
