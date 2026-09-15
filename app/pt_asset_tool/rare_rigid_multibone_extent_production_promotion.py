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
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_multibone_extent_live_writer_candidate import (
    CANDIDATE_TEST,
    TARGET_KINDS,
    run as run_live_candidate,
    write_at_dragon_multibone_outward_extent_candidate_workspace,
)
from .rare_rigid_multibone_extent_production import (
    POLICY_FORMAT,
    POLICY_REL,
    MANUAL_REL,
    LIVE_REL,
    SAVED_REL,
    PROMOTED_TEST,
    PROMOTED_SCOPE,
    ALLOWED_TARGET_KINDS,
    ALLOWED_FIELD_SHAPES,
    _MultiboneExtentProductionCertificationProxy,
    load_and_validate_extent_policy,
)

RELEASE_VERSION = '0.8.36'
FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_PRODUCTION_PROMOTION_AUDIT_V1'
EXPECTED_MANUAL_SHA256 = '00ac502551c9f5eca95a294605a478d76f3d026a2afaf176813269b35c712297'
MANUAL_WORK_REL = pathlib.Path('pt_build/rare_rigid_multibone_outward_extent_manual_candidate_v0835/at_dragon.smd/isolated_artist_workspace')


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _write_json_atomic(path: pathlib.Path, report: dict[str, Any]) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + '.staging')
    staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    staging.replace(path)


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(pathlib.Path(root) / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(reg: CertificationRegistry) -> str:
    return _sha256(reg.path) if reg.path.is_file() else hashlib.sha256(b'').hexdigest()


def _strict_manual(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = pathlib.Path(root) / MANUAL_REL
    if not p.is_file():
        raise RuntimeError(f'V0835_MANUAL_REPORT_MISSING:{p}')
    r = _json(p)
    checks = [
        r.get('format') == 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
        r.get('status') == 'PASS',
        r.get('release_version') == '0.8.35',
        r.get('logical') == TARGET,
        r.get('manual_artist_proof') is True,
        r.get('prior_v0834_failure_understood') is True,
        r.get('manual_friendly_delta_prevalidated') is True,
        r.get('target_bound_kind') == 'maxX',
        int(r.get('object_index', -1)) == 8,
        int(r.get('vertex_index', -1)) == 30,
        int(r.get('artist_changed_vertices', -1)) == 1,
        r.get('manual_axis') == 'x',
        int(r.get('manual_delta_world_fixed', 0)) == 64,
        float(r.get('manual_delta_world', 0.0)) == 0.25,
        r.get('visible_selection_persisted') is True,
        r.get('popup_used') is False,
        list(r.get('changed_bound_fields') or []) == ['maxX'],
        int(r.get('affected_bone_count', -1)) == 2,
        list(r.get('affected_bones') or []) == ['Bip01 L Calf', 'Bip01 L Foot'],
        r.get('all_non_authorized_bytes_byte_identical') is True,
        r.get('bound_window_non_field_bytes_byte_identical') is True,
        float(r.get('transport_position_error', 1.0)) == 0.0,
        float(r.get('transport_uv_error', 1.0)) == 0.0,
        r.get('witness_check') == 'PASS',
        r.get('transaction_atomic') is True,
        r.get('atomic_output_replace') is True,
        r.get('manual_output_matches_prevalidated_friendly_delta_plan') is True,
        r.get('manual_output_differs_from_v0833_reference') is True,
        r.get('candidate_certification_test') == CANDIDATE_TEST,
        r.get('candidate_certification_isolated') is True,
        r.get('production_extent_still_blocked') is True,
        'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' in str(r.get('production_extent_error') or ''),
        r.get('production_extent_output_created') is False,
        r.get('real_certification_registry_modified') is False,
        r.get('single_object_production_policy_modified') is False,
        r.get('cross_object_production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
        r.get('output_sha256') == EXPECTED_MANUAL_SHA256,
        r.get('multibone_outward_extent_live_write_authorized') is False,
        r.get('extent_contraction_write_authorized') is False,
        r.get('multi_vertex_extent_write_authorized') is False,
        r.get('cross_object_extent_write_authorized') is False,
        r.get('topology_write_authorized') is False,
        r.get('ready_for_multibone_outward_extent_promotion_gate') is True,
    ]
    if not all(checks):
        raise RuntimeError('V0835_MANUAL_REPORT_NOT_STRICT_PASS')
    out = pathlib.Path(str(r.get('output_smd') or ''))
    if not out.is_file() or _sha256(out) != EXPECTED_MANUAL_SHA256:
        raise RuntimeError('V0835_MANUAL_OUTPUT_HASH_MISMATCH')
    return r, p


def _strict_live(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = pathlib.Path(root) / LIVE_REL
    if not p.is_file():
        raise RuntimeError(f'V0833_LIVE_REPORT_MISSING:{p}')
    r = _json(p)
    rows = list(r.get('rows') or [])
    by_kind = {str(x.get('target_bound_kind')): x for x in rows if x.get('status') == 'PASS'}
    checks = [
        r.get('format') == 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_LIVE_WRITER_CANDIDATE_AUDIT_V1',
        r.get('status') == 'PASS', r.get('release_version') == '0.8.33', r.get('logical') == TARGET,
        r.get('prior_v0832_strict_pass') is True, int(r.get('prior_v0832_witness_count', -1)) == 5,
        list(r.get('candidate_target_kinds') or []) == list(TARGET_KINDS), int(r.get('candidate_witness_count', -1)) == 5,
        r.get('exact_candidate_writer_function_exercised') == 'write_at_dragon_multibone_outward_extent_candidate_workspace',
        r.get('all_candidate_rows_pass') is True, set(by_kind) == set(TARGET_KINDS),
        r.get('all_live_writer_outputs_match_v0832') is True,
        int(r.get('isolated_candidate_certification_count', -1)) == 5,
        r.get('candidate_certification_test') == CANDIDATE_TEST,
        r.get('production_extent_still_blocked') is True, r.get('production_extent_output_created') is False,
        r.get('multi_vertex_extent_blocked') is True, r.get('multi_vertex_extent_output_created') is False,
        r.get('cross_object_extent_blocked') is True, r.get('cross_object_extent_output_created') is False,
        r.get('inward_no_extent_blocked') is True, r.get('inward_no_extent_output_created') is False,
        r.get('real_certification_registry_modified') is False,
        r.get('single_object_production_policy_modified') is False,
        r.get('cross_object_production_policy_modified') is False,
        r.get('writer_modules_modified') is False, r.get('client_modified') is False,
        r.get('multibone_outward_extent_live_write_authorized') is False,
        r.get('extent_contraction_write_authorized') is False,
        r.get('multi_vertex_extent_write_authorized') is False,
        r.get('cross_object_extent_write_authorized') is False,
        r.get('topology_write_authorized') is False,
        r.get('writer_hashes') == EXPECTED_WRITER_HASHES,
    ]
    if not all(checks):
        raise RuntimeError('V0833_LIVE_REPORT_NOT_STRICT_PASS')
    for kind, row in by_kind.items():
        if row.get('candidate_only') is not True or row.get('production_authorized') is not False or row.get('matches_v0832_output_sha256') is not True:
            raise RuntimeError(f'V0833_LIVE_ROW_NOT_STRICT_PASS:{kind}')
    return r, p


def _strict_saved(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = pathlib.Path(root) / SAVED_REL
    if not p.is_file():
        raise RuntimeError(f'V0832_SAVED_REPORT_MISSING:{p}')
    r = _json(p)
    checks = [
        r.get('format') == 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_SAVED_BLENDER_CANDIDATE_AUDIT_V1',
        r.get('status') == 'PASS', r.get('release_version') == '0.8.32', r.get('logical') == TARGET,
        int(r.get('candidate_witness_count', -1)) == 5,
        r.get('all_candidate_rows_pass') is True,
        r.get('all_saved_blender_outputs_match_v0831') is True,
        r.get('production_extent_still_blocked') is True,
        r.get('production_extent_output_created') is False,
        r.get('candidate_certification_written') is False,
        r.get('real_certification_registry_modified') is False,
        r.get('single_object_production_policy_modified') is False,
        r.get('cross_object_production_policy_modified') is False,
        r.get('writer_modules_modified') is False, r.get('client_modified') is False,
        r.get('multibone_outward_extent_live_write_authorized') is False,
    ]
    if not all(checks):
        raise RuntimeError('V0832_SAVED_REPORT_NOT_STRICT_PASS')
    return r, p


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # Every promotion attempt starts extent-deauthorized. A stale V0.8.36 policy
    # must never survive a failed physical revalidation.
    policy_path = root / POLICY_REL
    policy_path.unlink(missing_ok=True)

    manual, manual_path = _strict_manual(root)
    live, live_path = _strict_live(root)
    saved, saved_path = _strict_saved(root)
    single = load_and_validate_policy(root)
    cross = load_and_validate_cross_policy(root)
    single_path = root / SINGLE_POLICY_REL
    cross_path = root / CROSS_POLICY_REL
    single_sha_before = _sha256(single_path)
    cross_sha_before = _sha256(cross_path)
    if int(single.get('production_max_vertices', -1)) != 8 or single.get('single_object_only') is not True:
        raise RuntimeError('V0836_SINGLE_OBJECT_POLICY_SCOPE_UNEXPECTED')
    if cross.get('cross_object_production_authorized') is not True:
        raise RuntimeError('V0836_CROSS_OBJECT_POLICY_SCOPE_UNEXPECTED')

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('V0836_CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_PROMOTION')
    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real.records())
    real_sha_before = _cert_sha(real)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)

    # Re-run the complete V0.8.33 live candidate, including all physical negatives.
    rerun_path = work / 'v0833_live_regression.json'
    rerun = run_live_candidate(root, rerun_path)
    if rerun.get('status') != 'PASS' or int(rerun.get('candidate_witness_count', -1)) != 5:
        raise RuntimeError('V0836_LIVE_CANDIDATE_REGRESSION_FAILED')
    _write_json_atomic(rerun_path, rerun)
    if _json(rerun_path) != rerun:
        raise RuntimeError('V0836_LIVE_REGRESSION_REPORT_PERSISTENCE_MISMATCH')
    if not all([
        rerun.get('all_candidate_rows_pass') is True,
        rerun.get('all_live_writer_outputs_match_v0832') is True,
        rerun.get('production_extent_still_blocked') is True,
        rerun.get('multi_vertex_extent_blocked') is True,
        rerun.get('cross_object_extent_blocked') is True,
        rerun.get('inward_no_extent_blocked') is True,
        rerun.get('real_certification_registry_modified') is False,
        rerun.get('single_object_production_policy_modified') is False,
        rerun.get('cross_object_production_policy_modified') is False,
        rerun.get('writer_modules_modified') is False,
        rerun.get('client_modified') is False,
    ]):
        raise RuntimeError('V0836_LIVE_REGRESSION_STATE_NOT_STRICT_PASS')

    # Reproduce the real V0.8.35 artist-saved workspace with the exact candidate
    # writer core, but relabel certification through a production proxy in isolation.
    manual_work = root / MANUAL_WORK_REL
    if not (manual_work / 'workspace_manifest.json').is_file():
        raise RuntimeError('V0835_MANUAL_WORKSPACE_MISSING')
    isolated = CertificationRegistry(work / 'isolated_promotion_certifications')
    proxy = _MultiboneExtentProductionCertificationProxy(isolated)
    reproduced = work / 'manual_v0835_reproduced_promoted_core.smd'
    repro = write_at_dragon_multibone_outward_extent_candidate_workspace(
        reg, resolver, proxy, settings,
        project_root=root, workspace_root=manual_work, output=reproduced,
    )
    if _sha256(reproduced) != manual.get('output_sha256'):
        raise RuntimeError('V0835_MANUAL_REPRODUCTION_OUTPUT_SHA_MISMATCH')
    if repro.get('target_bound_kind') != 'maxX' or list(repro.get('changed_bound_fields') or []) != ['maxX']:
        raise RuntimeError('V0835_MANUAL_REPRODUCTION_FIELD_SHAPE_MISMATCH')
    promoted_records = [x for x in isolated.records() if x.get('test') == PROMOTED_TEST]
    if len(promoted_records) != 1:
        raise RuntimeError(f'V0836_PROMOTED_CERTIFICATION_PROXY_NOT_EXACTLY_ONE:{len(promoted_records)}')

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real.records())
    real_sha_after = _cert_sha(real)
    single_sha_after = _sha256(single_path)
    cross_sha_after = _sha256(cross_path)
    if writers_after != writers_before or writers_after != EXPECTED_WRITER_HASHES:
        raise RuntimeError('V0836_WRITER_MODULES_CHANGED')
    if source_sha_after != source_sha_before:
        raise RuntimeError('V0836_CLIENT_CHANGED')
    if real_count_after != real_count_before or real_sha_after != real_sha_before:
        raise RuntimeError('V0836_REAL_CERTIFICATION_REGISTRY_CHANGED')
    if single_sha_after != single_sha_before or cross_sha_after != cross_sha_before:
        raise RuntimeError('V0836_EXISTING_PRODUCTION_POLICY_CHANGED')

    serialized_shapes = {k: sorted(v) for k, v in ALLOWED_FIELD_SHAPES.items()}
    policy = {
        'format': POLICY_FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'logical': TARGET,
        'multibone_outward_extent_production_authorized': True,
        'one_object_only': True,
        'exactly_one_changed_vertex': True,
        'allowed_target_kinds': list(ALLOWED_TARGET_KINDS),
        'allowed_bound_field_shapes': serialized_shapes,
        'monotonic_expansion_only': True,
        'multibone_affected_normals_required': True,
        'manual_artist_proof': True,
        'manual_report_sha256': _sha256(manual_path),
        'manual_output_sha256': manual.get('output_sha256'),
        'manual_output_reproduced_byte_identical': True,
        'live_writer_candidate_proof': True,
        'live_report_sha256': _sha256(live_path),
        'live_regression_report_sha256': _sha256(rerun_path),
        'saved_blender_candidate_proof': True,
        'saved_report_sha256': _sha256(saved_path),
        'single_object_policy_sha256': single_sha_after,
        'cross_object_policy_sha256': cross_sha_after,
        'client_source_sha256': source_sha_after,
        'writer_hashes': writers_after,
        'production_extent_negative_before_promotion': rerun.get('production_extent_still_blocked') is True,
        'multi_vertex_extent_blocked': rerun.get('multi_vertex_extent_blocked') is True,
        'cross_object_extent_blocked': rerun.get('cross_object_extent_blocked') is True,
        'inward_no_expansion_not_routed_as_extent': rerun.get('inward_no_extent_blocked') is True,
        'extent_contraction_authorized': False,
        'multi_vertex_extent_authorized': False,
        'cross_object_extent_authorized': False,
        'topology_authorized': False,
        'policy': {
            'writer': 'V0.8.33 exact saved-workspace candidate core promoted only through a strict V0.8.36 evidence/hash-bound policy and production certification proxy; certified V0.8.9 writers remain byte-identical',
            'scope': 'at_dragon one mesh object, exactly one changed multi-bone affected vertex, monotonic outward expansion, exact five physically proven bound-field shapes only',
            'precedence': 'V0.8.21 single-object interior and V0.8.30 cross-object interior production paths stay authoritative; V0.8.36 is reached only after the existing path rejects specifically with EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED',
            'deferred': 'bound contraction, topology, multi-vertex extent composition, cross-object extent and unproven bound-field shapes remain fail-closed',
        },
    }
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    staging = policy_path.with_suffix(policy_path.suffix + '.staging')
    staging.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    staging.replace(policy_path)
    try:
        validated_policy = load_and_validate_extent_policy(root)
    except Exception:
        policy_path.unlink(missing_ok=True)
        raise
    if validated_policy.get('multibone_outward_extent_production_authorized') is not True:
        policy_path.unlink(missing_ok=True)
        raise RuntimeError('V0836_POSTWRITE_POLICY_VALIDATION_NOT_AUTHORIZED')

    return {
        'format': FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'logical': TARGET,
        'manual_v0835_strict_pass': True,
        'manual_target_bound_kind': 'maxX',
        'manual_object_index': 8,
        'manual_vertex_index': 30,
        'manual_delta_world': 0.25,
        'manual_output_sha256': manual.get('output_sha256'),
        'manual_output_reproduced_byte_identical': True,
        'live_v0833_strict_pass': True,
        'saved_v0832_strict_pass': True,
        'live_candidate_regression_pass': True,
        'live_regression_report_persisted': True,
        'live_regression_report': str(rerun_path),
        'live_regression_report_sha256': _sha256(rerun_path),
        'promoted_target_kinds': list(ALLOWED_TARGET_KINDS),
        'promoted_bound_field_shapes': serialized_shapes,
        'multi_vertex_extent_blocked': True,
        'cross_object_extent_blocked': True,
        'inward_no_extent_blocked': True,
        'extent_contraction_authorized': False,
        'multi_vertex_extent_authorized': False,
        'cross_object_extent_authorized': False,
        'topology_authorized': False,
        'real_certification_count_before': real_count_before,
        'real_certification_count_after': real_count_after,
        'real_certification_registry_modified': False,
        'single_object_policy_modified': False,
        'cross_object_policy_modified': False,
        'writer_modules_modified': False,
        'client_modified': False,
        'multibone_outward_extent_production_policy_written': True,
        'multibone_outward_extent_production_policy': str(policy_path),
        'multibone_outward_extent_live_write_authorized': True,
        'production_single_object_max_vertices': 8,
        'production_cross_object_allowed_shapes': ['2x2', '3x2'],
        'production_extent_scope': 'one object / exactly one changed multi-bone vertex / monotonic outward / exact proven field shapes: maxX, maxZ, maxY, dBound, and maxY+dBound+Bound',
        'deferred': ['extent contraction', 'topology', 'multi-vertex extent', 'cross-object extent', 'unproven bound-field shapes'],
        'writer_hashes': writers_after,
        'client_source_sha256': source_sha_after,
        'next': 'exact one-vertex multi-bone outward extent shapes are production-authorized; next roadmap milestone is multi-vertex outward extent composition research',
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.36 multi-bone outward extent production-promotion gate')
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
            'logical': TARGET,
            'error': f'{type(exc).__name__}:{exc}',
            'multibone_outward_extent_live_write_authorized': False,
            'production_single_object_max_vertices': 8,
            'production_cross_object_allowed_shapes': ['2x2', '3x2'],
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get('status') == 'PASS':
        print('rare_rigid_multibone_outward_extent_production_promotion=PASS single_object_max=8 cross_object_shapes=2x2,3x2 extent_one_vertex=true contraction=false multi_vertex_extent=false cross_object_extent=false client_modified=false')
        return 0
    print('rare_rigid_multibone_outward_extent_production_promotion=FAIL')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
