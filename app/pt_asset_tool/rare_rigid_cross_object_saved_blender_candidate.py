from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import struct
from collections import defaultdict
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_cross_object_probe import (
    PROBE_OBJECT_COUNTS,
    compare_cross_object_transaction,
    discover_cross_object_representatives,
    patch_cross_object_transaction,
    _reimport_and_check_all,
)
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from .rare_rigid_large_production import POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_roundtrip import _parse_with_offsets
from . import rare_rigid_multivertex as mv
from .utils import run_logged

FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_CANDIDATE_AUDIT_V3'
RELEASE_VERSION = '0.8.25'
PRIOR_REPORT = 'pt_build/rare_rigid_cross_object_probe_workflow_v0822.json'
PRIOR_FAILED_REPORT = 'pt_build/rare_rigid_cross_object_saved_blender_workflow_v0824.json'
CANDIDATE_MAX_CHANGED = 8


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
        raise RuntimeError(f'PRIOR_V0822_REPORT_MISSING:{p}')
    r = _json(p)
    rows = list(r.get('rows') or [])
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_TRANSACTION_PROBE_AUDIT_V1',
        r.get('status') == 'PASS',
        list(r.get('probe_object_counts') or []) == list(PROBE_OBJECT_COUNTS),
        bool(r.get('probe_representatives_complete')),
        len(rows) == len(PROBE_OBJECT_COUNTS),
        all(x.get('status') == 'PASS' for x in rows),
        r.get('negative_partial_failure_blocked') is True,
        r.get('negative_output_created') is False,
        r.get('production_cross_object_still_blocked') is True,
        r.get('cross_object_write_authorized') is False,
        r.get('real_certification_registry_modified') is False,
        r.get('production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
    ]
    if not all(checks):
        raise RuntimeError(f'PRIOR_V0822_GATE_NOT_STRICT_PASS:{r}')
    return r


def _prior_v0824_failure(root: pathlib.Path) -> dict[str, Any]:
    p = root / PRIOR_FAILED_REPORT
    if not p.is_file():
        raise RuntimeError(f'PRIOR_V0824_FAIL_REPORT_MISSING:{p}')
    r = _json(p)
    err = str(r.get('error') or '')
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_SAVED_BLENDER_CANDIDATE_AUDIT_V2',
        r.get('status') == 'FAIL',
        r.get('release_version') == '0.8.24',
        'fixed quantization mismatch object=5 vertex=6' in err,
        '268436160' in err and '268436149' in err,
        int(r.get('production_single_object_max_vertices', -1)) == 8,
        r.get('cross_object_live_write_authorized') is False,
    ]
    if not all(checks):
        raise RuntimeError(f'PRIOR_V0824_FAILURE_NOT_EXPECTED_NEGATIVE_QUANTIZATION_SHAPE:{r}')
    return r


def _assert_representatives_match_prior(discovery: dict[str, Any], prior: dict[str, Any]) -> None:
    prior_rows = {int(r['object_count']): r for r in prior.get('rows') or []}
    for count in PROBE_OBJECT_COUNTS:
        tx = discovery['representatives'][f'objects_{count}']
        row = prior_rows.get(count)
        if row is None:
            raise RuntimeError(f'PRIOR_ROW_MISSING_{count}')
        if [int(x) for x in tx['object_indices']] != [int(x) for x in row['object_indices']]:
            raise RuntimeError(f'REPRESENTATIVE_OBJECTS_DRIFT_{count}')
        expected_map = {str(k): [int(x) for x in v] for k, v in (row['per_object_changed_vertex_indices'] or {}).items()}
        actual_map = {str(p['object_index']): [int(x) for x in p['changed_vertex_indices']] for p in tx['per_object_plans']}
        if actual_map != expected_map:
            raise RuntimeError(f'REPRESENTATIVE_VERTICES_DRIFT_{count}:{actual_map}!={expected_map}')


def _apply_saved_blender(
    *, root: pathlib.Path, settings: Settings, base_blend: pathlib.Path,
    transaction: dict[str, Any], out_blend: pathlib.Path, work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    out_blend.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_blend, out_blend)
    plan_path = work / 'cross_object_transaction_plan.json'
    report_path = work / 'cross_object_saved_blender_apply.json'
    plan_path.write_text(json.dumps(transaction, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    script = root / 'pt_asset_tool/blender/apply_rare_rigid_cross_object_transaction.py'
    run_logged(settings.blender_command() + [
        '--background', str(out_blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--plan', str(plan_path), '--report', str(report_path),
    ], work / '01_apply_cross_object_saved_blender.log')
    report = _json(report_path)
    if report.get('check') != 'PASS':
        raise RuntimeError(f'CROSS_OBJECT_SAVED_BLENDER_APPLY_FAILED:{report}')
    if report.get('saved_mode') != 'EDIT_MESH' or report.get('saved_mode_raw') != 'EDIT':
        raise RuntimeError(f'CROSS_OBJECT_SAVED_BLEND_NOT_EDIT_MESH:{report}')
    if [int(x) for x in report.get('object_indices') or []] != sorted(int(x) for x in transaction['object_indices']):
        raise RuntimeError('CROSS_OBJECT_SAVED_BLEND_OBJECT_SET_MISMATCH')
    if int(report.get('changed_vertex_count', -1)) != int(transaction['total_changed_vertices']):
        raise RuntimeError('CROSS_OBJECT_SAVED_BLEND_VERTEX_COUNT_MISMATCH')
    return report


def _extract_candidate(
    *, root: pathlib.Path, settings: Settings, blend: pathlib.Path,
    baseline: pathlib.Path, report_path: pathlib.Path, work: pathlib.Path,
    expect_success: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    script = root / 'pt_asset_tool/blender/extract_rare_rigid_cross_object_candidate.py'
    cmd = settings.blender_command() + [
        '--background', str(blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--baseline', str(baseline), '--report', str(report_path),
        '--max-changed', str(CANDIDATE_MAX_CHANGED), '--min-objects', '2', '--max-objects', '3',
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    work.mkdir(parents=True, exist_ok=True)
    (work / '02_extract_cross_object_candidate.log').write_text(proc.stdout or '', encoding='utf-8')
    report = _json(report_path) if report_path.is_file() else None
    if expect_success:
        if proc.returncode != 0 or report is None or report.get('check') != 'PASS':
            raise RuntimeError(f'CROSS_OBJECT_CANDIDATE_EXTRACTION_FAILED:rc={proc.returncode}:report={report}')
    return report, proc.stdout or ''


def _rebuild_transaction_from_extraction(
    *, prepared: pathlib.Path, skeleton: pathlib.Path, extraction: dict[str, Any], expected: dict[str, Any],
) -> dict[str, Any]:
    changed = list(extraction.get('changed_vertices') or [])
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ch in changed:
        grouped[int(ch['object_index'])].append(ch)
    object_indices = sorted(grouped)
    expected_objects = sorted(int(x) for x in expected['object_indices'])
    if object_indices != expected_objects:
        raise RuntimeError(f'EXTRACTED_OBJECT_SET_MISMATCH:{object_indices}!={expected_objects}')
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
        plans.append(plan)
    actual_map = {str(p['object_index']): [int(x) for x in p['changed_vertex_indices']] for p in plans}
    expected_map = {str(p['object_index']): [int(x) for x in p['changed_vertex_indices']] for p in expected['per_object_plans']}
    if actual_map != expected_map:
        raise RuntimeError(f'EXTRACTED_VERTEX_SET_MISMATCH:{actual_map}!={expected_map}')
    return {
        'object_count': len(plans),
        'object_indices': [int(p['object_index']) for p in plans],
        'total_changed_vertices': sum(int(p['changed_vertex_count']) for p in plans),
        'per_object_plans': plans,
        'transaction_atomic': True,
        'guard_status': 'PASS',
    }


def _candidate_write_from_saved_blend(
    *, root: pathlib.Path, settings: Settings, source: pathlib.Path, prepared: pathlib.Path,
    skeleton: pathlib.Path, manifest: dict[str, Any], resolver: ClientResolver,
    blend: pathlib.Path, expected: dict[str, Any], output: pathlib.Path, work: pathlib.Path,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    extraction_path = work / 'candidate_extract.json'
    extraction, _ = _extract_candidate(
        root=root, settings=settings, blend=blend,
        baseline=pathlib.Path(manifest['baseline_blender_report']),
        report_path=extraction_path, work=work, expect_success=True,
    )
    assert extraction is not None
    if extraction.get('writer_input_mode_before') != 'EDIT_MESH':
        raise RuntimeError(f'CANDIDATE_INPUT_MODE_NOT_EDIT_MESH:{extraction.get("writer_input_mode_before")}')
    if extraction.get('writer_input_mode_after') != 'OBJECT':
        raise RuntimeError('CANDIDATE_EXTRACTION_DID_NOT_CANONICALIZE')
    if not extraction.get('non_position_semantic_state_pass'):
        raise RuntimeError('CANDIDATE_NON_POSITION_SEMANTIC_STATE_FAILED')
    if float(extraction.get('max_uv_state_delta', 1.0)) != 0.0:
        raise RuntimeError('CANDIDATE_UV_STATE_DELTA_NONZERO')
    if float(extraction.get('max_physique_weight_delta', 1.0)) != 0.0:
        raise RuntimeError('CANDIDATE_PHYSIQUE_STATE_DELTA_NONZERO')

    transaction = _rebuild_transaction_from_extraction(
        prepared=prepared, skeleton=skeleton, extraction=extraction, expected=expected,
    )
    output.unlink(missing_ok=True)
    staging = output.with_name(output.name + '.v0823_staging')
    staging.unlink(missing_ok=True)
    try:
        patch = patch_cross_object_transaction(source, prepared, staging, transaction)
        compare = compare_cross_object_transaction(source, staging, staging, skeleton, transaction, patch)
        rebuilt = _reimport_and_check_all(
            root=root, settings=settings, resolver=resolver, manifest=manifest,
            prepared_output=staging, transaction=transaction, work=work / 'reimport',
        )
        staging.replace(output)
    except Exception:
        staging.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    return {
        'status': 'PASS',
        'object_count': int(transaction['object_count']),
        'object_indices': list(transaction['object_indices']),
        'total_changed_vertices': int(transaction['total_changed_vertices']),
        'per_object_changed_vertex_indices': {
            str(p['object_index']): list(p['changed_vertex_indices']) for p in transaction['per_object_plans']
        },
        'saved_blender_input_mode_before': extraction.get('writer_input_mode_before'),
        'saved_blender_input_mode_after': extraction.get('writer_input_mode_after'),
        'writer_input_object_mode_canonicalized': extraction.get('writer_input_object_mode_canonicalized'),
        'non_position_semantic_state_pass': extraction.get('non_position_semantic_state_pass'),
        'max_uv_state_delta': extraction.get('max_uv_state_delta'),
        'max_physique_weight_delta': extraction.get('max_physique_weight_delta'),
        'all_non_authorized_bytes_byte_identical': compare['all_non_authorized_bytes_byte_identical'],
        'all_affected_object_bounds_byte_identical': compare['all_affected_object_bounds_byte_identical'],
        'bounds_header_byte_identical_by_object': compare['bounds_header_byte_identical_by_object'],
        'binary_diff_byte_count': compare['diff_byte_count'],
        'blender_reimport_pass': rebuilt['blender_reimport_pass'],
        'transport_pass': rebuilt['transport_pass'],
        'transport_position_error': rebuilt['transport_position_error'],
        'transport_uv_error': rebuilt['transport_uv_error'],
        'physique_mismatch_count': rebuilt['physique_mismatch_count'],
        'all_object_transaction_witness_pass': rebuilt['all_object_transaction_witness_pass'],
        'per_object_transaction_witness': rebuilt['per_object_transaction_witness'],
        'transaction_atomic': True,
        'atomic_candidate_publish': patch['atomic_output_replace'],
        'output_smd': str(output),
        'output_sha256': _sha256(output),
        'candidate_only': True,
        'certification_written': False,
    }


def _production_extractor_still_blocks(
    *, root: pathlib.Path, settings: Settings, blend: pathlib.Path,
    baseline: pathlib.Path, work: pathlib.Path,
) -> tuple[bool, str, dict[str, Any] | None]:
    report = work / 'production_extract.json'
    script = root / 'pt_asset_tool/blender/extract_rare_rigid_edit.py'
    cmd = settings.blender_command() + [
        '--background', str(blend), '--python-exit-code', '1', '--python', str(script), '--',
        '--baseline', str(baseline), '--report', str(report), '--max-changed', '8',
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'production_extractor_control.log').write_text(proc.stdout or '', encoding='utf-8')
    data = _json(report) if report.is_file() else None
    blocked = bool(
        proc.returncode != 0 and data
        and 'MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED' in (data.get('errors') or [])
        and len(data.get('changed_object_indices') or []) >= 2
    )
    return blocked, (proc.stdout or '')[-4000:], data


def _float32_fixed_roundtrip(q: int) -> int:
    # Blender mesh coordinates are stored as float32. Emulate that storage so
    # the negative witness itself never fails before the bounds guard is reached.
    f32 = struct.unpack('<f', struct.pack('<f', float(q) / 256.0))[0]
    return int(round(float(f32) * 256.0))


def _exact_out_of_bounds_x(prepared: pathlib.Path, object_index: int, sign: int = 1) -> int:
    model = _parse_with_offsets(prepared)
    obj = model['objects'][int(object_index)]
    sb = obj['stored_bounds']
    # maxX is itself in fixed-point units. Choose a point comfortably outside
    # the stored envelope, then advance only until float32 preserves the exact
    # fixed integer. This keeps the negative physical, deterministic and small.
    minimum = abs(int(sb['maxX'])) + 256
    for q_abs in range(minimum, minimum + 4096):
        q = q_abs if sign >= 0 else -q_abs
        if _float32_fixed_roundtrip(q) == q:
            return q
    raise RuntimeError(f'NO_EXACT_FLOAT32_OUT_OF_BOUNDS_X:{object_index}:{minimum}')


def _negative_saved_blender(
    *, root: pathlib.Path, settings: Settings, base_blend: pathlib.Path,
    prepared: pathlib.Path, skeleton: pathlib.Path, manifest: dict[str, Any], resolver: ClientResolver,
    source: pathlib.Path, transaction: dict[str, Any], work: pathlib.Path,
) -> tuple[bool, str]:
    bad = json.loads(json.dumps(transaction))
    last = bad['per_object_plans'][-1]
    row = last['changed_vertices'][0]
    current = [int(x) for x in row['requested_after_world_fixed']]
    sign = 1 if current[0] >= 0 else -1
    bad_x = _exact_out_of_bounds_x(prepared, int(last['object_index']), sign)
    row['requested_after_world_fixed'] = [bad_x, current[1], current[2]]
    # Keep the negative outside the stored X envelope while guaranteeing Blender
    # float32 can round-trip the fixed integer exactly. The candidate writer must
    # then reject it at the unchanged extent/bounds guard, not in transport setup.
    out_blend = work / 'negative_cross_object.blend'
    _apply_saved_blender(
        root=root, settings=settings, base_blend=base_blend,
        transaction=bad, out_blend=out_blend, work=work / 'apply',
    )
    output = work / 'negative_should_not_exist.smd'
    try:
        _candidate_write_from_saved_blend(
            root=root, settings=settings, source=source, prepared=prepared, skeleton=skeleton,
            manifest=manifest, resolver=resolver, blend=out_blend, expected=bad,
            output=output, work=work / 'candidate',
        )
    except Exception as exc:
        output.unlink(missing_ok=True)
        return True, f'{type(exc).__name__}:{exc}'
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
    prior_failed = _prior_v0824_failure(root)
    policy = load_and_validate_policy(root)
    policy_path = root / POLICY_REL
    policy_sha_before = _sha256(policy_path)
    if int(policy.get('production_max_vertices', -1)) != 8 or policy.get('single_object_only') is not True:
        raise RuntimeError('V0821_PRODUCTION_POLICY_SCOPE_UNEXPECTED')

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0823')

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
        workspace_root=workspace, workspace_origin='AUDIT_V0823_SAVED_BLENDER_CROSS_OBJECT',
    )
    isolated_preview = isolated_cert.records()
    if len(isolated_preview) != 1 or isolated_preview[0].get('test') != 'RARE_RIGID_BLENDER_PREVIEW':
        raise RuntimeError(f'ISOLATED_PREVIEW_CERT_UNEXPECTED:{isolated_preview}')
    isolated_sha_after_preview = _cert_sha(isolated_cert)

    prepared = pathlib.Path(manifest['prepared_source'])
    skeleton = pathlib.Path(manifest['skeleton'])
    base_blend = pathlib.Path(manifest['edit_blend'])
    discovery = discover_cross_object_representatives(prepared, skeleton)
    if not discovery.get('complete'):
        raise RuntimeError(f'CROSS_OBJECT_REPRESENTATIVE_DISCOVERY_INCOMPLETE:{discovery}')
    _assert_representatives_match_prior(discovery, prior)

    prior_rows = {int(r['object_count']): r for r in prior.get('rows') or []}
    rows = []
    first_saved_blend = None
    for count in PROBE_OBJECT_COUNTS:
        tx = discovery['representatives'][f'objects_{count}']
        row_root = work / f'objects_{count}'
        saved_blend = row_root / f'cross_object_{count}_saved.blend'
        apply = _apply_saved_blender(
            root=root, settings=settings, base_blend=base_blend,
            transaction=tx, out_blend=saved_blend, work=row_root / 'apply',
        )
        if first_saved_blend is None:
            first_saved_blend = saved_blend
        out_smd = row_root / f'cross_object_saved_candidate_{count}.smd'
        candidate = _candidate_write_from_saved_blend(
            root=root, settings=settings, source=source, prepared=prepared, skeleton=skeleton,
            manifest=manifest, resolver=resolver, blend=saved_blend, expected=tx,
            output=out_smd, work=row_root / 'candidate',
        )
        prior_sha = str(prior_rows[count]['output_sha256'])
        if candidate['output_sha256'] != prior_sha:
            raise RuntimeError(
                f'V0823_OUTPUT_DIFFERS_FROM_V0822_OBJECTS_{count}:{candidate["output_sha256"]}!={prior_sha}'
            )
        candidate.update({
            'saved_blender_apply_pass': True,
            'saved_blender_saved_mode_raw': apply['saved_mode_raw'],
            'saved_blender_saved_mode': apply['saved_mode'],
            'saved_blender_objects_in_mode': apply['objects_in_mode'],
            'matches_v0822_output_sha256': True,
        })
        rows.append(candidate)

    assert first_saved_blend is not None
    prod_blocked, prod_error, prod_extract = _production_extractor_still_blocks(
        root=root, settings=settings, blend=first_saved_blend,
        baseline=pathlib.Path(manifest['baseline_blender_report']),
        work=work / 'production_control',
    )
    if not prod_blocked:
        raise RuntimeError(f'PRODUCTION_MULTI_OBJECT_EXTRACTION_NOT_BLOCKED:{prod_error}:{prod_extract}')

    negative_blocked, negative_error = _negative_saved_blender(
        root=root, settings=settings, base_blend=base_blend,
        prepared=prepared, skeleton=skeleton, manifest=manifest, resolver=resolver,
        source=source, transaction=discovery['representatives']['objects_2'],
        work=work / 'negative_partial_failure',
    )
    if not negative_blocked:
        raise RuntimeError('NEGATIVE_SAVED_BLENDER_PARTIAL_FAILURE_NOT_BLOCKED')

    if _cert_sha(isolated_cert) != isolated_sha_after_preview or len(isolated_cert.records()) != 1:
        raise RuntimeError('CANDIDATE_WROTE_CERTIFICATION_IN_ISOLATED_REGISTRY')

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    policy_sha_after = _sha256(policy_path)
    writer_unchanged = writers_before == writers_after == EXPECTED_WRITER_HASHES
    client_unchanged = source_sha_before == source_sha_after
    cert_unchanged = real_count_before == real_count_after and real_sha_before == real_sha_after
    policy_unchanged = policy_sha_before == policy_sha_after
    if not all([writer_unchanged, client_unchanged, cert_unchanged, policy_unchanged]):
        raise RuntimeError('V0823_SIDE_EFFECT_DETECTED')

    return {
        'format': FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'base_release': '0.8.24-failed-negative-quantization-fix',
        'prior_v0824_failure_understood': True,
        'prior_v0824_failure_error': str(prior_failed.get('error')),
        'negative_quantization_fix': 'saved-Blender partial-failure witness now chooses the first float32-exact fixed X coordinate outside the physical stored maxX envelope; writer bounds thresholds are unchanged',
        'extractor_bootstrap_fix_retained': True,
        'logical': TARGET,
        'prior_v0822_gate_pass': True,
        'representatives_match_v0822': True,
        'candidate_object_counts': list(PROBE_OBJECT_COUNTS),
        'candidate_max_total_changed_vertices': CANDIDATE_MAX_CHANGED,
        'rows': rows,
        'production_cross_object_still_blocked': True,
        'production_cross_object_extraction_error': prod_error,
        'production_cross_object_output_created': False,
        'negative_saved_blender_partial_failure_blocked': True,
        'negative_saved_blender_partial_failure_error': negative_error,
        'negative_output_created': False,
        'isolated_preview_certification_count': 1,
        'isolated_candidate_certification_count_after': len(isolated_cert.records()),
        'candidate_certification_written': False,
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
        'production_single_object_max_vertices': 8,
        'cross_object_live_write_authorized': False,
        'policy': {
            'scope': 'isolated saved-Blender cross-object candidate for 2 and 3 at_dragon mesh objects; two changed vertices per object; interior only',
            'saved_blender': 'all affected mesh objects are physically saved together in Blender multi-object EDIT_MESH, then a candidate-only extractor canonicalizes to OBJECT and re-derives the changed vertices',
            'binary_equivalence': 'candidate outputs must be byte-identical by SHA-256 to the corresponding V0.8.22 audit-only probe outputs',
            'production': 'the existing production extractor must continue rejecting the same saved multi-object .blend with MULTI_OBJECT_VERTEX_TRANSACTION_DEFERRED',
            'atomicity': 'all extracted per-object plans must pass before the combined SMD is atomically published; a saved-Blender partial-failure negative must produce zero output',
            'certification': 'workspace preview uses an isolated registry; candidate writes append no certification records; real registry and V0.8.21 production policy remain byte-identical',
            'authorization': 'PASS is saved-Blender cross-object candidate evidence only; no production cross-object authorization is added',
            'next_on_pass': 'build V0.8.26 isolated live-writer cross-object candidate before manual artist proof or production promotion',
            'deferred': 'production cross-object writes, extent/bounds changes, topology and >8 total changed vertices remain fail-closed',
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.25 saved-Blender cross-object negative quantization fix')
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
            'rare_rigid_cross_object_saved_blender_candidate=PASS '
            'object_counts=2,3 production_single_object_max=8 cross_object_authorized=false client_modified=false'
        )
        return 0
    print('rare_rigid_cross_object_saved_blender_candidate=FAIL')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
