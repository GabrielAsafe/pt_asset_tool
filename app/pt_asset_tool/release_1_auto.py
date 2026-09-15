from __future__ import annotations

import json
import pathlib
from typing import Any

from .animation_pose_devtest import run_animation_pose_automated_devtest_batch, choose_animation_pose_representatives, choose_animation_pose_physical_representatives, filter_animation_pose_physical_representatives
from .object_local_devtest import choose_object_local_representatives, run_object_local_automated_devtest_batch
from .model062_corpus import audit_model062_physical_corpus
from .model062_material_devtest import choose_all_model062_material_representatives, run_model062_material_automated_devtest_batch, audit_model062_material_physical_corpus
from .model062_texture_audit import audit_model062_texture_presence
from .mixed_synthetic_devtest import run_mixed_physique_synthetic_devtest
from .mixed_real_devtest import choose_mixed_physique_representatives, run_mixed_physique_physical_automated_devtest_batch
from .release_scope import MIXED_PHYSIQUE_RELEASE_1_SCOPE, MIXED_PHYSIQUE_RELEASE_1_BLOCKING
from .object_local_corpus import audit_object_local_physical_corpus
from .object_local_writer import audit_object_local_writer_corpus
from .rare_outliers import audit_rare_outliers_and_tga
from .rare_support import audit_rare_support
from .release_1_coverage import (
    CONTENT_DOMAINS, build_release_1_automated_gate_plan, build_release_1_coverage,
    content_domain, content_domain_from_values,
)
from .rigid_semantic_devtest import run_rigid_semantic_automated_devtest_batch
from .rigid_context_census import audit_rigid_context_census
from .rigid_model_info import audit_rigid_lod_context_corpus
from .stage072_semantic_devtest import run_stage072_automated_devtest_batch
from .stage072_corpus import audit_stage072_physical_corpus
from .stage072_area import audit_stage072_stagearea_rebuild
from .stage072_normals import audit_stage072_normals
from .stage072_texture_audit import audit_stage072_texture_presence
from .stage072_material_devtest import run_stage072_material_automated_devtest_batch, audit_stage072_material_physical_corpus
from .standalone_rigid_devtest import choose_standalone_rigid_representatives, choose_standalone_rigid_authorable_representatives, run_standalone_rigid_automated_devtest_batch
from .standalone_animation_devtest import (
    audit_smb_animation_corpus, choose_standalone_animation_representatives,
    run_standalone_animation_pose_devtest_batch,
)
from .player_scale_witness import run_player_scale_witness
from .static_semantic_devtest import run_static_semantic_automated_devtest_batch, audit_model062_static_physical_corpus, choose_static_semantic_representatives
from .texlink_corpus import audit_multilayer_texlink_corpus
from .texlink_devtest import choose_multilayer_representatives, run_multilayer_texlink_automated_devtest_batch
from .texture_codec_devtest import audit_proprietary_texture_codecs, audit_proprietary_texture_physical_corpus
from .writer_corpus_audit import (
    audit_inx_writer_corpus, audit_smb_writer_corpus,
    audit_inx_writer_edit_corpus, audit_smb_writer_edit_corpus,
    audit_motion_writer_semantic_edit_corpus,
)

FORMAT = "PT_ASSET_RELEASE_1_AUTOMATED_GATE_V1"


def _progress(message: str) -> None:
    print(f"[release-1-auto] {message}", flush=True)


def _load_resumable_batch(root: pathlib.Path, relative: str, rows: list[dict[str, Any]], *, label: str) -> dict[str, Any] | None:
    """Reuse a just-produced PASS batch only when its selected asset set matches exactly.

    This is intentionally limited to pt_build evidence from the same working tree.
    Corpus/read-only gates are always rerun against the mounted client.
    """
    path = (root / relative).resolve()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    expected = {str(r.get("asset") or "").replace("\\", "/").casefold() for r in rows if r.get("asset")}
    passed = {str(x or "").replace("\\", "/").casefold() for x in (data.get("passed_assets") or [])}
    if (
        str(data.get("status") or "") != "PASS"
        or int(data.get("requested") or -1) != len(rows)
        or passed != expected
        or bool(data.get("failed_assets"))
        or bool(data.get("client_modified"))
        or bool(data.get("client_write_authorized"))
        or bool(data.get("production_authorized"))
    ):
        return None
    data = dict(data)
    data["resumed_from_existing_pt_build"] = True
    data["resume_report"] = str(path)
    _progress(f"RESUME {label} PASS ({len(rows)} assets) <- {path}")
    return data


def _run_logged(label: str, fn):
    _progress(f"START {label}")
    result = fn()
    status = result.get("status") if isinstance(result, dict) else None
    _progress(f"DONE  {label} status={status or 'UNKNOWN'}")
    return result


def _resume_or_run_batch(root: pathlib.Path, resume: bool, relative: str, label: str, rows: list[dict[str, Any]], fn):
    if resume and rows:
        cached = _load_resumable_batch(root, relative, rows, label=label)
        if cached is not None:
            return cached
    return _run_logged(label, fn)


def _flatten(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out=[]
    for domain in sorted(groups):
        for row in groups[domain]:
            x=dict(row); x.setdefault("domain", domain); out.append(x)
    return out


def _status_pass(row: dict[str, Any] | None, *, allow_empty: bool = False) -> bool:
    if not isinstance(row, dict): return False
    status=str(row.get("status") or "")
    return status == "PASS" or (allow_empty and status == "EMPTY")


def _compact_batch(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict): return {"status":"MISSING"}
    return {
        "status": row.get("status"), "requested": row.get("requested"),
        "passed_assets": row.get("passed_assets"), "failed_assets": row.get("failed_assets"),
        "report": row.get("report"), "resumed_from_existing_pt_build": bool(row.get("resumed_from_existing_pt_build")),
    }


def _passed_domains(rows: list[dict[str, Any]], batch: dict[str, Any] | None) -> set[str]:
    """Return only domains whose selected representatives actually passed.

    Selection is planning evidence, not execution evidence.  This helper avoids
    a failed batch accidentally painting its selected domains green in the
    Release 1 coverage matrix.
    """
    if not isinstance(batch, dict):
        return set()
    passed = {str(x).replace("\\", "/").casefold() for x in (batch.get("passed_assets") or [])}
    result_pass = {
        str(x.get("asset") or "").replace("\\", "/").casefold()
        for x in (batch.get("results") or [])
        if str(x.get("status") or "") == "PASS"
    }
    passed |= result_pass
    out: set[str] = set()
    by_domain: dict[str, list[str]] = {}
    for row in rows:
        domain = str(row.get("domain") or "")
        asset = str(row.get("asset") or "").replace("\\", "/").casefold()
        if domain and asset:
            by_domain.setdefault(domain, []).append(asset)
    for domain, assets in by_domain.items():
        # A domain is green only when every selected witness in that domain
        # passed. One failing representative keeps that content-domain cell open.
        if assets and all(a in passed for a in assets):
            out.add(domain)
    return out


def _object_local_feature_coverage(physical: dict[str, Any], selected_rows: list[dict[str, Any]], batch: dict[str, Any] | None) -> tuple[set[str], dict[str, dict[str, list[str]]]]:
    """Require every physical object-local subtype in a domain to have a PASS Blender witness.

    Corpus parse proves broad readability.  This function prevents a domain that
    physically contains ROT/POS/SCALE, segmented TmFrame, legacy affine,
    zero-scale spawn or hierarchy semantics from being certified by a simpler
    representative that never exercised that subtype in Blender.
    """
    required={d:set() for d in CONTENT_DOMAINS}
    for row in (physical or {}).get("rows") or []:
        domain=content_domain_from_values(row.get("path") or "", row.get("category") or "")
        if domain not in required or str(row.get("parser_status") or "") != "PASS":
            continue
        required[domain].update(str(x) for x in (row.get("channels_present") or []))
        if int(row.get("segmented_object_count") or 0)>0:
            required[domain].add("SEGMENTED_TMFRAME")
        if int(row.get("legacy_affine_object_count") or 0)>0:
            required[domain].add("LEGACY_AFFINE")
        if int(row.get("zero_scale_spawn_object_count") or 0)>0:
            required[domain].add("ZERO_SCALE_SPAWN")
        if int(row.get("parent_edge_count_full_parse") or row.get("parent_edge_count") or 0)>0:
            required[domain].add("HIERARCHICAL")
        if int(row.get("unresolved_parent_count_full_parse") or row.get("runtime_unresolved_parent_count") or 0)>0:
            required[domain].add("UNRESOLVED_PARENT")
        if int(row.get("animated_child_count") or 0)>0:
            required[domain].add("ANIMATED_CHILD")

    asset_domain={str(r.get("asset") or "").replace("\\","/").casefold():str(r.get("domain") or "") for r in selected_rows}
    witnessed={d:set() for d in CONTENT_DOMAINS}
    for result in (batch or {}).get("results") or []:
        if str(result.get("status") or "PASS") != "PASS":
            continue
        asset=str(result.get("asset") or "").replace("\\","/").casefold()
        domain=asset_domain.get(asset, "")
        if domain not in witnessed:
            continue
        witnessed[domain].update("ROT" if str(x)=="ROT_AFFINE" else str(x) for x in (result.get("candidate_writer_channels_tested") or []))
        bake=result.get("blender_bake") or {}
        if result.get("segmented_tmframe_objects"):
            witnessed[domain].add("SEGMENTED_TMFRAME")
        if int(bake.get("legacy_affine_object_count") or 0)>0:
            witnessed[domain].add("LEGACY_AFFINE")
        if int(bake.get("zero_scale_spawn_object_count") or 0)>0:
            witnessed[domain].add("ZERO_SCALE_SPAWN")
        if int(bake.get("parent_edge_count") or 0)>0:
            witnessed[domain].add("HIERARCHICAL")
        if int(bake.get("unresolved_parent_count") or result.get("unresolved_parent_count") or 0)>0:
            witnessed[domain].add("UNRESOLVED_PARENT")
        if int(result.get("animated_child_count") or 0)>0:
            witnessed[domain].add("ANIMATED_CHILD")

    details={}
    pass_domains=set()
    for domain in CONTENT_DOMAINS:
        req=required[domain]
        wit=witnessed[domain]
        missing=sorted(req-wit)
        details[domain]={"required":sorted(req),"witnessed":sorted(wit),"missing":missing}
        if req and not missing:
            pass_domains.add(domain)
    return pass_domains, details


def _multilayer_profile_coverage(physical: dict[str, Any], selected_rows: list[dict[str, Any]], batch: dict[str, Any] | None) -> tuple[set[str], dict[str, dict[str, list[str]]]]:
    """Require every observed two-stage TexLink profile in a domain to be roundtripped.

    Profiles distinguish rigid/static containers, full-vs-partial multilayer
    face coverage and distinct per-stage UVs.  Chain depth >2/invalid chains are
    handled by the corpus blocker separately.
    """
    required={d:set() for d in CONTENT_DOMAINS}
    for row in (physical or {}).get("rows") or []:
        domain=content_domain_from_values(row.get("relative_path") or "", row.get("category") or "")
        if domain not in required:
            continue
        mode=str(row.get("mode") or "").upper()
        if mode in {"STATIC","RIGID"}: required[domain].add("FAMILY_"+mode)
        ml=int(row.get("multilayer_faces") or 0); total=int(row.get("total_faces") or 0)
        if ml>0 and total>0:
            required[domain].add("FULL_FACE_MULTILAYER" if ml==total else "PARTIAL_FACE_MULTILAYER")
        if int(row.get("uv_different_multilayer_faces") or 0)>0:
            required[domain].add("DISTINCT_UV_STAGE")

    passed={str(x).replace("\\","/").casefold() for x in ((batch or {}).get("passed_assets") or [])}
    passed.update(
        str(x.get("asset") or "").replace("\\","/").casefold()
        for x in ((batch or {}).get("results") or []) if str(x.get("status") or "PASS")=="PASS"
    )
    witnessed={d:set() for d in CONTENT_DOMAINS}
    for row in selected_rows:
        asset=str(row.get("asset") or "").replace("\\","/").casefold()
        domain=str(row.get("domain") or "")
        if domain in witnessed and asset in passed:
            witnessed[domain].update(str(x) for x in (row.get("coverage_features") or []))

    details={}; pass_domains=set()
    for domain in CONTENT_DOMAINS:
        req=required[domain]; wit=witnessed[domain]; missing=sorted(req-wit)
        details[domain]={"required":sorted(req),"witnessed":sorted(wit),"missing":missing}
        if req and not missing: pass_domains.add(domain)
    return pass_domains, details


# FIX25_MATERIAL_FAMILY_EVIDENCE
def _model062_material_family_coverage(
    physical: dict[str, Any], selected_rows: list[dict[str, Any]], batch: dict[str, Any] | None,
) -> tuple[set[str], dict[str, dict[str, list[str]]]]:
    """Require an executed material-writer witness for every physical Model0.62 family.

    The material binary structure is shared, but Release 1.0 is a domain x
    physical-family contract.  A rigid witness cannot implicitly certify static
    (or a future authentic Mixed) material authoring in the same content domain.
    """
    # Compatibility for synthetic/unit stubs written before the corpus audit
    # exposed row-level family evidence.  The real V1 corpus audit always emits
    # ``rows``; only that path is used for release evidence.
    if "rows" not in (physical or {}):
        passed = _passed_domains(selected_rows, batch)
        return passed, {
            d: {"required": [], "witnessed": [], "missing": [], "evidence": "LEGACY_STUB"}
            for d in CONTENT_DOMAINS
        }

    required = {d: set() for d in CONTENT_DOMAINS}
    missing_family_metadata = {d: 0 for d in CONTENT_DOMAINS}
    for row in (physical or {}).get("rows") or []:
        domain = str(row.get("domain") or "")
        family = str(row.get("family") or "")
        if domain in required:
            if family:
                required[domain].add(family)
            else:
                missing_family_metadata[domain] += 1

    passed_assets = {str(x).replace("\\", "/").casefold() for x in ((batch or {}).get("passed_assets") or [])}
    passed_assets.update(
        str(x.get("asset") or "").replace("\\", "/").casefold()
        for x in ((batch or {}).get("results") or [])
        if str(x.get("status") or "") == "PASS"
    )
    witnessed = {d: set() for d in CONTENT_DOMAINS}
    for row in selected_rows:
        domain = str(row.get("domain") or "")
        family = str(row.get("family") or "")
        asset = str(row.get("asset") or "").replace("\\", "/").casefold()
        if domain in witnessed and family and asset in passed_assets:
            witnessed[domain].add(family)

    details: dict[str, dict[str, list[str]]] = {}
    pass_domains: set[str] = set()
    for domain in CONTENT_DOMAINS:
        req = required[domain]
        wit = witnessed[domain]
        missing = sorted(req - wit)
        schema_missing = int(missing_family_metadata.get(domain) or 0)
        if schema_missing:
            missing.append("CORPUS_ROW_FAMILY_METADATA_MISSING")
        details[domain] = {
            "required": sorted(req), "witnessed": sorted(wit), "missing": missing,
            "corpus_rows_missing_family": schema_missing,
        }
        if req and not missing:
            pass_domains.add(domain)
    return pass_domains, details


def _stage072_full_corpus_proven(row: dict[str, Any] | None) -> bool:
    """Release 1.0 Stage evidence is the known canonical 63-file corpus, not a subset."""
    if not _status_pass(row):
        return False
    data = row or {}
    if data.get("stage072_physical_complete_candidate") is True:
        return True
    # Backward-compatible evidence shape used by earlier R14 reports/tests.
    full = int(data.get("full_parse_pass_files") or 0)
    expected = data.get("candidate_files_expected")
    audited = data.get("physical_files_audited")
    structural_fail = int(data.get("structural_fail_files") or 0)
    return bool(
        full == 63
        and structural_fail == 0
        and (expected is None or int(expected) == 63)
        and (audited is None or int(audited) == 63)
    )


def _stage072_aux_corpus_proven(row: dict[str, Any] | None, pass_count_key: str) -> bool:
    """Require an auxiliary Stage corpus audit to cover all 63 canonical files."""
    if not _status_pass(row):
        return False
    data = row or {}
    return bool(
        int(data.get("candidate_files_expected") or 0) == 63
        and int(data.get("physical_files_audited") or 0) == 63
        and int(data.get(pass_count_key) or 0) == 63
    )


def _stage072_material_corpus_proven(row: dict[str, Any] | None) -> bool:
    if not _status_pass(row):
        return False
    data = row or {}
    return bool(
        int(data.get("asset_count") or 0) == 63
        and int(data.get("failure_count") or 0) == 0
        and "MAP" in set(data.get("pass_domains") or [])
    )


def _motion_semantic_domain_passes(registry, report: dict[str, Any] | None) -> tuple[set[str], set[str], dict[str, Any]]:
    """Return domains requiring semantic motion evidence and those that passed it."""
    data = report or {}
    by_domain = data.get("by_domain")
    if isinstance(by_domain, dict):
        required = {
            d for d, row in by_domain.items()
            if d in CONTENT_DOMAINS and (
                int((row or {}).get("context_count") or 0) > 0
                or int((row or {}).get("unresolved_asset_count") or 0) > 0
            )
        }
        passed = {
            d for d in required
            if str((by_domain.get(d) or {}).get("status") or "") == "PASS"
        }
        return required, passed, by_domain

    # Older test doubles did not expose per-domain semantic evidence.  Real
    # audit output does; avoid breaking historical focused tests while keeping
    # production evidence strict.
    if "rows" not in data:
        return set(), set(CONTENT_DOMAINS) if _status_pass(data) else set(), {}

    asset_domains = {
        str(a.primary_path or "").replace("\\", "/").casefold(): content_domain(a)
        for a in registry.assets
    }
    touched = {d: [] for d in CONTENT_DOMAINS}
    for row in data.get("rows") or []:
        domains = set(str(x) for x in (row.get("domains") or []) if str(x) in CONTENT_DOMAINS)
        if not domains:
            for asset in row.get("assets") or []:
                domain = asset_domains.get(str(asset).replace("\\", "/").casefold(), "")
                if domain in CONTENT_DOMAINS:
                    domains.add(domain)
        for domain in domains:
            touched[domain].append(row)
    required = {d for d, rows in touched.items() if rows}
    passed = set()
    details: dict[str, Any] = {}
    for domain, rows in touched.items():
        if not rows:
            continue
        failed = [r for r in rows if str(r.get("source_integrity") or "PASS") != "PASS" or any(
            str((r.get(k) or {}).get("status") or "") == "FAIL" for k in ("inx_edit", "smb_edit")
        )]
        details[domain] = {"context_count": len(rows), "failed_context_count": len(failed), "status": "PASS" if not failed else "FAIL"}
        if not failed:
            passed.add(domain)
    return required, passed, details


def _physical_files_by_domain(registry, suffix: str) -> dict[str, list[str]]:
    """Return exact physical logical files attributed to each Release 1 domain."""
    wanted = str(suffix).casefold()
    out = {d: [] for d in CONTENT_DOMAINS}
    seen = {d: set() for d in CONTENT_DOMAINS}
    for record in registry.records:
        if str(record.get("extension") or "").casefold() != wanted:
            continue
        logical = str(record.get("relative_path") or "").replace("\\", "/")
        domain = content_domain_from_values(logical, str(record.get("category_hint") or ""))
        if domain not in out:
            continue
        key = logical.casefold()
        if key not in seen[domain]:
            out[domain].append(logical)
            seen[domain].add(key)
    for domain in out:
        out[domain].sort(key=str.casefold)
    return out


def _domain_audit_summary(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    present = [d for d, row in rows.items() if str(row.get("status") or "") != "EMPTY"]
    failed = [d for d in present if str(rows[d].get("status") or "") != "PASS"]
    return {
        "status": "PASS" if present and not failed else ("EMPTY" if not present else "FAIL"),
        "present_domains": present,
        "pass_domains": [d for d in present if d not in failed],
        "failed_domains": failed,
        "by_domain": rows,
    }


def run_release_1_automated_gate(
    settings, registry, resolver, certifications, *,
    rigid_per_domain: int = 3, static_per_domain: int = 3,
    object_local_limit: int = 4, texlink_limit: int = 4,
    animation_fps: int = 30, motion_pair_limit: int = 0, resume: bool = False,
    motion_semantic_timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    root=pathlib.Path(settings.project_root).resolve()
    plan=build_release_1_automated_gate_plan(
        registry, rigid_per_domain=int(rigid_per_domain), static_per_domain=int(static_per_domain),
    )
    rigid_rows=_flatten(plan.get("rigid_representatives") or {})
    # Release execution uses physical source-aware selection for static authoring
    # and motion-context-aware selection for animation.  The offline registry plan
    # remains useful for inventory diagnostics but must not spend witnesses on an
    # uneditable static container or on an INX that does not own the motion SMB.
    static_groups={
        d: choose_static_semantic_representatives(registry,resolver,d,limit=int(static_per_domain))
        for d in CONTENT_DOMAINS
    }
    animation_groups={}
    for d in ("PLAYER","NPC","MONSTER"):
        broad_animation = choose_animation_pose_representatives(
            registry, d, limit=max(50, int(rigid_per_domain) * 20)
        )
        animation_groups[d] = filter_animation_pose_physical_representatives(
            broad_animation, resolver, limit=2
        )
    plan["static_representatives"] = static_groups
    plan["animation_representatives"] = animation_groups
    static_rows=_flatten(static_groups)
    animation_rows=_flatten(animation_groups)
    stage_rows=list(plan.get("stage072_representatives") or [])
    material_groups = choose_all_model062_material_representatives(registry, per_domain=2)
    material_rows = _flatten(material_groups)
    plan["model062_material_representatives"] = material_groups
    # Some EFFECT/MAP rigid Model0.62 assets have no INX pairing but do have a
    # deterministic sibling SMB. They use a separate structural-gate-first
    # automated path rather than being silently omitted from Release 1.0.
    standalone_groups = {
        d: choose_standalone_rigid_authorable_representatives(
            registry, resolver, d, limit=int(rigid_per_domain)
        )
        for d in ("PLAYER", "NPC", "MONSTER", "EFFECT", "MAP")
    }
    standalone_rigid_rows = _flatten(standalone_groups)
    plan["standalone_rigid_representatives"] = standalone_groups
    standalone_animation_groups = choose_standalone_animation_representatives(
        registry, resolver, per_domain=2,
    )
    standalone_animation_rows = _flatten(standalone_animation_groups)
    plan["standalone_animation_representatives"] = standalone_animation_groups
    mixed_rows = choose_mixed_physique_representatives(registry)
    plan["mixed_physique_physical_assets"] = mixed_rows

    gates: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []
    _progress(f"BEGIN client_root={settings.client_root} resume={bool(resume)}")

    # Mixed has no real canonical representative, but the combined container
    # dispatch/verifier must still pass synthetically before an external sample
    # can be the only remaining format gate.
    gates["model062_mixed_synthetic"] = _run_logged(
        "model062_mixed_synthetic", lambda: run_mixed_physique_synthetic_devtest(root)
    )
    # Mixed-Physique stays implemented but is explicitly outside the Release 1.0
    # support/certification claim. Do not spend the 1.0 gate searching or running
    # a physical representative; preserve the pipeline for post-1.0 work.
    gates["model062_mixed_physical"] = {
        "status": MIXED_PHYSIQUE_RELEASE_1_SCOPE,
        "requested": 0, "passed": 0, "failed": [], "results": [],
        "physical_mixed_certified": False,
        "release_1_blocking": MIXED_PHYSIQUE_RELEASE_1_BLOCKING,
        "post_1_0_backlog": True,
        "discovered_representative_count": len(mixed_rows),
    }

    gates["model062_physical_corpus"] = _run_logged(
        "model062_physical_corpus", lambda: audit_model062_physical_corpus(registry, resolver, sample_limit=100)
    )

    # Physical Blender gates.  --resume may reuse only exact PASS batch reports
    # from pt_build whose selected asset set matches the current plan.  All
    # corpus/read-only gates are rerun against the mounted client.
    gates["rigid_context_census"] = _run_logged(
        "rigid_context_census", lambda: audit_rigid_context_census(registry, resolver, physical=True, sample_limit=100)
    )
    gates["rigid_lod_context_corpus"] = _run_logged(
        "rigid_lod_context_corpus", lambda: audit_rigid_lod_context_corpus(registry, sample_limit=100)
    )
    gates["model062_rigid"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/rigid_semantic_auto/batch_result.json",
            "model062_rigid", rigid_rows,
            lambda: run_rigid_semantic_automated_devtest_batch(
                settings, registry, resolver, certifications, rigid_rows, amplitude=0.12,
            ),
        )
        if rigid_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["model062_rigid_standalone"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/standalone_rigid_auto/batch_result.json",
            "model062_rigid_standalone", standalone_rigid_rows,
            lambda: run_standalone_rigid_automated_devtest_batch(
                settings, registry, resolver, certifications, standalone_rigid_rows, amplitude=0.12,
            ),
        )
        if standalone_rigid_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["model062_static"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/static_semantic_auto/batch_result.json",
            "model062_static", static_rows,
            lambda: run_static_semantic_automated_devtest_batch(
                settings, registry, resolver, certifications, static_rows, amplitude=0.08, require_topology=True,
            ),
        )
        if static_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["model062_static_corpus"] = _run_logged(
        "model062_static_corpus", lambda: audit_model062_static_physical_corpus(registry, resolver)
    )
    gates["stage072_physical_corpus"] = _run_logged(
        "stage072_physical_corpus", lambda: audit_stage072_physical_corpus(registry.records, resolver, per_profile=2)
    )
    gates["stage072_stagearea_corpus"] = _run_logged(
        "stage072_stagearea_corpus", lambda: audit_stage072_stagearea_rebuild(registry.records, resolver)
    )
    gates["stage072_normals_corpus"] = _run_logged(
        "stage072_normals_corpus", lambda: audit_stage072_normals(registry.records, resolver)
    )
    gates["stage072_texture_corpus"] = _run_logged(
        "stage072_texture_corpus", lambda: audit_stage072_texture_presence(registry.records, resolver)
    )
    gates["stage072"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/stage072_auto/batch_result.json",
            "stage072", stage_rows,
            lambda: run_stage072_automated_devtest_batch(settings, registry, resolver, certifications, stage_rows),
        )
        if stage_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["stage072_materials"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/release_1_auto/stage072_materials/batch_result.json",
            "stage072_materials", stage_rows,
            lambda: run_stage072_material_automated_devtest_batch(settings, registry, resolver, stage_rows),
        )
        if stage_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["stage072_material_corpus"] = _run_logged(
        "stage072_material_corpus", lambda: audit_stage072_material_physical_corpus(registry, resolver)
    )
    gates["animation_pose_space"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/animation_pose_auto/batch_result.json",
            "animation_pose_space", animation_rows,
            lambda: run_animation_pose_automated_devtest_batch(
                settings, registry, resolver, certifications, animation_rows, fps=int(animation_fps),
            ),
        )
        if animation_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["smb_animation_corpus"] = _run_logged(
        "smb_animation_corpus", lambda: audit_smb_animation_corpus(registry, resolver, sample_limit=25)
    )
    player_scale_required = int(
        ((((gates.get("smb_animation_corpus") or {}).get("by_domain") or {}).get("PLAYER") or {}).get("scale_key_count") or 0)
    ) > 0
    gates["player_scale_witness"] = (
        _run_logged(
            "player_scale_witness",
            lambda: run_player_scale_witness(
                settings, registry, resolver, certifications, fps=int(animation_fps),
            ),
        )
        if player_scale_required else {
            "status":"EMPTY", "domain":"PLAYER",
            "reason":"NO_PHYSICAL_PLAYER_SCALE_TRACKS",
            "witness_track_counts":{"rot":0,"pos":0,"scale":0},
            "runtime_authorized":False,"production_authorized":False,
            "client_write_authorized":False,"server_write_authorized":False,"client_modified":False,
        }
    )
    gates["standalone_animation_pose_space"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/standalone_animation_pose/batch_result.json",
            "standalone_animation_pose_space", standalone_animation_rows,
            lambda: run_standalone_animation_pose_devtest_batch(
                settings, registry, resolver, certifications, standalone_animation_rows, fps=int(animation_fps),
            ),
        )
        if standalone_animation_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["model062_materials"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/release_1_auto/materials/batch_result.json",
            "model062_materials", material_rows,
            lambda: run_model062_material_automated_devtest_batch(settings, registry, resolver, material_rows),
        )
        if material_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["model062_material_corpus"] = _run_logged(
        "model062_material_corpus", lambda: audit_model062_material_physical_corpus(registry, resolver, sample_limit=100)
    )
    gates["model062_texture_presence"] = _run_logged(
        "model062_texture_presence", lambda: audit_model062_texture_presence(root, registry, resolver, sample_limit=100)
    )

    object_groups = {
        d: choose_object_local_representatives(registry, resolver, limit=int(object_local_limit), domain=d)
        for d in CONTENT_DOMAINS
    }
    object_rows = _flatten(object_groups)
    plan["object_local_representatives"] = object_groups
    gates["object_local_blender"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/object_local_auto/batch_result.json",
            "object_local_blender", object_rows,
            lambda: run_object_local_automated_devtest_batch(
                settings, registry, resolver, certifications, object_rows, fps=int(animation_fps),
            ),
        )
        if object_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["object_local_writer_corpus"] = _run_logged(
        "object_local_writer_corpus", lambda: audit_object_local_writer_corpus(
            root, registry, resolver, sample_limit=max(25, int(object_local_limit)),
        )
    )
    gates["object_local_physical_corpus"] = _run_logged(
        "object_local_physical_corpus", lambda: audit_object_local_physical_corpus(
            registry.records, resolver, per_subtype=max(3, int(object_local_limit)),
        )
    )

    texlink_groups = {
        d: choose_multilayer_representatives(registry, resolver, limit=int(texlink_limit), domain=d)
        for d in CONTENT_DOMAINS
    }
    texlink_rows = _flatten(texlink_groups)
    plan["multilayer_texlink_representatives"] = texlink_groups
    gates["multilayer_texlink_blender"] = (
        _resume_or_run_batch(
            root, bool(resume), "pt_build/devtest/texlink_auto/batch_result.json",
            "multilayer_texlink_blender", texlink_rows,
            lambda: run_multilayer_texlink_automated_devtest_batch(
                settings, registry, resolver, certifications, texlink_rows,
            ),
        )
        if texlink_rows else {"status":"EMPTY","requested":0,"results":[]}
    )
    gates["multilayer_texlink_corpus"] = _run_logged(
        "multilayer_texlink_corpus", lambda: audit_multilayer_texlink_corpus(registry.records, resolver, per_profile=1)
    )

    # Proprietary texture adapters and rare/outlier physical families.
    gates["proprietary_texture_codecs"] = _run_logged(
        "proprietary_texture_codecs", lambda: audit_proprietary_texture_codecs(root, registry, resolver, per_family=3)
    )
    gates["proprietary_texture_corpus"] = _run_logged(
        "proprietary_texture_corpus", lambda: audit_proprietary_texture_physical_corpus(
            root, registry, resolver, failure_sample_limit=100, progress=True,
        )
    )
    gates["rare_outliers"] = _run_logged(
        "rare_outliers_tga_census", lambda: audit_rare_outliers_and_tga(registry.records, resolver, progress=True)
    )
    gates["rare_support"] = _run_logged(
        "rare_support", lambda: audit_rare_support(resolver, work=root/"pt_build"/"devtest"/"release_1_auto"/"rare_support")
    )

    # INX/SMB preservation and temporary edits are audited by exact physical
    # files per semantic content domain.  A broad `char/` PASS must never paint
    # EFFECT/MAP/WEAPON_ITEM green merely because those files share a writer.
    inx_files = _physical_files_by_domain(registry, ".inx")
    smb_files = _physical_files_by_domain(registry, ".smb")
    inx_noop_by_domain = {}
    inx_edit_by_domain = {}
    smb_noop_by_domain = {}
    smb_edit_by_domain = {}
    for d, paths in inx_files.items():
        if not paths:
            continue
        inx_noop_by_domain[d] = _run_logged(
            f"inx_noop_corpus[{d}] files={len(paths)} sample=25",
            lambda paths=paths: audit_inx_writer_corpus(settings.client_root, logical_paths=paths, sample_limit=25),
        )
        inx_edit_by_domain[d] = _run_logged(
            f"inx_edit_corpus[{d}] files={len(paths)} sample=25",
            lambda paths=paths: audit_inx_writer_edit_corpus(settings.client_root, logical_paths=paths, sample_limit=25),
        )
    for d, paths in smb_files.items():
        if not paths:
            continue
        smb_noop_by_domain[d] = _run_logged(
            f"smb_noop_corpus[{d}] files={len(paths)} sample=25",
            lambda paths=paths: audit_smb_writer_corpus(root, settings.client_root, logical_paths=paths, sample_limit=25),
        )
        smb_edit_by_domain[d] = _run_logged(
            f"smb_edit_corpus[{d}] files={len(paths)} sample=25",
            lambda paths=paths: audit_smb_writer_edit_corpus(root, settings.client_root, logical_paths=paths, sample_limit=25),
        )
    gates["inx_noop_corpus"] = _domain_audit_summary(inx_noop_by_domain)
    gates["inx_edit_corpus"] = _domain_audit_summary(inx_edit_by_domain)
    gates["smb_noop_corpus"] = _domain_audit_summary(smb_noop_by_domain)
    gates["smb_edit_corpus"] = _domain_audit_summary(smb_edit_by_domain)
    gates["motion_semantic_edit"] = _run_logged(
        "motion_semantic_edit_full_corpus", lambda: audit_motion_writer_semantic_edit_corpus(
            root, registry, resolver, pair_limit=int(motion_pair_limit), sample_limit=25, progress=True,
            operation_timeout_seconds=float(motion_semantic_timeout_seconds),
            checkpoint_path=root / "pt_build" / "devtest" / "release_1_auto" / "motion_semantic_checkpoint.jsonl",
            resume=bool(resume),
        )
    )

    # Determine automatic gate completeness. Mixed-Physique physical certification
    # is deliberately absent from this required set because Release 1.0 scope marks
    # it OUT_OF_SCOPE_NOT_CERTIFIED; the status is still reported separately.
    required = {
        "model062_mixed_synthetic": False,
        "model062_physical_corpus": False,
        "rigid_context_census": False,
        "rigid_lod_context_corpus": False,
        "model062_rigid": False,
        "model062_rigid_standalone": False,
        "model062_static": False,
        "model062_static_corpus": False,
        "stage072_physical_corpus": False,
        "stage072_stagearea_corpus": False,
        "stage072_normals_corpus": False,
        "stage072_texture_corpus": False,
        "stage072": False,
        "stage072_materials": False,
        "stage072_material_corpus": False,
        "animation_pose_space": False,
        "smb_animation_corpus": False,
        "player_scale_witness": not player_scale_required,
        "standalone_animation_pose_space": True,
        "model062_materials": False,
        "model062_material_corpus": False,
        "model062_texture_presence": False,
        "object_local_blender": False,
        "object_local_writer_corpus": False,
        "object_local_physical_corpus": False,
        "multilayer_texlink_blender": False,
        "multilayer_texlink_corpus": False,
        "proprietary_texture_codecs": False,
        "proprietary_texture_corpus": False,
        "rare_outliers": False,
        "rare_support": False,
        "inx_noop_corpus": False,
        "inx_edit_corpus": False,
        "smb_noop_corpus": False,
        "smb_edit_corpus": False,
        "motion_semantic_edit": False,
    }
    for name, allow_empty in required.items():
        row=gates.get(name) or {}
        # FIX24_RELEASE_CAPABILITY_TARGET_SEPARATION: the strict gate status may
        # be red because the target corpus itself is incomplete/invalid.  The
        # tool-capability gate remains fail-closed on parser/codec failures.
        if name == "model062_texture_presence":
            gate_status = row.get("audit_status") or row.get("status")
        elif name == "proprietary_texture_corpus":
            gate_status = row.get("capability_status") or row.get("status")
        else:
            gate_status = row.get("status")
        gate_ok = gate_status == "PASS" or (allow_empty and gate_status in {"EMPTY", "NOT_PRESENT"})
        if not gate_ok:
            blockers.append({"gate":name,"status":gate_status,"strict_status":row.get("status"),"reason":"AUTOMATED_GATE_NOT_PASS"})

    # Release 1.0 is a content-domain x family contract. If the canonical
    # inventory contains a family in a domain, the representative planner must
    # exercise it through either the normal bound path or the standalone
    # structural-gate-first path. Presence can never be silently skipped.
    inventory = (build_release_1_coverage(registry, external_evidence={}).get("inventory") or {}).get("by_domain") or {}
    rigid_selected_by_domain = {d: 0 for d in inventory}
    static_selected_by_domain = {d: 0 for d in inventory}
    material_selected_by_domain = {d: 0 for d in inventory}
    for row in rigid_rows + standalone_rigid_rows:
        rigid_selected_by_domain[str(row.get("domain"))] = rigid_selected_by_domain.get(str(row.get("domain")), 0) + 1
    for row in static_rows:
        static_selected_by_domain[str(row.get("domain"))] = static_selected_by_domain.get(str(row.get("domain")), 0) + 1
    for row in material_rows:
        material_selected_by_domain[str(row.get("domain"))] = material_selected_by_domain.get(str(row.get("domain")), 0) + 1
    for domain, counts in inventory.items():
        rigid_count = int((counts or {}).get("SMD_MODEL_062_RIGID_PHYSIQUE") or 0)
        static_count = int((counts or {}).get("SMD_MODEL_062_STATIC") or 0)
        material_count = int((counts or {}).get("MODEL062_HAS_MATERIALS") or 0)
        if rigid_count and not rigid_selected_by_domain.get(domain):
            blockers.append({
                "gate":"MODEL062_RIGID", "domain":domain, "status":"BLOCKED_NO_AUTOMATABLE_REPRESENTATIVE",
                "asset_count":rigid_count, "reason":"PRESENT_BUT_NO_AUTOMATABLE_REPRESENTATIVE",
            })
        if static_count and not static_selected_by_domain.get(domain):
            blockers.append({
                "gate":"MODEL062_STATIC", "domain":domain, "status":"BLOCKED_NO_AUTOMATABLE_REPRESENTATIVE",
                "asset_count":static_count, "reason":"PRESENT_BUT_NO_AUTOMATABLE_REPRESENTATIVE",
            })
        if material_count and not material_selected_by_domain.get(domain):
            blockers.append({
                "gate":"MATERIALS", "domain":domain, "status":"BLOCKED_NO_AUTOMATABLE_REPRESENTATIVE",
                "asset_count":material_count, "reason":"MODEL062_MATERIALS_PRESENT_BUT_NO_AUTOMATABLE_REPRESENTATIVE",
            })

    object_physical = gates.get("object_local_physical_corpus") or {}
    if object_physical.get("status") == "PASS" and not bool(object_physical.get("object_local_complete_candidate")):
        blockers.append({
            "gate":"OBJECT_LOCAL_ANIMATION", "status":"BLOCKED_UNSUPPORTED_SUBTYPE",
            "reason":"FULL_PARSE_FAILURE_REMAINS",
            "segmented_tmframe_files":int(object_physical.get("segmented_tmframe_files") or 0),
            "full_parse_failure_files":int((object_physical.get("tag_counts") or {}).get("FULL_PARSE_FAILURE") or 0),
        })

    # Attribute physical feature evidence to the Release 1.0 content domains.
    # A global PASS is insufficient when a feature exists in several content
    # classes: every present domain must receive at least one automated witness.
    object_local_physical_by_domain = {d: 0 for d in CONTENT_DOMAINS}
    for row in object_physical.get("rows") or []:
        domain = content_domain_from_values(row.get("path") or "", row.get("category") or "")
        if domain in object_local_physical_by_domain:
            object_local_physical_by_domain[domain] += 1
    object_local_selected_by_domain = {d: len(object_groups.get(d) or []) for d in CONTENT_DOMAINS}
    object_local_feature_pass_domains, object_local_feature_coverage = _object_local_feature_coverage(
        object_physical, object_rows, gates.get("object_local_blender"),
    )
    for domain, count in object_local_physical_by_domain.items():
        if count and not object_local_selected_by_domain.get(domain):
            blockers.append({
                "gate":"OBJECT_LOCAL_ANIMATION", "domain":domain,
                "status":"BLOCKED_NO_DOMAIN_REPRESENTATIVE", "asset_count":count,
                "reason":"PHYSICAL_FEATURE_PRESENT_BUT_NO_AUTOMATED_DOMAIN_WITNESS",
            })
        elif count:
            missing=(object_local_feature_coverage.get(domain) or {}).get("missing") or []
            if missing:
                blockers.append({
                    "gate":"OBJECT_LOCAL_ANIMATION", "domain":domain,
                    "status":"BLOCKED_SUBTYPE_WITHOUT_BLENDER_WITNESS",
                    "missing_subtypes":missing,
                    "reason":"PHYSICAL_OBJECT_LOCAL_SUBTYPE_PRESENT_WITHOUT_AUTOMATED_BLENDER_AND_WRITER_WITNESS",
                })

    texlink_physical = gates.get("multilayer_texlink_corpus") or {}
    multilayer_physical_by_domain = {d: 0 for d in CONTENT_DOMAINS}
    for row in texlink_physical.get("rows") or []:
        domain = content_domain_from_values(row.get("relative_path") or "", row.get("category") or "")
        if domain in multilayer_physical_by_domain:
            multilayer_physical_by_domain[domain] += 1
    texlink_selected_by_domain = {d: len(texlink_groups.get(d) or []) for d in CONTENT_DOMAINS}
    multilayer_profile_pass_domains, multilayer_profile_coverage = _multilayer_profile_coverage(
        texlink_physical, texlink_rows, gates.get("multilayer_texlink_blender"),
    )
    for domain, count in multilayer_physical_by_domain.items():
        if count and not texlink_selected_by_domain.get(domain):
            blockers.append({
                "gate":"MULTILAYER_TEXLINK", "domain":domain,
                "status":"BLOCKED_NO_DOMAIN_REPRESENTATIVE", "asset_count":count,
                "reason":"PHYSICAL_FEATURE_PRESENT_BUT_NO_AUTOMATED_DOMAIN_WITNESS",
            })
        elif count:
            missing=(multilayer_profile_coverage.get(domain) or {}).get("missing") or []
            if missing:
                blockers.append({
                    "gate":"MULTILAYER_TEXLINK", "domain":domain,
                    "status":"BLOCKED_PROFILE_WITHOUT_ROUNDTRIP_WITNESS",
                    "missing_profiles":missing,
                    "reason":"PHYSICAL_TWO_STAGE_TEXLINK_PROFILE_PRESENT_WITHOUT_AUTOMATED_ROUNDTRIP_WITNESS",
                })
    if texlink_physical.get("status") == "PASS" and not bool(texlink_physical.get("multilayer_two_stage_complete_candidate")):
        blockers.append({
            "gate":"MULTILAYER_TEXLINK", "status":"BLOCKED_UNSUPPORTED_DEPTH_OR_CHAIN",
            "reason":"PHYSICAL_CORPUS_CONTAINS_TEXLINK_SHAPE_OUTSIDE_TWO_STAGE_CANDIDATE",
            "three_plus_layer_files":int(texlink_physical.get("three_plus_layer_files") or 0),
            "invalid_chain_files":int(texlink_physical.get("invalid_chain_files") or 0),
            "cycle_files":int(texlink_physical.get("cycle_files") or 0),
        })


    stage_texture = gates.get("stage072_texture_corpus") or {}
    stage_physical = gates.get("stage072_physical_corpus") or {}
    if _status_pass(stage_physical) and not _stage072_full_corpus_proven(stage_physical):
        blockers.append({
            "gate":"STAGE072", "domain":"MAP",
            "status":"BLOCKED_INCOMPLETE_PHYSICAL_CORPUS",
            "candidate_files_expected":stage_physical.get("candidate_files_expected"),
            "physical_files_audited":stage_physical.get("physical_files_audited"),
            "full_parse_pass_files":stage_physical.get("full_parse_pass_files"),
            "reason":"RELEASE_1_STAGE072_REQUIRES_THE_KNOWN_CANONICAL_63_FILE_PHYSICAL_CORPUS",
        })
    stage_aux_specs = (
        ("stage072_stagearea_corpus", "reconstruction_pass_files", "STAGEAREA"),
        ("stage072_normals_corpus", "audit_pass_files", "NORMALS"),
        ("stage072_texture_corpus", "physical_files_audited", "TEXTURES"),
    )
    for gate_name, pass_key, label in stage_aux_specs:
        row = gates.get(gate_name) or {}
        if _status_pass(row) and not _stage072_aux_corpus_proven(row, pass_key):
            blockers.append({
                "gate":"STAGE072", "domain":"MAP",
                "status":"BLOCKED_INCOMPLETE_" + label + "_CORPUS",
                "candidate_files_expected":row.get("candidate_files_expected"),
                "physical_files_audited":row.get("physical_files_audited"),
                "pass_files":row.get(pass_key),
                "reason":"STAGE072_AUXILIARY_CORPUS_GATE_DID_NOT_PROVE_ALL_63_CANONICAL_FILES",
            })
    stage_material_corpus = gates.get("stage072_material_corpus") or {}
    if _status_pass(stage_material_corpus) and not _stage072_material_corpus_proven(stage_material_corpus):
        blockers.append({
            "gate":"STAGE072", "domain":"MAP",
            "status":"BLOCKED_INCOMPLETE_MATERIAL_CORPUS",
            "asset_count":stage_material_corpus.get("asset_count"),
            "failure_count":stage_material_corpus.get("failure_count"),
            "reason":"STAGE072_MATERIAL_CORPUS_GATE_DID_NOT_PROVE_ALL_63_CANONICAL_FILES",
        })
    if _status_pass(stage_texture) and stage_texture.get("texture_reference_classification_complete_candidate") is not True:
        blockers.append({
            "gate":"STAGE072", "domain":"MAP",
            "status":"BLOCKED_UNCLASSIFIED_TEXTURE_REFERENCE",
            "unclassified_unique_texture_references":int(stage_texture.get("unclassified_unique_texture_references") or 0),
            "reason":"STAGE_TEXTURE_REFERENCE_EXISTS_WITHOUT_EXACT_OR_PROVEN_TRANSPORT_CLASSIFICATION",
        })

    smb_animation = gates.get("smb_animation_corpus") or {}
    animated_smb_by_domain = {
        d: int(((smb_animation.get("by_domain") or {}).get(d) or {}).get("animated_smb_file_count") or 0)
        for d in CONTENT_DOMAINS
    }
    standalone_animation_selected_by_domain = {d: len(standalone_animation_groups.get(d) or []) for d in CONTENT_DOMAINS}

    model062_physical = gates.get("model062_physical_corpus") or {}
    if _status_pass(model062_physical):
        mixed_count=int(model062_physical.get("physical_mixed_count") or 0)
    else:
        physique_counts={}
        try:
            from .physique_audit import audit_physique_modes
            physique_counts=(audit_physique_modes(registry.records).get("raw_mode_counts") or {})
        except Exception:
            physique_counts={}
        mixed_count=int(physique_counts.get("MIXED") or 0)
    mixed_physical = gates.get("model062_mixed_physical") or {}
    mixed_physical_certified = bool(
        mixed_count > 0
        and str(mixed_physical.get("status") or "") == "PASS"
        and bool(mixed_physical.get("physical_mixed_certified"))
        and int(mixed_physical.get("requested") or 0) == mixed_count
        and int(mixed_physical.get("passed") or 0) == mixed_count
    )
    # Scope decision, not a PASS: Mixed-Physique is retained as NOT_CERTIFIED
    # but it does not block Release 1.0. Candidate/authoring safety is unchanged.
    mixed_release_scope = {
        "gate": "MODEL062_MIXED",
        "status": MIXED_PHYSIQUE_RELEASE_1_SCOPE,
        "release_1_blocking": MIXED_PHYSIQUE_RELEASE_1_BLOCKING,
        "physical_mixed_count": mixed_count,
        "pipeline_wired": True,
        "physical_certified": mixed_physical_certified,
        "post_1_0_backlog": True,
        "reason": "PHYSICAL_MIXED_PHYSIQUE_CERTIFICATION_DEFERRED_POST_1_0",
    }

    model062_family_pass = dict((gates.get("model062_physical_corpus") or {}).get("pass_domains_by_family") or {})
    rigid_physical_parse_pass_domains = set(model062_family_pass.get("SMD_MODEL_062_RIGID_PHYSIQUE") or [])
    static_physical_parse_pass_domains = set(model062_family_pass.get("SMD_MODEL_062_STATIC") or [])
    rigid_representative_pass_domains = (
        _passed_domains(rigid_rows, gates.get("model062_rigid"))
        | _passed_domains(standalone_rigid_rows, gates.get("model062_rigid_standalone"))
    )
    rigid_pass_domains = rigid_representative_pass_domains & rigid_physical_parse_pass_domains
    static_representative_pass_domains = _passed_domains(static_rows, gates.get("model062_static"))
    static_corpus_pass_domains = set((gates.get("model062_static_corpus") or {}).get("pass_domains") or [])
    static_pass_domains = static_representative_pass_domains & static_corpus_pass_domains & static_physical_parse_pass_domains
    animation_pass_domains = (
        _passed_domains(animation_rows, gates.get("animation_pose_space"))
        | _passed_domains(standalone_animation_rows, gates.get("standalone_animation_pose_space"))
    )
    if _status_pass(gates.get("player_scale_witness")):
        animation_pass_domains.add("PLAYER")
    animation_track_witness_by_domain = {d: {"rot": 0, "pos": 0, "scale": 0} for d in CONTENT_DOMAINS}
    for batch_name in ("animation_pose_space", "standalone_animation_pose_space"):
        for row in (gates.get(batch_name) or {}).get("results") or []:
            if str(row.get("status") or "") != "PASS":
                continue
            domain=str(row.get("domain") or "")
            if domain not in animation_track_witness_by_domain:
                continue
            counts=dict(row.get("track_key_counts") or {})
            for track in ("rot","pos","scale"):
                animation_track_witness_by_domain[domain][track] += int(counts.get(track) or 0)
    scale_witness_gate = gates.get("player_scale_witness") or {}
    if str(scale_witness_gate.get("status") or "") == "PASS":
        counts = dict(scale_witness_gate.get("witness_track_counts") or {})
        for track in ("rot","pos","scale"):
            animation_track_witness_by_domain["PLAYER"][track] += int(counts.get(track) or 0)
    animation_track_required_by_domain = {d: {
        "rot": int(((smb_animation.get("by_domain") or {}).get(d) or {}).get("rot_key_count") or 0),
        "pos": int(((smb_animation.get("by_domain") or {}).get(d) or {}).get("pos_key_count") or 0),
        "scale": int(((smb_animation.get("by_domain") or {}).get(d) or {}).get("scale_key_count") or 0),
    } for d in CONTENT_DOMAINS}
    for domain, required_tracks in animation_track_required_by_domain.items():
        missing=[track for track,count in required_tracks.items() if count>0 and int(animation_track_witness_by_domain[domain].get(track) or 0)<=0]
        if missing:
            blockers.append({
                "gate":"EXISTING_ANIMATION", "domain":domain,
                "status":"BLOCKED_TRACK_SUBTYPE_WITHOUT_POSE_WITNESS",
                "missing_track_types":missing,
                "reason":"PHYSICAL_SMB_TRACK_SUBTYPE_PRESENT_WITHOUT_AUTOMATED_BLENDER_POSE_WITNESS",
            })
    for domain, count in animated_smb_by_domain.items():
        if count and domain not in animation_pass_domains:
            blockers.append({
                "gate":"EXISTING_ANIMATION", "domain":domain,
                "status":"BLOCKED_NO_POSE_SPACE_DOMAIN_WITNESS", "animated_smb_file_count":count,
                "reason":"PHYSICAL_ANIMATED_SMB_PRESENT_BUT_NO_AUTOMATED_POSE_SPACE_PASS",
            })
    material_family_pass_domains, material_family_coverage = _model062_material_family_coverage(
        gates.get("model062_material_corpus") or {}, material_rows, gates.get("model062_materials"),
    )
    material_corpus_pass_domains = set((gates.get("model062_material_corpus") or {}).get("pass_domains") or [])
    material_pass_domains = material_family_pass_domains & material_corpus_pass_domains
    for domain, detail in material_family_coverage.items():
        missing = list((detail or {}).get("missing") or [])
        if missing:
            blockers.append({
                "gate":"MATERIALS", "domain":domain,
                "status":"BLOCKED_MODEL062_FAMILY_WITHOUT_WRITER_WITNESS",
                "missing_families":missing,
                "reason":"PHYSICAL_MODEL062_MATERIAL_FAMILY_PRESENT_WITHOUT_EXECUTED_CANDIDATE_WRITER_WITNESS",
            })
    model062_texture_gate = gates.get("model062_texture_presence") or {}
    model062_texture_presence_pass_domains = set(model062_texture_gate.get("pass_domains") or [])
    model062_texture_audit_domains = set(model062_texture_gate.get("audit_complete_domains") or [])
    target_content_issues=[]
    if str(model062_texture_gate.get("target_content_status") or model062_texture_gate.get("status") or "") != "PASS":
        target_content_issues.append({
            "gate":"model062_texture_presence","status":model062_texture_gate.get("target_content_status") or model062_texture_gate.get("status"),
            "failure_count":int(model062_texture_gate.get("failure_count") or 0),
            "reason":"TARGET_MODEL062_TEXTURE_REFERENCES_MISSING_OR_INVALID",
        })
    texture_corpus_gate = gates.get("proprietary_texture_corpus") or {}
    if int(texture_corpus_gate.get("target_content_invalid_count") or 0) > 0:
        target_content_issues.append({
            "gate":"proprietary_texture_corpus","status":texture_corpus_gate.get("target_content_status") or "FAIL",
            "failure_count":int(texture_corpus_gate.get("target_content_invalid_count") or 0),
            "reason":"TARGET_TEXTURE_PAYLOAD_IS_NOT_A_VALID_IMAGE_CONTAINER",
            "sample":list(texture_corpus_gate.get("target_content_invalid_sample") or []),
        })
    target_content_readiness_status="PASS" if not target_content_issues else "GAPS_PRESENT"
    object_local_corpus_ok = (
        _status_pass(gates.get("object_local_writer_corpus"))
        and _status_pass(object_physical)
        and bool(object_physical.get("object_local_complete_candidate"))
    )
    object_local_pass_domains = (
        (_passed_domains(object_rows, gates.get("object_local_blender")) & object_local_feature_pass_domains)
        if object_local_corpus_ok else set()
    )
    multilayer_corpus_ok = (
        _status_pass(texlink_physical)
        and bool(texlink_physical.get("multilayer_two_stage_complete_candidate"))
    )
    multilayer_pass_domains = (
        (_passed_domains(texlink_rows, gates.get("multilayer_texlink_blender")) & multilayer_profile_pass_domains)
        if multilayer_corpus_ok else set()
    )
    stage_geometry_domains = _passed_domains(stage_rows, gates.get("stage072"))
    stage_material_corpus_domains = set((gates.get("stage072_material_corpus") or {}).get("pass_domains") or [])
    stage_material_domains = (
        _passed_domains(stage_rows, gates.get("stage072_materials")) & stage_material_corpus_domains
        if _stage072_material_corpus_proven(gates.get("stage072_material_corpus")) else set()
    )
    stage_texture = gates.get("stage072_texture_corpus") or {}
    stage_texture_transport_ok = bool(
        _status_pass(stage_texture)
        and stage_texture.get("texture_reference_classification_complete_candidate") is True
    )
    stage_pass_domains = {"MAP"} if (
        "MAP" in stage_geometry_domains and "MAP" in stage_material_domains
        and _stage072_full_corpus_proven(gates.get("stage072_physical_corpus"))
        and _stage072_aux_corpus_proven(gates.get("stage072_stagearea_corpus"), "reconstruction_pass_files")
        and _stage072_aux_corpus_proven(gates.get("stage072_normals_corpus"), "audit_pass_files")
        and _stage072_aux_corpus_proven(gates.get("stage072_texture_corpus"), "physical_files_audited")
        and stage_texture_transport_ok
    ) else set()
    inventory_by_domain = (build_release_1_coverage(registry, external_evidence={}).get("inventory") or {}).get("by_domain") or {}
    semantic_required_domains, semantic_pass_domains, motion_semantic_by_domain = _motion_semantic_domain_passes(
        registry, gates.get("motion_semantic_edit"),
    )
    inx_pass_domains = {
        d for d, counts in inventory_by_domain.items()
        if int((counts or {}).get("PHYSICAL_INX_FILE") or 0) > 0
        and str(((gates.get("inx_noop_corpus") or {}).get("by_domain") or {}).get(d, {}).get("status") or "") == "PASS"
        and str(((gates.get("inx_edit_corpus") or {}).get("by_domain") or {}).get(d, {}).get("status") or "") == "PASS"
        and (d not in semantic_required_domains or d in semantic_pass_domains)
    }
    smb_pass_domains = {
        d for d, counts in inventory_by_domain.items()
        if int((counts or {}).get("PHYSICAL_SMB_FILE") or 0) > 0
        and str(((gates.get("smb_noop_corpus") or {}).get("by_domain") or {}).get(d, {}).get("status") or "") == "PASS"
        and str(((gates.get("smb_edit_corpus") or {}).get("by_domain") or {}).get(d, {}).get("status") or "") == "PASS"
        and (d not in semantic_required_domains or d in semantic_pass_domains)
    }
    for domain in sorted(semantic_required_domains - semantic_pass_domains):
        blockers.append({
            "gate":"MOTION_SEMANTIC_EDIT", "domain":domain,
            "status":"BLOCKED_DOMAIN_SEMANTIC_EDIT_CORPUS",
            "reason":"PHYSICAL_MOTION_CONTEXT_DOMAIN_DID_NOT_COMPLETE_TEMP_INX_SMB_SEMANTIC_EDIT_AUDIT",
        })

    lod_corpus = gates.get("rigid_lod_context_corpus") or {}
    lod_rows_by_domain = {d: [] for d in CONTENT_DOMAINS}
    for row in lod_corpus.get("rows") or []:
        domain = content_domain_from_values(row.get("asset") or "", row.get("category") or "")
        if domain in lod_rows_by_domain and (row.get("lod_groups") or {}):
            if any((row.get("lod_groups") or {}).get(x) for x in ("high","default","low")):
                lod_rows_by_domain[domain].append(row)
    lod_asset_rows_by_domain = {d: [] for d in CONTENT_DOMAINS}
    for row in lod_corpus.get("asset_summary") or []:
        domain = content_domain_from_values(row.get("asset") or "", "")
        if domain in lod_asset_rows_by_domain:
            lod_asset_rows_by_domain[domain].append(row)
    lod_corpus_pass_domains = {
        d for d, rows in lod_asset_rows_by_domain.items()
        if rows and all(bool(r.get("authorable")) for r in rows)
    }
    lod_content_inconsistent_by_domain = {
        d: sum(1 for r in rows if str(r.get("state")) == "MISSING_SMD_NODES_FAIL_CLOSED")
        for d, rows in lod_rows_by_domain.items()
    }
    lod_single_tier_full_container_by_domain = {
        d: sum(1 for r in rows if str(r.get("state")) == "AUTHORABLE_SINGLE_TIER_FULL_CONTAINER")
        for d, rows in lod_rows_by_domain.items()
    }
    lod_fixed16_by_domain = {
        d: sum(1 for r in rows if str(r.get("state")) == "IMPORTABLE_FIXED16_MODEL_KEY")
        for d, rows in lod_rows_by_domain.items()
    }
    lod_assets_without_authorable_by_domain = {
        d: sum(1 for r in rows if not bool(r.get("authorable")))
        for d, rows in lod_asset_rows_by_domain.items()
    }
    lod_assets_with_diagnosed_outliers_by_domain = {
        d: sum(1 for r in rows if bool(r.get("authorable_with_diagnosed_fail_closed_outliers")))
        for d, rows in lod_asset_rows_by_domain.items()
    }
    for d, count in lod_assets_without_authorable_by_domain.items():
        if count:
            blockers.append({
                "gate":"LOD", "domain":d,
                "status":"BLOCKED_NO_AUTHORABLE_LOD_CONFIG",
                "asset_count":count,
                "reason":"EVERY_LOD_CONFIG_FOR_ONE_OR_MORE_ASSETS_IS_NON_AUTHORABLE_OR_UNKNOWN",
            })
    rigid_census_by_domain = dict((gates.get("rigid_context_census") or {}).get("by_domain") or {})
    rigid_census_pass_domains = {
        d for d, row in rigid_census_by_domain.items()
        if int((row or {}).get("TOTAL") or 0) > 0 and int((row or {}).get("UNRESOLVED") or 0) == 0
    }
    evidence = {
        "rigid_automated_pass_domains": sorted(rigid_pass_domains),
        "rigid_physical_parse_pass_domains": sorted(rigid_physical_parse_pass_domains),
        "rigid_context_census_by_domain": rigid_census_by_domain,
        "rigid_context_census_pass_domains": sorted(rigid_census_pass_domains),
        "lod_corpus_pass_domains": sorted(lod_corpus_pass_domains),
        "lod_content_inconsistent_by_domain": lod_content_inconsistent_by_domain,
        "lod_single_tier_full_container_by_domain": lod_single_tier_full_container_by_domain,
        "lod_assets_without_authorable_config_by_domain": lod_assets_without_authorable_by_domain,
        "lod_assets_with_diagnosed_fail_closed_outliers_by_domain": lod_assets_with_diagnosed_outliers_by_domain,
        "lod_fixed16_model_key_by_domain": lod_fixed16_by_domain,
        "static_automated_pass_domains": sorted(static_pass_domains),
        "static_corpus_pass_domains": sorted(static_corpus_pass_domains),
        "static_physical_parse_pass_domains": sorted(static_physical_parse_pass_domains),
        "animation_pose_pass_domains": sorted(animation_pass_domains),
        "animated_smb_physical_by_domain": animated_smb_by_domain,
        "model062_material_pass_domains": sorted(material_pass_domains),
        "model062_material_family_coverage": material_family_coverage,
        "model062_texture_presence_pass_domains": sorted(model062_texture_presence_pass_domains),
        "model062_texture_audit_domains": sorted(model062_texture_audit_domains),
        "target_content_readiness_separated": True,
        "stage072_material_pass_domains": sorted(stage_material_domains),
        "stage072_pass_domains": sorted(stage_pass_domains),
        "object_local_physical_by_domain": object_local_physical_by_domain,
        "object_local_feature_coverage": object_local_feature_coverage,
        "object_local_pass_domains": sorted(object_local_pass_domains),
        "multilayer_physical_by_domain": multilayer_physical_by_domain,
        "multilayer_profile_coverage": multilayer_profile_coverage,
        "multilayer_texlink_pass_domains": sorted(multilayer_pass_domains),
        "texture_codec_pass_domains": sorted(
            set(gates.get("proprietary_texture_codecs", {}).get("pass_domains") or [])
            & set(
                (gates.get("proprietary_texture_corpus", {}).get("capability_pass_domains")
                 or gates.get("proprietary_texture_corpus", {}).get("pass_domains") or [])
            )
        ),
        "inx_writer_pass_domains": sorted(inx_pass_domains),
        "smb_writer_pass_domains": sorted(smb_pass_domains),
        "motion_semantic_required_domains": sorted(semantic_required_domains),
        "motion_semantic_pass_domains": sorted(semantic_pass_domains),
        "motion_semantic_by_domain": motion_semantic_by_domain,
        "mixed_physical_certified": mixed_physical_certified,
        "mixed_physical_pass_domains": sorted({str(r.get("domain")) for r in mixed_rows if any(str(x.get("asset")) == str(r.get("asset")) and str(x.get("status")) == "PASS" for x in (mixed_physical.get("results") or []))}),
    }
    coverage=build_release_1_coverage(registry, external_evidence=evidence)
    # The executable matrix and the runner must never disagree.  Domain-level
    # coverage blockers are automatic readiness blockers too; only GLOBAL gates
    # (real Mixed sample and publish/runtime policy) are intentionally handled
    # outside the automatic gate status.
    coverage_automatic_blockers = [
        dict(x) for x in (coverage.get("blocking_gates") or [])
        if str((x or {}).get("domain") or "") != "GLOBAL"
    ]
    existing_keys={(str(b.get("gate") or b.get("capability") or ""),str(b.get("domain") or ""),str(b.get("reason") or b.get("blocker") or "")) for b in blockers}
    for row in coverage_automatic_blockers:
        key=(str(row.get("capability") or ""),str(row.get("domain") or ""),str(row.get("blocker") or ""))
        if key not in existing_keys:
            blockers.append({
                "gate": row.get("capability"), "domain": row.get("domain"),
                "status": "BLOCKED_COVERAGE_MATRIX", "reason": row.get("blocker"),
                "source": "PT_ASSET_RELEASE_1_COVERAGE_V1",
            })
            existing_keys.add(key)
    automatic_status="PASS" if not blockers else "FAIL"
    # Gameplay/runtime acceptance is outside PT Asset Tool 1.0.  Controlled
    # production publish/restore remains safety-locked as an external operation,
    # so automatic tool-capability PASS is still reported as BLOCKED_EXTERNAL.
    overall="BLOCKED_EXTERNAL" if automatic_status=="PASS" else "FAIL"
    result={
        "format":FORMAT,"status":overall,"automatic_gate_status":automatic_status,
        "tool_capability_status":automatic_status,
        "target_content_readiness_status":target_content_readiness_status,
        "target_content_issues":target_content_issues,
        "release_target":"1.0","plan":plan,
        "summary":{
            "model062_physical_corpus": {
                "status": (gates.get("model062_physical_corpus") or {}).get("status"),
                "asset_count": (gates.get("model062_physical_corpus") or {}).get("asset_count"),
                "failure_count": (gates.get("model062_physical_corpus") or {}).get("failure_count"),
                "physical_mixed_count": (gates.get("model062_physical_corpus") or {}).get("physical_mixed_count"),
                "pass_domains_by_family": (gates.get("model062_physical_corpus") or {}).get("pass_domains_by_family"),
            },
            "rigid_context_census": {
                "status": (gates.get("rigid_context_census") or {}).get("status"),
                "rigid_asset_count": (gates.get("rigid_context_census") or {}).get("rigid_asset_count"),
                "unresolved_count": (gates.get("rigid_context_census") or {}).get("unresolved_count"),
                "by_domain": (gates.get("rigid_context_census") or {}).get("by_domain"),
            },
            "rigid_lod_context_corpus": {
                "status": (gates.get("rigid_lod_context_corpus") or {}).get("status"),
                "config_count": (gates.get("rigid_lod_context_corpus") or {}).get("config_count"),
                "importable_config_count": (gates.get("rigid_lod_context_corpus") or {}).get("importable_config_count"),
                "content_inconsistent_config_count": (gates.get("rigid_lod_context_corpus") or {}).get("content_inconsistent_config_count"),
                "single_tier_full_container_config_count": (gates.get("rigid_lod_context_corpus") or {}).get("single_tier_full_container_config_count"),
                "assets_without_authorable_lod_config_count": (gates.get("rigid_lod_context_corpus") or {}).get("assets_without_authorable_lod_config_count"),
                "assets_with_diagnosed_fail_closed_config_outliers_count": (gates.get("rigid_lod_context_corpus") or {}).get("assets_with_diagnosed_fail_closed_config_outliers_count"),
                "lod_tier_count": (gates.get("rigid_lod_context_corpus") or {}).get("lod_tier_count"),
                "lod_tier_missing_node_count": (gates.get("rigid_lod_context_corpus") or {}).get("lod_tier_missing_node_count"),
                "content_inconsistent_by_domain": lod_content_inconsistent_by_domain,
                "single_tier_full_container_by_domain": lod_single_tier_full_container_by_domain,
                "assets_without_authorable_config_by_domain": lod_assets_without_authorable_by_domain,
                "assets_with_diagnosed_fail_closed_outliers_by_domain": lod_assets_with_diagnosed_outliers_by_domain,
            },
            "rigid":_compact_batch(gates.get("model062_rigid")),
            "rigid_standalone":_compact_batch(gates.get("model062_rigid_standalone")),
            "static":_compact_batch(gates.get("model062_static")),
            "static_corpus": {
                "status": (gates.get("model062_static_corpus") or {}).get("status"),
                "asset_count": (gates.get("model062_static_corpus") or {}).get("asset_count"),
                "failure_count": (gates.get("model062_static_corpus") or {}).get("failure_count"),
                "pass_domains": (gates.get("model062_static_corpus") or {}).get("pass_domains"),
            },
            "stage072_corpus": {
                "physical": (gates.get("stage072_physical_corpus") or {}).get("status"),
                "full_parse_pass_files": (gates.get("stage072_physical_corpus") or {}).get("full_parse_pass_files"),
                "stagearea": (gates.get("stage072_stagearea_corpus") or {}).get("status"),
                "normals": (gates.get("stage072_normals_corpus") or {}).get("status"),
                "textures": (gates.get("stage072_texture_corpus") or {}).get("status"),
            },
            "stage072":_compact_batch(gates.get("stage072")),
            "stage072_materials":_compact_batch(gates.get("stage072_materials")),
            "animation_pose_space":_compact_batch(gates.get("animation_pose_space")),
            "smb_animation_corpus": {
                "status": (gates.get("smb_animation_corpus") or {}).get("status"),
                "smb_file_count": (gates.get("smb_animation_corpus") or {}).get("smb_file_count"),
                "animated_smb_file_count": (gates.get("smb_animation_corpus") or {}).get("animated_smb_file_count"),
                "by_domain": (gates.get("smb_animation_corpus") or {}).get("by_domain"),
            },
            "standalone_animation_pose_space":_compact_batch(gates.get("standalone_animation_pose_space")),
            "player_scale_witness": {
                "status": (gates.get("player_scale_witness") or {}).get("status"),
                "asset": (gates.get("player_scale_witness") or {}).get("asset"),
                "skeleton_smb": (gates.get("player_scale_witness") or {}).get("skeleton_smb"),
                "candidate_basis": (gates.get("player_scale_witness") or {}).get("candidate_basis"),
                "selected_container": (gates.get("player_scale_witness") or {}).get("selected_container"),
                "scale_active_sample_count": (gates.get("player_scale_witness") or {}).get("scale_active_sample_count"),
                "track_key_counts": (gates.get("player_scale_witness") or {}).get("track_key_counts"),
                "witness_track_counts": (gates.get("player_scale_witness") or {}).get("witness_track_counts"),
                "max_abs_matrix_error": (gates.get("player_scale_witness") or {}).get("max_abs_matrix_error"),
                "report": (gates.get("player_scale_witness") or {}).get("report"),
            },
            "model062_materials":_compact_batch(gates.get("model062_materials")),
            "model062_material_corpus": {
                "status": (gates.get("model062_material_corpus") or {}).get("status"),
                "asset_count": (gates.get("model062_material_corpus") or {}).get("asset_count"),
                "failure_count": (gates.get("model062_material_corpus") or {}).get("failure_count"),
                "pass_domains": (gates.get("model062_material_corpus") or {}).get("pass_domains"),
                "writer_pass_domains": sorted(material_pass_domains),
                "family_coverage": material_family_coverage,
            },
            "model062_texture_presence": {
                "status": (gates.get("model062_texture_presence") or {}).get("status"),
                "model062_asset_count": (gates.get("model062_texture_presence") or {}).get("model062_asset_count"),
                "required_texture_reference_count": (gates.get("model062_texture_presence") or {}).get("required_texture_reference_count"),
                "failure_count": (gates.get("model062_texture_presence") or {}).get("failure_count"),
                "pass_domains": (gates.get("model062_texture_presence") or {}).get("pass_domains"),
                "audit_status": (gates.get("model062_texture_presence") or {}).get("audit_status"),
                "audit_complete_domains": (gates.get("model062_texture_presence") or {}).get("audit_complete_domains"),
                "target_content_status": (gates.get("model062_texture_presence") or {}).get("target_content_status"),
            },
            "object_local":_compact_batch(gates.get("object_local_blender")),
            "object_local_physical_corpus": {
                "status": (gates.get("object_local_physical_corpus") or {}).get("status"),
                "complete_candidate": (gates.get("object_local_physical_corpus") or {}).get("object_local_complete_candidate"),
                "segmented_tmframe_files": (gates.get("object_local_physical_corpus") or {}).get("segmented_tmframe_files"),
            },
            "multilayer_texlink":_compact_batch(gates.get("multilayer_texlink_blender")),
            "texture_codecs":{
                "status":gates["proprietary_texture_codecs"].get("status"),
                "pass_count":gates["proprietary_texture_codecs"].get("pass_count"),
                "failure_count":gates["proprietary_texture_codecs"].get("failure_count"),
                "pass_domains":gates["proprietary_texture_codecs"].get("pass_domains"),
                "domain_summary":gates["proprietary_texture_codecs"].get("domain_summary"),
                "corpus_capability_status":(gates.get("proprietary_texture_corpus") or {}).get("capability_status"),
                "corpus_target_content_status":(gates.get("proprietary_texture_corpus") or {}).get("target_content_status"),
                "corpus_codec_failure_count":(gates.get("proprietary_texture_corpus") or {}).get("codec_failure_count"),
                "corpus_target_content_invalid_count":(gates.get("proprietary_texture_corpus") or {}).get("target_content_invalid_count"),
            },
            "inx_semantic":{"status":gates["motion_semantic_edit"].get("status"),"audited_contexts":gates["motion_semantic_edit"].get("audited_contexts")},
            "mixed_physique_count":mixed_count,
            "mixed_synthetic": {
                "status": (gates.get("model062_mixed_synthetic") or {}).get("status"),
                "real_corpus_certified": (gates.get("model062_mixed_synthetic") or {}).get("real_corpus_certified"),
            },
            "mixed_physical": {
                "status": mixed_physical.get("status"),
                "requested": mixed_physical.get("requested"),
                "passed": mixed_physical.get("passed"),
                "physical_mixed_certified": mixed_physical_certified,
                "failed": mixed_physical.get("failed"),
            },
            "object_local_physical_by_domain": object_local_physical_by_domain,
            "object_local_selected_by_domain": object_local_selected_by_domain,
            "object_local_feature_coverage": object_local_feature_coverage,
            "multilayer_physical_by_domain": multilayer_physical_by_domain,
            "multilayer_selected_by_domain": texlink_selected_by_domain,
            "multilayer_profile_coverage": multilayer_profile_coverage,
            "animated_smb_physical_by_domain": animated_smb_by_domain,
            "standalone_animation_selected_by_domain": standalone_animation_selected_by_domain,
            "animation_track_required_by_domain": animation_track_required_by_domain,
            "animation_track_witness_by_domain": animation_track_witness_by_domain,
        },
        "blockers":blockers,"coverage":coverage,"gates":gates,
        "mixed_physique_release_scope": mixed_release_scope,
        "manual_review_required_now": bool(automatic_status == "PASS"),
        "external_input_required": False,
        "external_input_request": None,
        "external_gates_pending": (["WRITER_PROMOTION_AND_PUBLISH_RESTORE"] if automatic_status == "PASS" else []),
        "runtime_game_acceptance_pending": False,
        "runtime_game_acceptance_scope": "OUT_OF_SCOPE_PT_ASSET_TOOL_1_0",
        "production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
    out=root/"pt_build"/"devtest"/"release_1_auto"/"result.json"
    out.parent.mkdir(parents=True,exist_ok=True); result["report"]=str(out)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    _progress(f"END status={overall} automatic_gate_status={automatic_status} report={out}")
    return result
