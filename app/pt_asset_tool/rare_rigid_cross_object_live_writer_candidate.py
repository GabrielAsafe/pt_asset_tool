from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from collections import defaultdict
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_edit import WORKSPACE_FORMAT, _at_dragon_binding, prepare_at_dragon_edit_workspace
from .rare_rigid_cross_object_probe import (
    PROBE_OBJECT_COUNTS,
    compare_cross_object_transaction,
    discover_cross_object_representatives,
    patch_cross_object_transaction,
    _reimport_and_check_all,
)
from .rare_rigid_cross_object_saved_blender_candidate import (
    _apply_saved_blender,
    _exact_out_of_bounds_x,
    _production_extractor_still_blocks,
    _extract_candidate,
)
from .rare_rigid_large_production import POLICY_REL, load_and_validate_policy, production_widening
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, _safe_rows
from .rare_rigid_multibone_bridge import TARGET
from . import rare_rigid_edit as redit
from . import rare_rigid_multivertex as mv
from .utils import sha256_file

FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_LIVE_WRITER_CANDIDATE_AUDIT_V1'
WRITE_FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_LIVE_WRITER_CANDIDATE_WRITE_V1'
RELEASE_VERSION = '0.8.26'
PRIOR_REPORT = 'pt_build/rare_rigid_cross_object_saved_blender_workflow_v0825.json'
CANDIDATE_MAX_CHANGED = 8
CANDIDATE_MIN_OBJECTS = 2
CANDIDATE_MAX_OBJECTS = 3
CANDIDATE_VERTICES_PER_OBJECT = 2
CANDIDATE_TEST = 'RARE_RIGID_ARTIST_GUARDED_CROSS_OBJECT_TRANSACTION_WRITE_CANDIDATE'
CANDIDATE_SCOPE = 'AT_DRAGON_CROSS_OBJECT_TWO_OR_THREE_OBJECTS_TWO_VERTICES_EACH_INTERIOR_ATOMIC_TRANSACTION_CANDIDATE_ONLY'


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(root / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(reg: CertificationRegistry) -> str:
    return _sha256(reg.path) if reg.path.is_file() else hashlib.sha256(b'').hexdigest()


def _prior_gate(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_REPORT
    if not p.is_file():
        raise RuntimeError(f'PRIOR_V0825_REPORT_MISSING:{p}')
    r = _json(p)
    rows = list(r.get('rows') or [])
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_CANDIDATE_AUDIT_V3',
        r.get('status') == 'PASS',
        r.get('release_version') == '0.8.25',
        r.get('prior_v0822_gate_pass') is True,
        r.get('representatives_match_v0822') is True,
        list(r.get('candidate_object_counts') or []) == list(PROBE_OBJECT_COUNTS),
        int(r.get('candidate_max_total_changed_vertices', -1)) == CANDIDATE_MAX_CHANGED,
        len(rows) == len(PROBE_OBJECT_COUNTS),
        all(x.get('status') == 'PASS' for x in rows),
        all(x.get('matches_v0822_output_sha256') is True for x in rows),
        r.get('production_cross_object_still_blocked') is True,
        r.get('production_cross_object_output_created') is False,
        r.get('negative_saved_blender_partial_failure_blocked') is True,
        r.get('negative_output_created') is False,
        r.get('candidate_certification_written') is False,
        r.get('real_certification_registry_modified') is False,
        r.get('production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
        int(r.get('production_single_object_max_vertices', -1)) == 8,
        r.get('cross_object_live_write_authorized') is False,
    ]
    if not all(checks):
        raise RuntimeError(f'PRIOR_V0825_GATE_NOT_STRICT_PASS:{r}')
    return r


def _transaction_from_extraction(prepared: pathlib.Path, skeleton: pathlib.Path, extraction: dict[str, Any]) -> dict[str, Any]:
    changed = list(extraction.get('changed_vertices') or [])
    if not (1 <= len(changed) <= CANDIDATE_MAX_CHANGED):
        raise RuntimeError(f'CROSS_OBJECT_LIVE_CHANGED_COUNT_OUTSIDE_1_{CANDIDATE_MAX_CHANGED}:{len(changed)}')
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ch in changed:
        grouped[int(ch['object_index'])].append(ch)
    object_indices = sorted(grouped)
    if not (CANDIDATE_MIN_OBJECTS <= len(object_indices) <= CANDIDATE_MAX_OBJECTS):
        raise RuntimeError(f'CROSS_OBJECT_LIVE_OBJECT_COUNT_OUTSIDE_{CANDIDATE_MIN_OBJECTS}_{CANDIDATE_MAX_OBJECTS}:{len(object_indices)}')
    for oi in object_indices:
        if len(grouped[oi]) != CANDIDATE_VERTICES_PER_OBJECT:
            raise RuntimeError(f'CROSS_OBJECT_LIVE_REQUIRES_EXACTLY_TWO_VERTICES_PER_OBJECT:{oi}:{len(grouped[oi])}')

    plans = []
    for oi in object_indices:
        changes = [
            {
                'object_index': oi,
                'vertex_index': int(ch['vertex_index']),
                'before_world_fixed': [int(x) for x in ch['before_world_fixed']],
                'after_world_fixed': [int(x) for x in ch['after_world_fixed']],
            }
            for ch in sorted(grouped[oi], key=lambda x: int(x['vertex_index']))
        ]
        plan = mv.plan_requested_at_dragon_transaction(prepared, skeleton, changes=changes)
        extract_before = {int(ch['vertex_index']): [int(x) for x in ch['before_world_fixed']] for ch in grouped[oi]}
        for row in plan.get('changed_vertices') or []:
            vi = int(row['vertex_index'])
            if vi not in extract_before or list(row['before_world_fixed']) != extract_before[vi]:
                raise RuntimeError(f'CROSS_OBJECT_LIVE_BASELINE_MISMATCH_OBJECT_{oi}_VERTEX_{vi}')
        plans.append(plan)

    total = sum(int(p['changed_vertex_count']) for p in plans)
    if total != len(changed) or total > CANDIDATE_MAX_CHANGED:
        raise RuntimeError(f'CROSS_OBJECT_LIVE_TOTAL_CHANGED_MISMATCH:{total}!={len(changed)}')
    return {
        'object_count': len(plans),
        'object_indices': object_indices,
        'total_changed_vertices': total,
        'per_object_plans': plans,
        'transaction_atomic': True,
        'guard_status': 'PASS',
    }


def _asset_id(reg: AssetRegistry) -> str:
    try:
        aid = str(getattr(reg.resolve(TARGET), 'asset_id', '') or '')
    except Exception:
        aid = ''
    return aid or ('RARE::' + TARGET)


def write_at_dragon_cross_object_candidate_workspace(
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
        raise RuntimeError(f'CROSS_OBJECT_CANDIDATE_WORKSPACE_MANIFEST_MISSING:{manifest_path}')
    manifest = _json(manifest_path)
    if manifest.get('format') != WORKSPACE_FORMAT or manifest.get('logical') != TARGET:
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_WORKSPACE_MANIFEST_MISMATCH')

    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    if sha256_file(source) != manifest.get('source_sha256'):
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_PHYSICAL_SOURCE_CHANGED')
    skeleton = pathlib.Path(resolver.resolve(manifest['motion_smb'], required=True))
    if sha256_file(skeleton) != manifest.get('skeleton_sha256'):
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_SKELETON_CHANGED')
    prepared = pathlib.Path(manifest['prepared_source'])
    if not prepared.is_file() or sha256_file(prepared) != manifest.get('prepared_source_sha256'):
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_PREPARED_SOURCE_CHANGED')

    # Mirror the production writer's immediate serialized binding recheck.
    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=project_root,
        work=work / ('cross_object_live_binding_recheck_' + pathlib.Path(output).stem), bundle=None,
    )
    if binding.get('status') != 'PASS':
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_BINDING_RECHECK_FAILED')
    _at_dragon_binding(binding)

    edit_blend = pathlib.Path(manifest['edit_blend'])
    if not edit_blend.is_file():
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_SAVED_BLEND_MISSING')
    write_work = work / ('cross_object_live_candidate_' + pathlib.Path(output).stem)
    if write_work.exists():
        shutil.rmtree(write_work)
    write_work.mkdir(parents=True)
    extraction_path = write_work / 'artist_edit_extract.json'
    extraction, _ = _extract_candidate(
        root=project_root, settings=settings, blend=edit_blend,
        baseline=pathlib.Path(manifest['baseline_blender_report']),
        report_path=extraction_path, work=write_work, expect_success=True,
    )
    assert extraction is not None
    if extraction.get('writer_input_mode_before') != 'EDIT_MESH':
        raise RuntimeError(f'CROSS_OBJECT_CANDIDATE_INPUT_MODE_NOT_EDIT_MESH:{extraction.get("writer_input_mode_before")}')
    if extraction.get('writer_input_mode_after') != 'OBJECT':
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_EXTRACTION_DID_NOT_CANONICALIZE')
    if extraction.get('writer_input_object_mode_canonicalized') is not True:
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_OBJECT_MODE_NOT_CANONICALIZED')
    if extraction.get('non_position_semantic_state_pass') is not True:
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_NON_POSITION_SEMANTIC_STATE_FAILED')
    if float(extraction.get('max_uv_state_delta', 1.0)) != 0.0:
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_UV_STATE_DELTA_NONZERO')
    if float(extraction.get('max_physique_weight_delta', 1.0)) != 0.0:
        raise RuntimeError('CROSS_OBJECT_CANDIDATE_PHYSIQUE_STATE_DELTA_NONZERO')

    transaction = _transaction_from_extraction(prepared, skeleton, extraction)
    final_output = pathlib.Path(output).resolve()
    final_output.parent.mkdir(parents=True, exist_ok=True)
    final_output.unlink(missing_ok=True)
    staging = final_output.with_name(final_output.name + '.v0826_staging')
    staging.unlink(missing_ok=True)
    try:
        patch = patch_cross_object_transaction(source, prepared, staging, transaction)
        binary = compare_cross_object_transaction(source, staging, staging, skeleton, transaction, patch)
        validation = _reimport_and_check_all(
            root=project_root, settings=settings, resolver=resolver, manifest=manifest,
            prepared_output=staging, transaction=transaction, work=write_work / 'write_validation',
        )
        staging.replace(final_output)
    except Exception:
        staging.unlink(missing_ok=True)
        final_output.unlink(missing_ok=True)
        raise

    affected_bones = sorted({str(b) for p in transaction['per_object_plans'] for b in (p.get('affected_bones') or [])})
    cert = certifications.add(
        asset_id=_asset_id(reg), asset_path=TARGET,
        family='MODEL062_LEGACY_NAME_MISMATCH_BODY_EXACT',
        test=CANDIDATE_TEST, layer='AUTOMATIC', result='PASS',
        source_sha256=sha256_file(source), artifact_sha256=sha256_file(final_output),
        notes='V0.8.26 isolated cross-object live-writer candidate only; not production authorization.',
        metadata={
            'write_scope': CANDIDATE_SCOPE,
            'candidate_only': True,
            'production_authorized': False,
            'object_count': int(transaction['object_count']),
            'object_indices': list(transaction['object_indices']),
            'artist_changed_vertices': int(transaction['total_changed_vertices']),
            'per_object_changed_vertex_indices': {
                str(p['object_index']): list(p['changed_vertex_indices']) for p in transaction['per_object_plans']
            },
            'affected_bone_count_union': len(affected_bones),
            'affected_bones_union': affected_bones,
            'all_non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
            'all_affected_object_bounds_byte_identical': binary['all_affected_object_bounds_byte_identical'],
            'atomic_output_replace': True,
            'client_modified': False,
        },
    )
    return {
        'format': WRITE_FORMAT,
        'status': 'PASS',
        'logical': TARGET,
        'candidate_only': True,
        'production_authorized': False,
        'exact_candidate_writer_function_exercised': 'write_at_dragon_cross_object_candidate_workspace',
        'object_count': int(transaction['object_count']),
        'object_indices': list(transaction['object_indices']),
        'artist_changed_vertices': int(transaction['total_changed_vertices']),
        'per_object_changed_vertex_indices': {
            str(p['object_index']): list(p['changed_vertex_indices']) for p in transaction['per_object_plans']
        },
        'affected_bone_count_union': len(affected_bones),
        'affected_bones_union': affected_bones,
        'writer_input_mode_before': extraction.get('writer_input_mode_before'),
        'writer_input_mode_after': extraction.get('writer_input_mode_after'),
        'writer_input_object_mode_canonicalized': extraction.get('writer_input_object_mode_canonicalized'),
        'non_position_semantic_state_pass': extraction.get('non_position_semantic_state_pass'),
        'max_uv_state_delta': extraction.get('max_uv_state_delta'),
        'max_physique_weight_delta': extraction.get('max_physique_weight_delta'),
        'all_non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
        'all_affected_object_bounds_byte_identical': binary['all_affected_object_bounds_byte_identical'],
        'bounds_header_byte_identical_by_object': binary['bounds_header_byte_identical_by_object'],
        'binary_diff_byte_count': binary['diff_byte_count'],
        'blender_reimport_pass': validation['blender_reimport_pass'],
        'transport_pass': validation['transport_pass'],
        'transport_position_error': validation['transport_position_error'],
        'transport_uv_error': validation['transport_uv_error'],
        'physique_mismatch_count': validation['physique_mismatch_count'],
        'all_object_transaction_witness_pass': validation['all_object_transaction_witness_pass'],
        'per_object_transaction_witness': validation['per_object_transaction_witness'],
        'transaction_atomic': True,
        'atomic_output_replace': patch['atomic_output_replace'],
        'output_smd': str(final_output),
        'output_sha256': _sha256(final_output),
        'candidate_certification_id': cert['certification_id'],
        'candidate_certification_test': CANDIDATE_TEST,
        'candidate_write_scope': CANDIDATE_SCOPE,
    }


def _install_transaction_into_workspace(
    *, root: pathlib.Path, settings: Settings, pristine_blend: pathlib.Path,
    manifest: dict[str, Any], transaction: dict[str, Any], workspace: pathlib.Path, label: str,
) -> dict[str, Any]:
    edit_blend = pathlib.Path(manifest['edit_blend'])
    return _apply_saved_blender(
        root=root, settings=settings, base_blend=pristine_blend,
        transaction=transaction, out_blend=edit_blend, work=workspace / ('apply_' + label),
    )


def _bad_bounds_transaction(prepared: pathlib.Path, transaction: dict[str, Any]) -> dict[str, Any]:
    bad = json.loads(json.dumps(transaction))
    last = bad['per_object_plans'][-1]
    row = last['changed_vertices'][0]
    current = [int(x) for x in row['requested_after_world_fixed']]
    sign = 1 if current[0] >= 0 else -1
    row['requested_after_world_fixed'] = [
        _exact_out_of_bounds_x(prepared, int(last['object_index']), sign), current[1], current[2]
    ]
    return bad


def _nine_vertex_saved_transaction(prepared: pathlib.Path, skeleton: pathlib.Path, base_tx: dict[str, Any]) -> dict[str, Any]:
    safe_by_object, _ = _safe_rows(prepared, skeleton)
    plans = []
    for base_plan in base_tx['per_object_plans']:
        oi = int(base_plan['object_index'])
        used = {int(x) for x in base_plan['changed_vertex_indices']}
        rows = [r for r in safe_by_object.get(oi, []) if int(r['vertex_index']) not in used]
        if not rows:
            raise RuntimeError(f'NINE_VERTEX_CONTROL_NO_THIRD_SAFE_VERTEX_OBJECT_{oi}')
        extra = rows[0]
        changes = [
            {
                'object_index': oi,
                'vertex_index': int(r['vertex_index']),
                'before_world_fixed': list(r['before_world_fixed']),
                'requested_after_world_fixed': list(r['requested_after_world_fixed']),
            }
            for r in base_plan['changed_vertices']
        ]
        changes.append({
            'object_index': oi,
            'vertex_index': int(extra['vertex_index']),
            'before_world_fixed': list(extra['before_world_fixed']),
            'requested_after_world_fixed': list(extra['requested_after_world_fixed']),
        })
        # The saved-Blender transport only needs the changed_vertices rows. Do not
        # require a 3-vertex plan to pass: the candidate extractor must reject total=9
        # before the live writer plans or publishes anything.
        plans.append({'object_index': oi, 'changed_vertices': changes})
    return {
        'object_count': len(plans),
        'object_indices': [int(p['object_index']) for p in plans],
        'total_changed_vertices': sum(len(p['changed_vertices']) for p in plans),
        'per_object_plans': plans,
    }


def _exact_production_core_still_blocks(
    *, root: pathlib.Path, reg: AssetRegistry, resolver: ClientResolver,
    certifications: CertificationRegistry, settings: Settings, workspace: pathlib.Path,
) -> tuple[bool, str]:
    before = len(certifications.records())
    try:
        with production_widening():
            redit.write_at_dragon_edit_workspace(
                reg, resolver, certifications, settings,
                project_root=root, workspace_root=workspace,
                output=workspace / 'production_control_should_not_exist.smd',
            )
    except Exception as exc:
        after = len(certifications.records())
        blocked = 'MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED' in str(exc) and before == after
        return blocked, f'{type(exc).__name__}:{exc}'
    return False, 'UNEXPECTED_PASS'


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    prior = _prior_gate(root)
    policy = load_and_validate_policy(root)
    policy_path = root / POLICY_REL
    policy_sha_before = _sha256(policy_path)
    if int(policy.get('production_max_vertices', -1)) != 8 or policy.get('single_object_only') is not True:
        raise RuntimeError('V0821_PRODUCTION_POLICY_SCOPE_UNEXPECTED')

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0826')

    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records())
    real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    if source_sha_before != policy.get('client_source_sha256'):
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0821_POLICY')

    isolated_cert = CertificationRegistry(work / 'isolated_certifications')
    workspace = work / 'isolated_artist_workspace'
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings,
        project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin='AUDIT_V0826_LIVE_WRITER_CROSS_OBJECT_CANDIDATE',
    )
    preview_records = isolated_cert.records()
    if len(preview_records) != 1 or preview_records[0].get('test') != 'RARE_RIGID_BLENDER_PREVIEW':
        raise RuntimeError(f'ISOLATED_PREVIEW_CERT_UNEXPECTED:{preview_records}')

    prepared = pathlib.Path(manifest['prepared_source'])
    skeleton = pathlib.Path(manifest['skeleton'])
    edit_blend = pathlib.Path(manifest['edit_blend'])
    pristine_blend = work / 'pristine_edit_workspace.blend'
    shutil.copy2(edit_blend, pristine_blend)
    discovery = discover_cross_object_representatives(prepared, skeleton)
    if not discovery.get('complete'):
        raise RuntimeError(f'CROSS_OBJECT_REPRESENTATIVE_DISCOVERY_INCOMPLETE:{discovery}')

    prior_rows = {int(r['object_count']): r for r in prior.get('rows') or []}
    rows = []
    first_saved_copy = None
    for count in PROBE_OBJECT_COUNTS:
        tx = discovery['representatives'][f'objects_{count}']
        prior_row = prior_rows.get(count)
        if prior_row is None:
            raise RuntimeError(f'V0825_PRIOR_ROW_MISSING_{count}')
        expected_map = {str(k): [int(x) for x in v] for k, v in (prior_row['per_object_changed_vertex_indices'] or {}).items()}
        actual_map = {str(p['object_index']): [int(x) for x in p['changed_vertex_indices']] for p in tx['per_object_plans']}
        if actual_map != expected_map:
            raise RuntimeError(f'V0826_REPRESENTATIVE_DRIFT_{count}:{actual_map}!={expected_map}')

        apply = _install_transaction_into_workspace(
            root=root, settings=settings, pristine_blend=pristine_blend,
            manifest=manifest, transaction=tx, workspace=workspace, label=f'objects_{count}',
        )
        if first_saved_copy is None:
            first_saved_copy = work / 'first_cross_object_saved.blend'
            shutil.copy2(edit_blend, first_saved_copy)
        cert_before = len(isolated_cert.records())
        out_smd = work / f'live_candidate_{count}' / f'cross_object_live_candidate_{count}.smd'
        result = write_at_dragon_cross_object_candidate_workspace(
            reg, resolver, isolated_cert, settings,
            project_root=root, workspace_root=workspace, output=out_smd,
        )
        cert_after = len(isolated_cert.records())
        if cert_after != cert_before + 1:
            raise RuntimeError(f'CROSS_OBJECT_LIVE_CANDIDATE_CERT_COUNT_{count}:{cert_before}->{cert_after}')
        if result['output_sha256'] != str(prior_row['output_sha256']):
            raise RuntimeError(f'V0826_OUTPUT_DIFFERS_FROM_V0825_OBJECTS_{count}')
        if sorted(result['object_indices']) != sorted(int(x) for x in tx['object_indices']):
            raise RuntimeError(f'V0826_OBJECT_SET_DRIFT_{count}')
        result.update({
            'saved_blender_apply_pass': True,
            'saved_blender_saved_mode': apply['saved_mode'],
            'saved_blender_objects_in_mode': apply['objects_in_mode'],
            'matches_v0825_output_sha256': True,
            'isolated_candidate_certification_count_delta': 1,
        })
        rows.append(result)
        shutil.copy2(pristine_blend, edit_blend)

    candidate_records = [r for r in isolated_cert.records() if r.get('test') == CANDIDATE_TEST]
    candidate_counts = sorted(int((r.get('metadata') or {}).get('object_count', -1)) for r in candidate_records)
    if candidate_counts != list(PROBE_OBJECT_COUNTS):
        raise RuntimeError(f'CROSS_OBJECT_LIVE_CANDIDATE_CERT_OBJECT_COUNTS:{candidate_counts}')

    # Production path control: same real multi-object blend, exact core function,
    # V0.8.21 max=8 widening active; rejection must still occur at the production extractor.
    assert first_saved_copy is not None
    shutil.copy2(first_saved_copy, edit_blend)
    prod_cert_before = len(isolated_cert.records())
    prod_blocked, prod_error = _exact_production_core_still_blocks(
        root=root, reg=reg, resolver=resolver, certifications=isolated_cert,
        settings=settings, workspace=workspace,
    )
    if not prod_blocked or len(isolated_cert.records()) != prod_cert_before:
        raise RuntimeError(f'PRODUCTION_CORE_MULTI_OBJECT_NOT_STRICTLY_BLOCKED:{prod_error}')
    production_control_output = workspace / 'production_control_should_not_exist.smd'
    if production_control_output.exists():
        raise RuntimeError('PRODUCTION_CORE_MULTI_OBJECT_OUTPUT_CREATED')

    # Bounds negative through the live-writer candidate must fail before output/certification.
    bad = _bad_bounds_transaction(prepared, discovery['representatives']['objects_2'])
    _install_transaction_into_workspace(
        root=root, settings=settings, pristine_blend=pristine_blend,
        manifest=manifest, transaction=bad, workspace=workspace, label='negative_bounds',
    )
    neg_output = work / 'negative_bounds_should_not_exist.smd'
    neg_cert_before = len(isolated_cert.records())
    try:
        write_at_dragon_cross_object_candidate_workspace(
            reg, resolver, isolated_cert, settings,
            project_root=root, workspace_root=workspace, output=neg_output,
        )
    except Exception as exc:
        negative_bounds_blocked = 'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' in str(exc)
        negative_bounds_error = f'{type(exc).__name__}:{exc}'
    else:
        negative_bounds_blocked = False
        negative_bounds_error = 'UNEXPECTED_PASS'
    if not negative_bounds_blocked or neg_output.exists() or len(isolated_cert.records()) != neg_cert_before:
        raise RuntimeError(f'CROSS_OBJECT_LIVE_BOUNDS_NEGATIVE_NOT_STRICT:{negative_bounds_error}')

    # Total >8 must fail at extraction before planning, output or certification.
    nine_tx = _nine_vertex_saved_transaction(prepared, skeleton, discovery['representatives']['objects_3'])
    if int(nine_tx['total_changed_vertices']) != 9:
        raise RuntimeError('NINE_VERTEX_CONTROL_NOT_NINE')
    _install_transaction_into_workspace(
        root=root, settings=settings, pristine_blend=pristine_blend,
        manifest=manifest, transaction=nine_tx, workspace=workspace, label='negative_nine',
    )
    nine_output = work / 'nine_vertex_should_not_exist.smd'
    nine_cert_before = len(isolated_cert.records())
    try:
        write_at_dragon_cross_object_candidate_workspace(
            reg, resolver, isolated_cert, settings,
            project_root=root, workspace_root=workspace, output=nine_output,
        )
    except Exception as exc:
        nine_error = f'{type(exc).__name__}:{exc}'
        nine_blocked = 'TOO_MANY_VERTEX_POSITION_CHANGES_9' in str(exc)
    else:
        nine_error = 'UNEXPECTED_PASS'
        nine_blocked = False
    if not nine_blocked or nine_output.exists() or len(isolated_cert.records()) != nine_cert_before:
        raise RuntimeError(f'CROSS_OBJECT_LIVE_NINE_VERTEX_NOT_STRICT:{nine_error}')

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    policy_sha_after = _sha256(policy_path)
    writer_unchanged = writers_before == writers_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    cert_unchanged = real_count_before == real_count_after and real_sha_before == real_sha_after
    policy_unchanged = policy_sha_before == policy_sha_after
    limits_restored = int(redit.MAX_TRANSACTION_VERTICES) == 4 and int(mv.MAX_TRANSACTION_VERTICES) == 4
    if not all([writer_unchanged, client_unchanged, cert_unchanged, policy_unchanged, limits_restored]):
        raise RuntimeError('V0826_SIDE_EFFECT_OR_LIMIT_RESTORE_FAILURE')

    return {
        'format': FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'base_release': '0.8.25',
        'logical': TARGET,
        'prior_v0825_gate_pass': True,
        'candidate_object_counts': list(PROBE_OBJECT_COUNTS),
        'candidate_total_changed_vertices': [int(r['artist_changed_vertices']) for r in rows],
        'candidate_max_total_changed_vertices': CANDIDATE_MAX_CHANGED,
        'candidate_vertices_per_object': CANDIDATE_VERTICES_PER_OBJECT,
        'exact_candidate_writer_function_exercised': 'write_at_dragon_cross_object_candidate_workspace',
        'rows': rows,
        'isolated_preview_certification_count': 1,
        'isolated_candidate_certification_count': len(candidate_records),
        'isolated_candidate_certification_object_counts': candidate_counts,
        'candidate_certification_test': CANDIDATE_TEST,
        'production_exact_core_writer_cross_object_blocked': True,
        'production_exact_core_writer_error': prod_error,
        'production_cross_object_output_created': False,
        'negative_bounds_blocked': True,
        'negative_bounds_error': negative_bounds_error,
        'negative_bounds_output_created': False,
        'negative_bounds_certification_written': False,
        'nine_vertex_blocked': True,
        'nine_vertex_error': nine_error,
        'nine_vertex_output_created': False,
        'nine_vertex_certification_written': False,
        'real_certification_count_before': real_count_before,
        'real_certification_count_after': real_count_after,
        'real_certification_registry_sha256_before': real_sha_before,
        'real_certification_registry_sha256_after': real_sha_after,
        'real_certification_registry_modified': False,
        'production_policy_sha256_before': policy_sha_before,
        'production_policy_sha256_after': policy_sha_after,
        'production_policy_modified': False,
        'writer_modules_modified': False,
        'client_source_sha256_before': source_sha_before,
        'client_source_sha256_after': source_sha_after,
        'client_modified': False,
        'process_local_limits_restored_to_4': limits_restored,
        'production_single_object_max_vertices': 8,
        'cross_object_live_write_authorized': False,
        'manual_artist_proof_required_before_cross_object_authorization': True,
        'policy': {
            'scope': 'isolated live-writer cross-object candidate for 2 and 3 at_dragon mesh objects; exactly two changed vertices per object; interior only; total <=8',
            'live_writer': 'candidate function consumes the saved workspace itself, rechecks physical binding/source/skeleton/prepared hashes, extracts multi-object EDIT_MESH without an expected transaction input, rebuilds per-object plans and atomically publishes only after all guards pass',
            'binary_equivalence': 'each live-writer candidate output must match the corresponding physically passed V0.8.25 saved-Blender output SHA-256',
            'certification': 'successful candidate writes append candidate-labelled records only to an isolated registry; the real append-only registry remains count/hash identical',
            'production_control': 'the exact certified core write_at_dragon_edit_workspace path under the existing V0.8.21 max=8 widening must continue rejecting the same multi-object saved Blender edit',
            'upper_bound': 'a nine-vertex multi-object saved Blender edit is rejected at candidate extraction before planning/output/certification',
            'guards': 'out-of-bounds partial failure remains blocked with zero output and zero candidate certification',
            'authorization': 'PASS is isolated live-writer cross-object candidate evidence only; production cross-object remains unauthorized',
            'next_on_pass': 'build V0.8.27 interactive cross-object candidate workspace/write command for one real manual two-object artist transaction before any production promotion',
            'deferred': 'production cross-object authorization, extent/bounds changes, topology and >8 total changed vertices remain fail-closed',
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.26 isolated live-writer cross-object candidate')
    ap.add_argument('--root', required=True)
    ap.add_argument('--output', required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            'format': FORMAT,
            'status': 'FAIL',
            'release_version': RELEASE_VERSION,
            'error': f'{type(exc).__name__}:{exc}',
            'production_single_object_max_vertices': 8,
            'cross_object_live_write_authorized': False,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get('status') == 'PASS':
        print(
            'rare_rigid_cross_object_live_writer_candidate=PASS '
            'object_counts=2,3 candidate_max_total=8 production_single_object_max=8 '
            'cross_object_authorized=false client_modified=false'
        )
        return 0
    print('rare_rigid_cross_object_live_writer_candidate=FAIL')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
