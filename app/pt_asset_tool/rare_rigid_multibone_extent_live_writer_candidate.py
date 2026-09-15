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
from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_cross_object_production import (
    POLICY_REL as CROSS_POLICY_REL,
    load_and_validate_cross_policy,
)
from .rare_rigid_cross_object_saved_blender_candidate import _apply_saved_blender
from .rare_rigid_edit import (
    WORKSPACE_FORMAT,
    _at_dragon_binding,
    _reimport_and_check,
    prepare_at_dragon_edit_workspace,
)
from .rare_rigid_extent_bridge import _bound_changes, _expanded_bounds
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL, load_and_validate_policy
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
from .rare_rigid_multibone_extent_saved_blender_candidate import (
    _apply_saved_blender_one,
    _extract_saved_change,
    _production_extent_negative,
)
from .rare_rigid_normal_bridge import _build_source_normal_state
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_rigid_geometry import _parse_skeleton_tms
from .rare_support import prepare_model062_tooling_source
from .utils import run_logged, sha256_file

RELEASE_VERSION = '0.8.33'
FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_AUDIT_V1'
WRITE_FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_WRITE_V1'
PRIOR_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_saved_blender_workflow_v0832.json')
CANDIDATE_TEST = 'RARE_RIGID_ARTIST_GUARDED_MULTIBONE_OUTWARD_EXTENT_WRITE_CANDIDATE'
CANDIDATE_SCOPE = 'AT_DRAGON_ONE_VERTEX_ONE_OBJECT_MULTIBONE_OUTWARD_EXTENT_MONOTONIC_BOUND_EXPANSION_CANDIDATE_ONLY'

# The candidate is intentionally narrower than a general extent writer.  These
# are the exact changed-bound field shapes physically proven in V0.8.31/V0.8.32.
EXACT_BOUND_FIELD_SHAPES = {
    frozenset({'maxX'}): 'maxX',
    frozenset({'maxZ'}): 'maxZ',
    frozenset({'maxY'}): 'maxY',
    frozenset({'dBound'}): 'dBound',
    frozenset({'maxY', 'dBound', 'Bound'}): 'Bound',
}


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


def _cert_sha(reg: CertificationRegistry) -> str:
    return _sha256(reg.path) if reg.path.is_file() else hashlib.sha256(b'').hexdigest()


def _asset_id(reg: AssetRegistry) -> str:
    try:
        aid = str(getattr(reg.resolve(TARGET), 'asset_id', '') or '')
    except Exception:
        aid = ''
    return aid or ('RARE::' + TARGET)


def _strict_prior_v0832(root: pathlib.Path) -> dict[str, Any]:
    p = pathlib.Path(root) / PRIOR_REL
    if not p.is_file():
        raise RuntimeError(f'PRIOR_V0832_REPORT_MISSING:{p}')
    d = _json(p)
    rows = list(d.get('rows') or [])
    by_kind = {str(r.get('target_bound_kind')): r for r in rows if r.get('status') == 'PASS'}
    checks = [
        d.get('format') == 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_SAVED_BLENDER_CANDIDATE_AUDIT_V1',
        d.get('status') == 'PASS',
        d.get('release_version') == '0.8.32',
        d.get('logical') == TARGET,
        d.get('prior_v0831_strict_pass') is True,
        int(d.get('prior_v0831_witness_count', -1)) == 5,
        set(d.get('candidate_target_kinds') or []) == set(TARGET_KINDS),
        int(d.get('candidate_witness_count', -1)) == 5,
        d.get('all_candidate_rows_pass') is True,
        set(by_kind) == set(TARGET_KINDS),
        d.get('all_saved_blender_outputs_match_v0831') is True,
        d.get('production_extent_still_blocked') is True,
        d.get('production_extent_output_created') is False,
        d.get('candidate_certification_written') is False,
        d.get('real_certification_registry_modified') is False,
        d.get('single_object_production_policy_modified') is False,
        d.get('cross_object_production_policy_modified') is False,
        d.get('writer_modules_modified') is False,
        d.get('client_modified') is False,
        d.get('multibone_outward_extent_live_write_authorized') is False,
        d.get('extent_contraction_write_authorized') is False,
        d.get('topology_write_authorized') is False,
        d.get('writer_hashes') == EXPECTED_WRITER_HASHES,
    ]
    if not all(checks):
        raise RuntimeError('PRIOR_V0832_REPORT_NOT_STRICT_PASS')
    for kind in TARGET_KINDS:
        row = by_kind[kind]
        row_checks = [
            row.get('saved_blender_apply_pass') is True,
            row.get('saved_blender_saved_mode') == 'EDIT_MESH',
            row.get('saved_blender_input_mode_before') == 'EDIT_MESH',
            row.get('saved_blender_input_mode_after') == 'OBJECT',
            row.get('writer_input_object_mode_canonicalized') is True,
            row.get('non_position_semantic_state_pass') is True,
            float(row.get('max_uv_state_delta', 1.0)) == 0.0,
            float(row.get('max_physique_weight_delta', 1.0)) == 0.0,
            row.get('all_non_authorized_bytes_byte_identical') is True,
            row.get('bound_window_non_field_bytes_byte_identical') is True,
            row.get('witness_check') == 'PASS',
            row.get('atomic_candidate_publish') is True,
            row.get('candidate_only') is True,
            row.get('certification_written') is False,
            row.get('matches_v0831_output_sha256') is True,
            bool(row.get('output_sha256')),
        ]
        if not all(row_checks):
            raise RuntimeError(f'PRIOR_V0832_ROW_NOT_STRICT_PASS:{kind}')
    d['_rows_by_kind'] = by_kind
    return d


def _classify_target_kind(changed_fields: list[str]) -> str:
    key = frozenset(str(x) for x in changed_fields)
    kind = EXACT_BOUND_FIELD_SHAPES.get(key)
    if kind is None:
        if not key:
            raise RuntimeError('MULTIBONE_EXTENT_LIVE_REQUIRES_OUTWARD_BOUND_EXPANSION')
        raise RuntimeError('MULTIBONE_EXTENT_LIVE_BOUND_FIELD_SHAPE_NOT_PROVEN:' + ','.join(sorted(key)))
    return kind


def _plan_from_extraction(prepared: pathlib.Path, skeleton: pathlib.Path, extraction: dict[str, Any]) -> dict[str, Any]:
    changed = list(extraction.get('changed_vertices') or [])
    if len(changed) != 1:
        raise RuntimeError(f'MULTIBONE_EXTENT_LIVE_REQUIRES_EXACTLY_ONE_VERTEX:{len(changed)}')
    ch = changed[0]
    model = _parse_with_offsets(prepared)
    oi = int(ch['object_index'])
    vi = int(ch['vertex_index'])
    if oi < 0 or oi >= len(model['objects']):
        raise RuntimeError(f'MULTIBONE_EXTENT_LIVE_OBJECT_OUT_OF_RANGE:{oi}')
    obj = model['objects'][oi]
    bone_tms = _parse_skeleton_tms(skeleton)
    world = _world_positions(obj, bone_tms)
    if vi < 0 or vi >= len(world):
        raise RuntimeError(f'MULTIBONE_EXTENT_LIVE_VERTEX_OUT_OF_RANGE:{oi}:{vi}')
    before = tuple(int(x) for x in ch['before_world_fixed'])
    after = tuple(int(x) for x in ch['after_world_fixed'])
    if before != tuple(world[vi]):
        raise RuntimeError(f'MULTIBONE_EXTENT_LIVE_BASELINE_MISMATCH:{oi}:{vi}')
    stored = {k: int(v) for k, v in obj['stored_bounds'].items()}
    expanded = _expanded_bounds(stored, after)
    changed_fields = _bound_changes(stored, expanded)
    target_kind = _classify_target_kind(changed_fields)
    state = _build_source_normal_state(world, obj['faces'])
    plan = _evaluate(obj, bone_tms, world, state, vi, after, target_kind)
    if plan is None or plan.get('guard_status') != 'PASS':
        raise RuntimeError(f'MULTIBONE_EXTENT_LIVE_PLAN_REDERIVATION_FAILED:{target_kind}:{oi}:{vi}')
    if set(plan.get('changed_bound_fields') or []) != set(changed_fields):
        raise RuntimeError('MULTIBONE_EXTENT_LIVE_BOUND_REDERIVATION_MISMATCH')
    if int(plan.get('affected_bone_count', 0)) < 2:
        raise RuntimeError('MULTIBONE_EXTENT_LIVE_REQUIRES_MULTIBONE_AFFECTED_NORMALS')
    return plan


def write_at_dragon_multibone_outward_extent_candidate_workspace(
    reg: AssetRegistry,
    resolver: ClientResolver,
    certifications: CertificationRegistry,
    settings: Settings,
    *,
    project_root: pathlib.Path,
    workspace_root: pathlib.Path,
    output: pathlib.Path,
) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    work = pathlib.Path(workspace_root).resolve()
    manifest_path = work / 'workspace_manifest.json'
    if not manifest_path.is_file():
        raise RuntimeError(f'MULTIBONE_EXTENT_CANDIDATE_WORKSPACE_MANIFEST_MISSING:{manifest_path}')
    manifest = _json(manifest_path)
    if manifest.get('format') != WORKSPACE_FORMAT or manifest.get('logical') != TARGET:
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_WORKSPACE_MANIFEST_MISMATCH')

    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if sha256_file(source) != manifest.get('source_sha256'):
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_PHYSICAL_SOURCE_CHANGED')
    skeleton = pathlib.Path(resolver.resolve(manifest['motion_smb'], required=True))
    if sha256_file(skeleton) != manifest.get('skeleton_sha256'):
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_SKELETON_CHANGED')
    prepared = pathlib.Path(manifest['prepared_source'])
    if not prepared.is_file() or sha256_file(prepared) != manifest.get('prepared_source_sha256'):
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_PREPARED_SOURCE_CHANGED')

    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=project_root,
        work=work / ('multibone_extent_live_binding_recheck_' + pathlib.Path(output).stem), bundle=None,
    )
    if binding.get('status') != 'PASS':
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_BINDING_RECHECK_FAILED')
    _at_dragon_binding(binding)

    edit_blend = pathlib.Path(manifest['edit_blend'])
    if not edit_blend.is_file():
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_SAVED_BLEND_MISSING')
    preview_path = work / 'base_preview' / 'summary.json'
    if not preview_path.is_file():
        raise RuntimeError('MULTIBONE_EXTENT_CANDIDATE_PREVIEW_SUMMARY_MISSING')
    preview = _json(preview_path)

    write_work = work / ('multibone_extent_live_candidate_' + pathlib.Path(output).stem)
    if write_work.exists():
        shutil.rmtree(write_work)
    write_work.mkdir(parents=True)
    extraction = _extract_saved_change(
        settings=settings, root=project_root, blend=edit_blend,
        baseline=pathlib.Path(manifest['baseline_blender_report']),
        report=write_work / 'artist_edit_extract.json', log=write_work / '01_extract_artist_extent.log',
    )
    plan = _plan_from_extraction(prepared, skeleton, extraction)

    final_output = pathlib.Path(output).resolve()
    final_output.parent.mkdir(parents=True, exist_ok=True)
    final_output.unlink(missing_ok=True)
    staging = final_output.with_name(final_output.name + '.v0833_staging')
    staging.unlink(missing_ok=True)
    try:
        patch = _patch(source, prepared, staging, plan)
        prepared_output = write_work / 'prepared_output' / pathlib.PurePosixPath(TARGET)
        prepare_model062_tooling_source(staging, prepared_output)
        bone_tms = _parse_skeleton_tms(skeleton)
        binary = _compare(source, staging, prepared_output, plan, patch, bone_tms)
        validation = _reimport_and_check(
            reg=reg, resolver=resolver, certifications=certifications, settings=settings,
            project_root=project_root, preview=preview, skeleton=skeleton,
            prepared_output=prepared_output, plan=plan, work=write_work / 'write_validation',
        )
        staging.replace(final_output)
    except Exception:
        staging.unlink(missing_ok=True)
        final_output.unlink(missing_ok=True)
        raise

    cert = certifications.add(
        asset_id=_asset_id(reg), asset_path=TARGET,
        family='MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT',
        test=CANDIDATE_TEST, layer='AUTOMATIC', result='PASS',
        source_sha256=sha256_file(source), artifact_sha256=sha256_file(final_output),
        notes='V0.8.33 isolated multi-bone outward extent live-writer candidate only; not production authorization.',
        metadata={
            'write_scope': CANDIDATE_SCOPE,
            'candidate_only': True,
            'production_authorized': False,
            'object_index': int(plan['object_index']),
            'vertex_index': int(plan['vertex_index']),
            'target_bound_kind': str(plan['target_bound_kind']),
            'changed_bound_fields': list(plan['changed_bound_fields']),
            'affected_bone_count': int(plan['affected_bone_count']),
            'affected_bones': list(plan['affected_bones']),
            'all_non_authorized_bytes_byte_identical': bool(binary['all_non_authorized_bytes_byte_identical']),
            'bound_window_non_field_bytes_byte_identical': bool(binary['bound_window_non_field_bytes_byte_identical']),
            'atomic_output_replace': True,
            'client_modified': False,
        },
    )
    transport = validation['transport']
    return {
        'format': WRITE_FORMAT,
        'status': 'PASS',
        'logical': TARGET,
        'candidate_only': True,
        'production_authorized': False,
        'exact_candidate_writer_function_exercised': 'write_at_dragon_multibone_outward_extent_candidate_workspace',
        'object_index': int(plan['object_index']),
        'vertex_index': int(plan['vertex_index']),
        'artist_changed_vertices': 1,
        'target_bound_kind': str(plan['target_bound_kind']),
        'stored_bounds_before': plan['stored_bounds_before'],
        'stored_bounds_after': plan['stored_bounds_after'],
        'changed_bound_fields': list(plan['changed_bound_fields']),
        'affected_bone_count': int(plan['affected_bone_count']),
        'affected_bones': list(plan['affected_bones']),
        'max_current_source_normal_delta_fixed': int(plan['max_current_source_normal_delta_fixed']),
        'max_target_reimport_normal_error_fixed': int(plan['max_target_reimport_normal_error_fixed']),
        'writer_input_mode_before': extraction.get('writer_input_mode_before'),
        'writer_input_mode_after': extraction.get('writer_input_mode_after'),
        'writer_input_object_mode_canonicalized': extraction.get('writer_input_object_mode_canonicalized'),
        'non_position_semantic_state_pass': extraction.get('non_position_semantic_state_pass'),
        'max_uv_state_delta': extraction.get('max_uv_state_delta'),
        'max_physique_weight_delta': extraction.get('max_physique_weight_delta'),
        'all_non_authorized_bytes_byte_identical': bool(binary['all_non_authorized_bytes_byte_identical']),
        'bound_window_non_field_bytes_byte_identical': bool(binary['bound_window_non_field_bytes_byte_identical']),
        'binary_diff_byte_count': int(binary['diff_byte_count']),
        'transport_position_error': float(transport.get('max_position_error', transport.get('position_error', 0.0)) or 0.0),
        'transport_uv_error': float(transport.get('max_uv_error', transport.get('uv_error', 0.0)) or 0.0),
        'witness_check': validation['witness'].get('check'),
        'transaction_atomic': True,
        'atomic_output_replace': True,
        'output_smd': str(final_output),
        'output_sha256': _sha256(final_output),
        'candidate_certification_id': cert['certification_id'],
        'candidate_certification_test': CANDIDATE_TEST,
        'candidate_write_scope': CANDIDATE_SCOPE,
    }


def _apply_two_vertex_same_object_negative(
    *, settings: Settings, root: pathlib.Path, pristine_blend: pathlib.Path,
    out_blend: pathlib.Path, a: dict[str, Any], b: dict[str, Any], work: pathlib.Path,
) -> dict[str, Any]:
    oi = int(a['object_index'])
    if int(b['object_index']) != oi:
        raise RuntimeError('V0833_TWO_VERTEX_NEGATIVE_REQUIRES_SHARED_OBJECT')
    shutil.copy2(pristine_blend, out_blend)
    plan = {
        'object_index': oi,
        'changed_vertices': [
            {
                'vertex_index': int(p['vertex_index']),
                'before_world_fixed': [int(x) for x in p['before_world_fixed']],
                'requested_after_world_fixed': [int(x) for x in p['requested_after_world_fixed']],
            }
            for p in (a, b)
        ],
    }
    work.mkdir(parents=True, exist_ok=True)
    pp = work / 'two_vertex_extent_negative_plan.json'
    rp = work / 'two_vertex_extent_negative_apply.json'
    pp.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    script = root / 'pt_asset_tool/blender/apply_rare_rigid_transaction_witness.py'
    run_logged(settings.blender_command() + [
        '--background', str(out_blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--plan', str(pp), '--report', str(rp),
    ], work / '01_apply_two_vertex_extent_negative.log')
    r = _json(rp)
    if r.get('check') != 'PASS' or int(r.get('changed_vertex_count', -1)) != 2:
        raise RuntimeError(f'V0833_TWO_VERTEX_NEGATIVE_APPLY_FAILED:{r}')
    return r


def _apply_cross_object_extent_negative(
    *, settings: Settings, root: pathlib.Path, pristine_blend: pathlib.Path,
    out_blend: pathlib.Path, a: dict[str, Any], b: dict[str, Any], work: pathlib.Path,
) -> dict[str, Any]:
    if int(a['object_index']) == int(b['object_index']):
        raise RuntimeError('V0833_CROSS_OBJECT_NEGATIVE_REQUIRES_DIFFERENT_OBJECTS')
    per_object = [
        {
            'object_index': int(p['object_index']),
            'changed_vertices': [{
                'vertex_index': int(p['vertex_index']),
                'before_world_fixed': [int(x) for x in p['before_world_fixed']],
                'requested_after_world_fixed': [int(x) for x in p['requested_after_world_fixed']],
            }],
        }
        for p in (a, b)
    ]
    tx = {
        'object_count': 2,
        'object_indices': sorted(int(p['object_index']) for p in (a, b)),
        'total_changed_vertices': 2,
        'per_object_plans': per_object,
    }
    return _apply_saved_blender(
        root=root, settings=settings, base_blend=pristine_blend,
        transaction=tx, out_blend=out_blend, work=work,
    )


def _candidate_negative(
    *, reg: AssetRegistry, resolver: ClientResolver, certifications: CertificationRegistry,
    settings: Settings, root: pathlib.Path, workspace: pathlib.Path, output: pathlib.Path,
    expected_error: str,
) -> tuple[bool, str]:
    output.unlink(missing_ok=True)
    before = len(certifications.records())
    err = ''
    try:
        write_at_dragon_multibone_outward_extent_candidate_workspace(
            reg, resolver, certifications, settings,
            project_root=root, workspace_root=workspace, output=output,
        )
    except Exception as exc:
        err = f'{type(exc).__name__}:{exc}'
    after = len(certifications.records())
    blocked = expected_error in err and not output.exists() and after == before
    return blocked, err


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    prior = _strict_prior_v0832(root)
    prior_rows = prior['_rows_by_kind']
    single_policy = load_and_validate_policy(root)
    cross_policy = load_and_validate_cross_policy(root)
    single_path = root / SINGLE_POLICY_REL
    cross_path = root / CROSS_POLICY_REL
    single_sha_before = _sha256(single_path)
    cross_sha_before = _sha256(cross_path)
    if int(single_policy.get('production_max_vertices', -1)) != 8:
        raise RuntimeError('V0833_SINGLE_OBJECT_PRODUCTION_POLICY_SCOPE_UNEXPECTED')
    if cross_policy.get('cross_object_production_authorized') is not True:
        raise RuntimeError('V0833_CROSS_OBJECT_PRODUCTION_POLICY_NOT_AUTHORIZED')

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0833')

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records())
    real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    expected_source_sha = str(prior.get('client_source_sha256_before') or prior.get('client_source_sha256_after') or '')
    if expected_source_sha and source_sha_before != expected_source_sha:
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0832_EVIDENCE')
    if source_sha_before != str(single_policy.get('client_source_sha256')) or source_sha_before != str(cross_policy.get('client_source_sha256')):
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_PRODUCTION_POLICIES')

    isolated_cert = CertificationRegistry(work / 'isolated_certifications')
    workspace = work / 'isolated_artist_workspace'
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings, project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin='AUDIT_V0833_LIVE_WRITER_MULTIBONE_OUTWARD_EXTENT_CANDIDATE',
    )
    preview_records = isolated_cert.records()
    if len(preview_records) != 1 or preview_records[0].get('test') != 'RARE_RIGID_BLENDER_PREVIEW':
        raise RuntimeError(f'ISOLATED_PREVIEW_CERT_UNEXPECTED:{preview_records}')

    prepared = pathlib.Path(manifest['prepared_source'])
    skeleton = pathlib.Path(manifest['skeleton'])
    edit_blend = pathlib.Path(manifest['edit_blend'])
    pristine_blend = work / 'pristine_edit_workspace.blend'
    shutil.copy2(edit_blend, pristine_blend)
    discovery = discover_witnesses(prepared, skeleton)
    found = discovery['found']
    if set(found) != set(TARGET_KINDS):
        raise RuntimeError(f'V0833_WITNESS_SET_INCOMPLETE:{sorted(found)}')

    rows = []
    for kind in TARGET_KINDS:
        setup = found[kind]
        prior_row = prior_rows[kind]
        if int(setup['object_index']) != int(prior_row['object_index']) or int(setup['vertex_index']) != int(prior_row['vertex_index']):
            raise RuntimeError(f'V0833_WITNESS_IDENTITY_DIVERGED:{kind}')
        apply = _apply_saved_blender_one(
            settings=settings, root=root, base_blend=pristine_blend, plan=setup,
            out_blend=edit_blend, work=workspace / ('apply_live_extent_' + kind),
        )
        cert_before = len(isolated_cert.records())
        out_smd = work / ('live_' + kind) / ('live_extent_' + kind + '.smd')
        result = write_at_dragon_multibone_outward_extent_candidate_workspace(
            reg, resolver, isolated_cert, settings,
            project_root=root, workspace_root=workspace, output=out_smd,
        )
        cert_after = len(isolated_cert.records())
        if cert_after != cert_before + 1:
            raise RuntimeError(f'V0833_CANDIDATE_CERT_DELTA_NOT_ONE:{kind}:{cert_before}->{cert_after}')
        if result.get('candidate_certification_test') != CANDIDATE_TEST:
            raise RuntimeError(f'V0833_CANDIDATE_CERT_TEST_MISMATCH:{kind}')
        if result.get('target_bound_kind') != kind:
            raise RuntimeError(f'V0833_TARGET_KIND_MISMATCH:{kind}:{result.get("target_bound_kind")}')
        if result.get('output_sha256') != prior_row.get('output_sha256'):
            raise RuntimeError(f'V0833_BINARY_NOT_EQUIVALENT_TO_V0832:{kind}:{result.get("output_sha256")}!={prior_row.get("output_sha256")}')
        rows.append({
            **result,
            'saved_blender_apply_pass': apply.get('check') == 'PASS',
            'saved_blender_saved_mode': apply.get('saved_mode'),
            'matches_v0832_output_sha256': True,
            'isolated_candidate_certification_count_delta': 1,
        })

    # Existing production writer remains a required negative even after all five
    # candidate live writes succeed.
    _apply_saved_blender_one(
        settings=settings, root=root, base_blend=pristine_blend, plan=found['maxX'],
        out_blend=edit_blend, work=workspace / 'apply_production_extent_negative',
    )
    prod_out = work / 'production_extent_should_not_exist.smd'
    prod_cert_before = len(isolated_cert.records())
    production_blocked, production_error = _production_extent_negative(
        reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
        root=root, workspace=workspace, edit_blend=edit_blend, output=prod_out,
    )
    if not production_blocked or len(isolated_cert.records()) != prod_cert_before:
        raise RuntimeError(f'V0833_PRODUCTION_EXTENT_NEGATIVE_FAILED:{production_error}:output={prod_out.exists()}')

    # Multi-vertex extent composition stays fail-closed.  The two physically
    # discovered object-1 witnesses make this a real same-object saved-Blender
    # negative rather than a synthetic planner-only check.
    if int(found['dBound']['object_index']) != int(found['Bound']['object_index']):
        raise RuntimeError('V0833_NO_SHARED_OBJECT_PAIR_FOR_MULTI_VERTEX_NEGATIVE')
    _apply_two_vertex_same_object_negative(
        settings=settings, root=root, pristine_blend=pristine_blend, out_blend=edit_blend,
        a=found['dBound'], b=found['Bound'], work=workspace / 'apply_two_vertex_extent_negative',
    )
    multi_out = work / 'two_vertex_extent_should_not_exist.smd'
    multi_blocked, multi_error = _candidate_negative(
        reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
        root=root, workspace=workspace, output=multi_out,
        expected_error='TOO_MANY_VERTEX_POSITION_CHANGES_2',
    )
    if not multi_blocked:
        raise RuntimeError(f'V0833_MULTI_VERTEX_EXTENT_NEGATIVE_FAILED:{multi_error}:output={multi_out.exists()}')

    # Cross-object extent remains independently blocked at extraction.
    cross_a = found['maxX']
    cross_b = next((found[k] for k in TARGET_KINDS if int(found[k]['object_index']) != int(cross_a['object_index'])), None)
    if cross_b is None:
        raise RuntimeError('V0833_NO_DIFFERENT_OBJECT_PAIR_FOR_CROSS_OBJECT_NEGATIVE')
    _apply_cross_object_extent_negative(
        settings=settings, root=root, pristine_blend=pristine_blend, out_blend=edit_blend,
        a=cross_a, b=cross_b, work=workspace / 'apply_cross_object_extent_negative',
    )
    cross_out = work / 'cross_object_extent_should_not_exist.smd'
    cross_blocked, cross_error = _candidate_negative(
        reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
        root=root, workspace=workspace, output=cross_out,
        expected_error='MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED',
    )
    if not cross_blocked:
        raise RuntimeError(f'V0833_CROSS_OBJECT_EXTENT_NEGATIVE_FAILED:{cross_error}:output={cross_out.exists()}')

    # Inward movement of the maxX witness changes a vertex but proves no larger
    # stored bound.  Candidate writer must refuse rather than infer contraction.
    inward = json.loads(json.dumps(found['maxX']))
    before = [int(x) for x in inward['before_world_fixed']]
    after = list(before)
    axes = sorted(range(3), key=lambda i: abs(before[i]), reverse=True)
    inward_axis = next((i for i in axes if before[i] != 0), None)
    if inward_axis is None:
        raise RuntimeError('V0833_INWARD_NEGATIVE_ZERO_VECTOR_UNUSABLE')
    after[inward_axis] = before[inward_axis] - 1 if before[inward_axis] > 0 else before[inward_axis] + 1
    inward['requested_after_world_fixed'] = after
    _apply_saved_blender_one(
        settings=settings, root=root, base_blend=pristine_blend, plan=inward,
        out_blend=edit_blend, work=workspace / 'apply_inward_no_extent_negative',
    )
    inward_out = work / 'inward_extent_should_not_exist.smd'
    inward_blocked, inward_error = _candidate_negative(
        reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
        root=root, workspace=workspace, output=inward_out,
        expected_error='MULTIBONE_EXTENT_LIVE_REQUIRES_OUTWARD_BOUND_EXPANSION',
    )
    if not inward_blocked:
        raise RuntimeError(f'V0833_INWARD_EXTENT_NEGATIVE_FAILED:{inward_error}:output={inward_out.exists()}')

    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    source_sha_after = _sha256(source)
    single_sha_after = _sha256(single_path)
    cross_sha_after = _sha256(cross_path)
    writers_after = _writer_hashes(root)
    if real_count_after != real_count_before or real_sha_after != real_sha_before:
        raise RuntimeError('REAL_CERTIFICATION_REGISTRY_MODIFIED')
    if source_sha_after != source_sha_before:
        raise RuntimeError('CLIENT_SOURCE_MODIFIED')
    if single_sha_after != single_sha_before or cross_sha_after != cross_sha_before:
        raise RuntimeError('PRODUCTION_POLICY_MODIFIED')
    if writers_after != writers_before:
        raise RuntimeError('CERTIFIED_WRITERS_MODIFIED')

    candidate_records = [r for r in isolated_cert.records() if r.get('test') == CANDIDATE_TEST]
    if len(candidate_records) != len(TARGET_KINDS):
        raise RuntimeError(f'V0833_ISOLATED_CANDIDATE_CERT_COUNT_MISMATCH:{len(candidate_records)}')

    report = {
        'format': FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'logical': TARGET,
        'prior_v0832_strict_pass': True,
        'prior_v0832_witness_count': 5,
        'candidate_target_kinds': list(TARGET_KINDS),
        'candidate_witness_count': len(rows),
        'exact_candidate_writer_function_exercised': 'write_at_dragon_multibone_outward_extent_candidate_workspace',
        'all_candidate_rows_pass': all(r.get('status') == 'PASS' for r in rows),
        'rows': rows,
        'all_live_writer_outputs_match_v0832': all(r.get('matches_v0832_output_sha256') for r in rows),
        'isolated_preview_certification_count': 1,
        'isolated_candidate_certification_count': len(candidate_records),
        'candidate_certification_test': CANDIDATE_TEST,
        'production_extent_still_blocked': True,
        'production_extent_error': production_error,
        'production_extent_output_created': prod_out.exists(),
        'multi_vertex_extent_blocked': True,
        'multi_vertex_extent_error': multi_error,
        'multi_vertex_extent_output_created': multi_out.exists(),
        'cross_object_extent_blocked': True,
        'cross_object_extent_error': cross_error,
        'cross_object_extent_output_created': cross_out.exists(),
        'inward_no_extent_blocked': True,
        'inward_no_extent_error': inward_error,
        'inward_no_extent_output_created': inward_out.exists(),
        'real_certification_count_before': real_count_before,
        'real_certification_count_after': real_count_after,
        'real_certification_registry_sha256_before': real_sha_before,
        'real_certification_registry_sha256_after': real_sha_after,
        'real_certification_registry_modified': False,
        'single_object_production_policy_modified': False,
        'cross_object_production_policy_modified': False,
        'writer_modules_modified': False,
        'client_source_sha256_before': source_sha_before,
        'client_source_sha256_after': source_sha_after,
        'client_modified': False,
        'multibone_outward_extent_live_write_authorized': False,
        'extent_contraction_write_authorized': False,
        'multi_vertex_extent_write_authorized': False,
        'cross_object_extent_write_authorized': False,
        'topology_write_authorized': False,
        'writer_hashes': writers_after,
        'policy': {
            'scope': 'isolated live-writer candidate for the five physically proven at_dragon one-vertex multi-bone outward extent classes; one mesh object and exactly one changed vertex per write',
            'live_writer': 'candidate function consumes the saved workspace itself, rechecks physical source/skeleton/prepared hashes and serialized binding, independently extracts the actual saved vertex, infers only the exact proven bound-field shape, recomputes final-geometry multi-bone normals/bounds and atomically publishes only after all guards pass',
            'binary_equivalence': 'each live-writer candidate output must be SHA-256 identical to its corresponding V0.8.32 saved-Blender output',
            'certification': 'successful candidate writes append candidate-labelled records only to an isolated registry; the real append-only registry remains count/hash identical',
            'production_control': 'the exact existing production writer must continue rejecting the same extent edit with EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED and create no output/certification',
            'negatives': 'same-object two-vertex extent, cross-object extent and inward/no-expansion edits must all fail before output/certification',
            'authorization': 'PASS is isolated live-writer extent candidate evidence only; production extent remains unauthorized',
            'next_on_pass': 'build V0.8.35 interactive/manual one-vertex multi-bone outward extent candidate before any production promotion',
            'deferred': 'production extent writes, contraction, topology, multi-vertex extent composition and cross-object extent remain fail-closed',
        },
        'next': 'interactive/manual multi-bone outward extent candidate if this isolated live-writer gate passes',
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args(argv)
    out = pathlib.Path(a.output).resolve()
    try:
        report = run(pathlib.Path(a.root), out)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            'rare_rigid_multibone_outward_extent_live_writer=PASS '
            f'witnesses={report["candidate_witness_count"]} extent_authorized=false client_modified=false'
        )
        return 0
    except Exception as exc:
        report = {
            'format': FORMAT,
            'status': 'FAIL',
            'release_version': RELEASE_VERSION,
            'logical': TARGET,
            'error': f'{type(exc).__name__}:{exc}',
            'multibone_outward_extent_live_write_authorized': False,
            'extent_contraction_write_authorized': False,
            'multi_vertex_extent_write_authorized': False,
            'cross_object_extent_write_authorized': False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('rare_rigid_multibone_outward_extent_live_writer=FAIL')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
