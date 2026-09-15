from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_cross_object_production import POLICY_REL as CROSS_POLICY_REL, load_and_validate_cross_policy
from .rare_rigid_edit import prepare_at_dragon_edit_workspace, _reimport_and_check, write_at_dragon_edit_workspace
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_multibone_extent_probe import (
    TARGET_KINDS,
    _compare,
    _evaluate,
    _patch,
    _world_positions,
    discover_witnesses,
)
from .rare_rigid_normal_bridge import _build_source_normal_state
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_rigid_geometry import _parse_skeleton_tms
from .rare_support import prepare_model062_tooling_source
from .utils import run_logged, sha256_file

RELEASE_VERSION = '0.8.32'
FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_SAVED_BLENDER_CANDIDATE_AUDIT_V1'
PRIOR_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_probe_workflow_v0831.json')


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(pathlib.Path(root) / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(cert: CertificationRegistry) -> str:
    return _sha256(cert.path) if cert.path.is_file() else hashlib.sha256(b'').hexdigest()


def _strict_prior_v0831(root: pathlib.Path) -> dict[str, Any]:
    p = pathlib.Path(root) / PRIOR_REL
    if not p.is_file():
        raise RuntimeError(f'PRIOR_V0831_REPORT_MISSING:{p}')
    d = _json(p)
    rows = list(d.get('rows') or [])
    by_kind = {str(r.get('target_bound_kind')): r for r in rows if r.get('status') == 'PASS'}
    checks = [
        d.get('format') == 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_PROBE_AUDIT_V1',
        d.get('status') == 'PASS',
        d.get('release_version') == '0.8.31',
        d.get('logical') == TARGET,
        int(d.get('probe_witness_count', -1)) == 5,
        set(d.get('discovered_target_kinds') or []) == set(TARGET_KINDS),
        set(by_kind) == set(TARGET_KINDS),
        d.get('production_extent_still_blocked') is True,
        d.get('multibone_outward_extent_write_authorized') is False,
        d.get('extent_contraction_write_authorized') is False,
        d.get('topology_write_authorized') is False,
        d.get('real_certification_registry_modified') is False,
        d.get('cross_object_production_policy_modified') is False,
        d.get('writer_modules_modified') is False,
        d.get('client_modified') is False,
        d.get('writer_hashes') == EXPECTED_WRITER_HASHES,
    ]
    if not all(checks):
        raise RuntimeError('PRIOR_V0831_REPORT_NOT_STRICT_PASS')
    for kind in TARGET_KINDS:
        row = by_kind[kind]
        if not row.get('all_non_authorized_bytes_byte_identical'):
            raise RuntimeError(f'PRIOR_V0831_BYTES_NOT_EXACT:{kind}')
        if not row.get('bound_window_non_field_bytes_byte_identical'):
            raise RuntimeError(f'PRIOR_V0831_BOUND_WINDOW_NOT_EXACT:{kind}')
        if row.get('witness_check') != 'PASS':
            raise RuntimeError(f'PRIOR_V0831_WITNESS_NOT_PASS:{kind}')
        if not row.get('output_sha256'):
            raise RuntimeError(f'PRIOR_V0831_OUTPUT_SHA_MISSING:{kind}')
    d['_rows_by_kind'] = by_kind
    return d


def _apply_saved_blender_one(
    *, settings: Settings, root: pathlib.Path, base_blend: pathlib.Path,
    plan: dict[str, Any], out_blend: pathlib.Path, work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    out_blend.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_blend, out_blend)
    apply_plan = {
        'object_index': int(plan['object_index']),
        'vertex_index': int(plan['vertex_index']),
        'before_world_fixed': [int(x) for x in plan['before_world_fixed']],
        'requested_after_world_fixed': [int(x) for x in plan['requested_after_world_fixed']],
    }
    plan_path = work / 'saved_blender_apply_plan.json'
    report_path = work / 'saved_blender_apply_report.json'
    plan_path.write_text(json.dumps(apply_plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    script = root / 'pt_asset_tool/blender/apply_rare_rigid_artist_witness.py'
    run_logged(settings.blender_command() + [
        '--background', str(out_blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--plan', str(plan_path), '--report', str(report_path),
    ], work / '01_apply_saved_extent.log')
    r = _json(report_path)
    if r.get('check') != 'PASS':
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_APPLY_FAILED:{r}')
    raw = str(r.get('saved_mode'))
    semantic = 'EDIT_MESH' if raw == 'EDIT' else raw
    if semantic != 'EDIT_MESH':
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_NOT_EDIT_MESH:{raw}')
    return {**r, 'saved_mode_raw': raw, 'saved_mode': semantic}


def _extract_saved_change(
    *, settings: Settings, root: pathlib.Path, blend: pathlib.Path,
    baseline: pathlib.Path, report: pathlib.Path, log: pathlib.Path,
) -> dict[str, Any]:
    script = root / 'pt_asset_tool/blender/extract_rare_rigid_edit.py'
    run_logged(settings.blender_command() + [
        '--background', str(blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--baseline', str(baseline), '--report', str(report), '--max-changed', '1',
    ], log)
    r = _json(report)
    if r.get('check') != 'PASS':
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_EXTRACTION_FAILED:{r}')
    changed = list(r.get('changed_vertices') or [])
    if len(changed) != 1:
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_REQUIRES_EXACTLY_ONE_CHANGE:{len(changed)}')
    if r.get('writer_input_mode_before') != 'EDIT_MESH':
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_INPUT_MODE_NOT_EDIT_MESH:{r.get("writer_input_mode_before")}')
    if r.get('writer_input_mode_after') != 'OBJECT':
        raise RuntimeError('SAVED_BLENDER_EXTENT_NOT_CANONICALIZED_TO_OBJECT')
    if not r.get('non_position_semantic_state_pass'):
        raise RuntimeError('SAVED_BLENDER_EXTENT_SEMANTIC_STATE_FAILED')
    if float(r.get('max_uv_state_delta', 1.0)) != 0.0:
        raise RuntimeError('SAVED_BLENDER_EXTENT_UV_DELTA_NONZERO')
    if float(r.get('max_physique_weight_delta', 1.0)) != 0.0:
        raise RuntimeError('SAVED_BLENDER_EXTENT_PHYSIQUE_DELTA_NONZERO')
    return r


def _rederive_saved_plan(
    prepared: pathlib.Path, skeleton: pathlib.Path, change: dict[str, Any], target_kind: str,
) -> dict[str, Any]:
    model = _parse_with_offsets(prepared)
    oi = int(change['object_index']); vi = int(change['vertex_index'])
    if oi < 0 or oi >= len(model['objects']):
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_OBJECT_OUT_OF_RANGE:{oi}')
    obj = model['objects'][oi]
    bone_tms = _parse_skeleton_tms(skeleton)
    world = _world_positions(obj, bone_tms)
    if vi < 0 or vi >= len(world):
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_VERTEX_OUT_OF_RANGE:{oi}:{vi}')
    before = tuple(int(x) for x in change['before_world_fixed'])
    after = tuple(int(x) for x in change['after_world_fixed'])
    if before != tuple(world[vi]):
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_BASELINE_MISMATCH:{oi}:{vi}')
    state = _build_source_normal_state(world, obj['faces'])
    plan = _evaluate(obj, bone_tms, world, state, vi, after, target_kind)
    if plan is None or plan.get('guard_status') != 'PASS':
        raise RuntimeError(f'SAVED_BLENDER_EXTENT_PLAN_REDERIVATION_FAILED:{target_kind}:{oi}:{vi}')
    return plan


def _production_extent_negative(
    *, reg: AssetRegistry, resolver: ClientResolver, certifications: CertificationRegistry,
    settings: Settings, root: pathlib.Path, workspace: pathlib.Path,
    edit_blend: pathlib.Path, output: pathlib.Path,
) -> tuple[bool, str]:
    manifest_path = workspace / 'workspace_manifest.json'
    original_text = manifest_path.read_text(encoding='utf-8')
    manifest = json.loads(original_text)
    manifest['edit_blend'] = str(edit_blend)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output.unlink(missing_ok=True)
    err = ''
    try:
        write_at_dragon_edit_workspace(
            reg, resolver, certifications, settings,
            project_root=root, output=output, workspace_root=workspace,
        )
    except Exception as exc:
        err = f'{type(exc).__name__}:{exc}'
    finally:
        manifest_path.write_text(original_text, encoding='utf-8')
    blocked = 'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' in err and not output.exists()
    return blocked, err


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve(); output = pathlib.Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)

    prior = _strict_prior_v0831(root); prior_rows = prior['_rows_by_kind']
    cross_policy = load_and_validate_cross_policy(root)
    cross_path = root / CROSS_POLICY_REL; single_path = root / SINGLE_POLICY_REL
    cross_sha_before = _sha256(cross_path); single_sha_before = _sha256(single_path)
    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0832')

    settings = Settings.discover(root, None); resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records()); real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True)); source_sha_before = _sha256(source)
    if source_sha_before != prior.get('client_source_sha256') or source_sha_before != cross_policy.get('client_source_sha256'):
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_PRIOR_EVIDENCE')

    isolated_cert = CertificationRegistry(work / 'isolated_preview_certifications')
    workspace = work / 'isolated_workspace'
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings, project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin='AUDIT_V0832_SAVED_BLENDER_MULTIBONE_OUTWARD_EXTENT',
    )
    prepared = pathlib.Path(manifest['prepared_source']); skeleton = pathlib.Path(manifest['skeleton'])
    baseline = pathlib.Path(manifest['baseline_blender_report']); base_blend = pathlib.Path(manifest['edit_blend'])
    discovery = discover_witnesses(prepared, skeleton); found = discovery['found']
    if set(found) != set(TARGET_KINDS):
        raise RuntimeError(f'V0832_WITNESS_SET_INCOMPLETE:{sorted(found)}')

    preview = _json(workspace / 'base_preview' / 'summary.json')
    bone_tms = _parse_skeleton_tms(skeleton)
    rows = []; saved_blends: dict[str, pathlib.Path] = {}
    isolated_count_after_preview = len(isolated_cert.records())

    for kind in TARGET_KINDS:
        prior_row = prior_rows[kind]; setup_plan = found[kind]
        if int(setup_plan['object_index']) != int(prior_row['object_index']) or int(setup_plan['vertex_index']) != int(prior_row['vertex_index']):
            raise RuntimeError(f'V0832_WITNESS_IDENTITY_DIVERGED:{kind}')
        case = work / f'extent_{kind}'; case.mkdir(parents=True, exist_ok=True)
        edit_blend = case / f'at_dragon_extent_{kind}_saved.blend'; saved_blends[kind] = edit_blend
        apply = _apply_saved_blender_one(settings=settings, root=root, base_blend=base_blend, plan=setup_plan, out_blend=edit_blend, work=case / 'apply')
        extraction = _extract_saved_change(
            settings=settings, root=root, blend=edit_blend, baseline=baseline,
            report=case / 'extract.json', log=case / '02_extract_saved_extent.log',
        )
        ch = list(extraction['changed_vertices'])[0]
        if int(ch['object_index']) != int(setup_plan['object_index']) or int(ch['vertex_index']) != int(setup_plan['vertex_index']):
            raise RuntimeError(f'SAVED_BLENDER_EXTENT_IDENTITY_MISMATCH:{kind}')
        if [int(x) for x in ch['after_world_fixed']] != [int(x) for x in setup_plan['requested_after_world_fixed']]:
            raise RuntimeError(f'SAVED_BLENDER_EXTENT_POSITION_MISMATCH:{kind}')
        plan = _rederive_saved_plan(prepared, skeleton, ch, kind)
        staging = case / 'candidate_extent.smd.staging'; final = case / 'candidate_extent.smd'
        patch = _patch(source, prepared, staging, plan)
        prepared_output = case / 'prepared_output' / pathlib.PurePosixPath(TARGET)
        prepare_model062_tooling_source(staging, prepared_output)
        binary = _compare(source, staging, prepared_output, plan, patch, bone_tms)
        validation = _reimport_and_check(
            reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
            project_root=root, preview=preview, skeleton=skeleton, prepared_output=prepared_output,
            plan=plan, work=case / 'validation',
        )
        staging.replace(final)
        final_sha = _sha256(final)
        if final_sha != str(prior_row['output_sha256']):
            raise RuntimeError(f'V0832_BINARY_NOT_EQUIVALENT_TO_V0831:{kind}:{final_sha}!={prior_row["output_sha256"]}')
        rows.append({
            'status': 'PASS', 'target_bound_kind': kind,
            'object_index': int(plan['object_index']), 'vertex_index': int(plan['vertex_index']),
            'affected_bone_count': int(plan['affected_bone_count']), 'affected_bones': list(plan['affected_bones']),
            'saved_blender_apply_pass': apply.get('check') == 'PASS',
            'saved_blender_saved_mode_raw': apply.get('saved_mode_raw'), 'saved_blender_saved_mode': apply.get('saved_mode'),
            'saved_blender_input_mode_before': extraction.get('writer_input_mode_before'),
            'saved_blender_input_mode_after': extraction.get('writer_input_mode_after'),
            'writer_input_object_mode_canonicalized': extraction.get('writer_input_object_mode_canonicalized'),
            'non_position_semantic_state_pass': extraction.get('non_position_semantic_state_pass'),
            'max_uv_state_delta': extraction.get('max_uv_state_delta'), 'max_physique_weight_delta': extraction.get('max_physique_weight_delta'),
            'stored_bounds_before': plan['stored_bounds_before'], 'stored_bounds_after': plan['stored_bounds_after'],
            'changed_bound_fields': list(plan['changed_bound_fields']),
            'all_non_authorized_bytes_byte_identical': bool(binary['all_non_authorized_bytes_byte_identical']),
            'bound_window_non_field_bytes_byte_identical': bool(binary['bound_window_non_field_bytes_byte_identical']),
            'transport_position_error': float(validation['transport'].get('max_position_error', validation['transport'].get('position_error', 0.0)) or 0.0),
            'transport_uv_error': float(validation['transport'].get('max_uv_error', validation['transport'].get('uv_error', 0.0)) or 0.0),
            'witness_check': validation['witness'].get('check'), 'atomic_candidate_publish': True,
            'candidate_only': True, 'certification_written': False,
            'output_smd': str(final), 'output_sha256': final_sha, 'matches_v0831_output_sha256': True,
        })

    # Exact production writer must still reject the physically saved extent edit.
    prod_out = work / 'production_negative_should_not_exist.smd'
    prod_cert_before = len(isolated_cert.records())
    production_blocked, production_error = _production_extent_negative(
        reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings, root=root,
        workspace=workspace, edit_blend=saved_blends['maxX'], output=prod_out,
    )
    if not production_blocked:
        raise RuntimeError(f'PRODUCTION_EXTENT_NEGATIVE_FAILED:{production_error}:output={prod_out.exists()}')
    if len(isolated_cert.records()) != prod_cert_before:
        raise RuntimeError('PRODUCTION_EXTENT_NEGATIVE_WROTE_CERTIFICATION')

    real_count_after = len(real_cert.records()); real_sha_after = _cert_sha(real_cert)
    source_sha_after = _sha256(source); cross_sha_after = _sha256(cross_path); single_sha_after = _sha256(single_path)
    writers_after = _writer_hashes(root)
    if real_count_after != real_count_before or real_sha_after != real_sha_before:
        raise RuntimeError('REAL_CERTIFICATION_REGISTRY_MODIFIED')
    if source_sha_after != source_sha_before:
        raise RuntimeError('CLIENT_SOURCE_MODIFIED')
    if cross_sha_after != cross_sha_before or single_sha_after != single_sha_before:
        raise RuntimeError('PRODUCTION_POLICY_MODIFIED')
    if writers_after != writers_before:
        raise RuntimeError('CERTIFIED_WRITERS_MODIFIED')

    report = {
        'format': FORMAT, 'status': 'PASS', 'release_version': RELEASE_VERSION, 'logical': TARGET,
        'prior_v0831_strict_pass': True, 'prior_v0831_witness_count': 5,
        'candidate_target_kinds': list(TARGET_KINDS), 'candidate_witness_count': len(rows),
        'all_candidate_rows_pass': all(r['status'] == 'PASS' for r in rows), 'rows': rows,
        'all_saved_blender_outputs_match_v0831': all(r['matches_v0831_output_sha256'] for r in rows),
        'production_extent_still_blocked': True, 'production_extent_error': production_error,
        'production_extent_output_created': prod_out.exists(),
        'isolated_preview_certification_count': isolated_count_after_preview,
        'isolated_candidate_certification_count_after': len(isolated_cert.records()),
        'candidate_certification_written': False,
        'real_certification_count_before': real_count_before, 'real_certification_count_after': real_count_after,
        'real_certification_registry_sha256_before': real_sha_before, 'real_certification_registry_sha256_after': real_sha_after,
        'real_certification_registry_modified': False,
        'single_object_production_policy_modified': False, 'cross_object_production_policy_modified': False,
        'writer_modules_modified': False, 'client_source_sha256_before': source_sha_before,
        'client_source_sha256_after': source_sha_after, 'client_modified': False,
        'multibone_outward_extent_live_write_authorized': False,
        'extent_contraction_write_authorized': False, 'topology_write_authorized': False,
        'writer_hashes': writers_after,
        'policy': {
            'scope': 'isolated saved-Blender at_dragon multi-bone outward extent candidate for the five V0.8.31 physical witness classes; exactly one changed vertex in one mesh object per case',
            'saved_blender': 'each witness is physically persisted in Blender EDIT_MESH, then the standard production extractor canonicalizes to OBJECT and independently reports the actual saved fixed-point position',
            'rederivation': 'the extent/normal/bound plan is recomputed from the extracted saved position and final geometry before any binary candidate is built',
            'binary_equivalence': 'each saved-Blender candidate output must be SHA-256 identical to its corresponding V0.8.31 physical probe output',
            'production_control': 'the exact existing production writer must continue rejecting the same saved extent blend with EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED and create no output/certification',
            'authorization': 'PASS is saved-Blender extent candidate evidence only; no production extent authorization is added',
            'next_on_pass': 'build V0.8.33 isolated live-writer multi-bone outward extent candidate before manual artist proof or production promotion',
            'deferred': 'extent production writes, contraction, topology, multi-vertex extent composition and cross-object extent remain fail-closed',
        },
        'next': 'isolated live-writer multi-bone outward extent candidate if this saved-Blender gate passes',
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.32 saved-Blender multi-bone outward extent candidate')
    ap.add_argument('--root', required=True); ap.add_argument('--output', required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).resolve(); out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = run(pathlib.Path(ns.root), out)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"rare_rigid_multibone_outward_extent_saved_blender=PASS witnesses={r['candidate_witness_count']} extent_authorized=false client_modified=false")
        return 0
    except Exception as exc:
        r = {
            'format': FORMAT, 'status': 'FAIL', 'release_version': RELEASE_VERSION, 'logical': TARGET,
            'error': f'{type(exc).__name__}:{exc}', 'multibone_outward_extent_live_write_authorized': False,
        }
        out.write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print('rare_rigid_multibone_outward_extent_saved_blender=FAIL')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
