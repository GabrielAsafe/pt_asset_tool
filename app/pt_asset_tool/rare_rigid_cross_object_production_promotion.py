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
from .rare_rigid_edit import prepare_at_dragon_edit_workspace
from .rare_rigid_large_production import POLICY_REL as SINGLE_POLICY_REL, load_and_validate_policy
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES, _safe_rows
from .rare_rigid_multibone_bridge import TARGET
from .rare_rigid_cross_object_live_writer_candidate import (
    _cert_sha,
    _writer_hashes,
    run as run_live_candidate,
    write_at_dragon_cross_object_candidate_workspace,
    _install_transaction_into_workspace,
)
from .rare_rigid_cross_object_production import (
    POLICY_FORMAT,
    POLICY_REL,
    MANUAL_REL,
    LIVE_REL,
    PROMOTED_TEST,
    PROMOTED_SCOPE,
    ALLOWED_OBJECT_COUNTS,
    VERTICES_PER_OBJECT,
    MAX_TOTAL_CHANGED,
    _CrossObjectProductionCertificationProxy,
)

RELEASE_VERSION = '0.8.30'
FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_PRODUCTION_PROMOTION_AUDIT_V2'



PRIOR_FAIL_REL = pathlib.Path('pt_build/rare_rigid_cross_object_production_promotion_workflow_v0829.json')
LEGACY_POLICY_REL = pathlib.Path('pt_build/rare_rigid_cross_object_production_policy_v0829.json')


def _strict_v0829_failure(root: pathlib.Path) -> dict[str, Any]:
    p = pathlib.Path(root) / PRIOR_FAIL_REL
    if not p.is_file():
        raise RuntimeError(f'V0829_FAILURE_REPORT_MISSING:{p}')
    r = _json(p)
    err = str(r.get('error') or '')
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_PRODUCTION_PROMOTION_AUDIT_V1',
        r.get('status') == 'FAIL',
        r.get('release_version') == '0.8.29',
        r.get('logical') == TARGET,
        "FileNotFoundError:[Errno 2] No such file or directory:" in err,
        'v0826_live_regression.json' in err,
        r.get('cross_object_live_write_authorized') is False,
        int(r.get('production_single_object_max_vertices', -1)) == 8,
    ]
    if not all(checks):
        raise RuntimeError(f'V0829_FAILURE_NOT_EXPECTED_REGRESSION_REPORT_BUG:{r}')
    return r


def _write_json_atomic(path: pathlib.Path, report: dict[str, Any]) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + '.staging')
    staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    staging.replace(path)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _strict_manual(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = root / MANUAL_REL
    if not p.is_file():
        raise RuntimeError(f'V0828_MANUAL_REPORT_MISSING:{p}')
    r = _json(p)
    per = {str(k): [int(x) for x in v] for k, v in (r.get('per_object_changed_vertex_indices') or {}).items()}
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_INTERACTIVE_CANDIDATE_MANUAL_WRITE_V1',
        r.get('status') == 'PASS',
        r.get('release_version') == '0.8.28',
        r.get('manual_artist_proof') is True,
        r.get('prior_v0827_failure_understood') is True,
        int(r.get('object_count', -1)) == 2,
        sorted(int(x) for x in (r.get('object_indices') or [])) == [0, 5],
        int(r.get('artist_changed_vertices', -1)) == 4,
        sorted(len(v) for v in per.values()) == [2, 2],
        r.get('visible_selection_persisted') is True,
        r.get('popup_used') is False,
        r.get('all_non_authorized_bytes_byte_identical') is True,
        r.get('all_affected_object_bounds_byte_identical') is True,
        float(r.get('transport_position_error', 1.0)) == 0.0,
        float(r.get('transport_uv_error', 1.0)) == 0.0,
        int(r.get('physique_mismatch_count', -1)) == 0,
        r.get('all_object_transaction_witness_pass') is True,
        r.get('transaction_atomic') is True,
        r.get('atomic_output_replace') is True,
        r.get('candidate_certification_isolated') is True,
        r.get('production_exact_core_writer_cross_object_blocked') is True,
        r.get('real_certification_registry_modified') is False,
        r.get('production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
        int(r.get('production_single_object_max_vertices', -1)) == 8,
        r.get('cross_object_live_write_authorized') is False,
        r.get('ready_for_cross_object_promotion_gate') is True,
    ]
    if not all(checks):
        raise RuntimeError('V0828_MANUAL_REPORT_NOT_STRICT_PASS')
    out = pathlib.Path(str(r.get('output_smd') or ''))
    if not out.is_file() or _sha256(out) != r.get('output_sha256'):
        raise RuntimeError('V0828_MANUAL_OUTPUT_HASH_MISMATCH')
    return r, p


def _strict_live(root: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    p = root / LIVE_REL
    if not p.is_file():
        raise RuntimeError(f'V0826_LIVE_REPORT_MISSING:{p}')
    r = _json(p)
    rows = list(r.get('rows') or [])
    checks = [
        r.get('format') == 'PT_RARE_RIGID_CROSS_OBJECT_LIVE_WRITER_CANDIDATE_AUDIT_V1',
        r.get('status') == 'PASS', r.get('release_version') == '0.8.26',
        list(r.get('candidate_object_counts') or []) == [2, 3],
        list(r.get('candidate_total_changed_vertices') or []) == [4, 6],
        int(r.get('candidate_max_total_changed_vertices', -1)) == 8,
        int(r.get('candidate_vertices_per_object', -1)) == 2,
        len(rows) == 2 and all(x.get('status') == 'PASS' for x in rows),
        all(x.get('matches_v0825_output_sha256') is True for x in rows),
        r.get('production_exact_core_writer_cross_object_blocked') is True,
        r.get('negative_bounds_blocked') is True,
        r.get('nine_vertex_blocked') is True,
        r.get('real_certification_registry_modified') is False,
        r.get('production_policy_modified') is False,
        r.get('writer_modules_modified') is False,
        r.get('client_modified') is False,
        r.get('process_local_limits_restored_to_4') is True,
        int(r.get('production_single_object_max_vertices', -1)) == 8,
        r.get('cross_object_live_write_authorized') is False,
        r.get('manual_artist_proof_required_before_cross_object_authorization') is True,
    ]
    if not all(checks):
        raise RuntimeError('V0826_LIVE_REPORT_NOT_STRICT_PASS')
    return r, p


def _transport_only_shape(safe: dict[int, list[dict[str, Any]]], object_vertices: dict[int, int]) -> dict[str, Any]:
    plans = []
    for oi, n in object_vertices.items():
        rows = list(safe.get(int(oi)) or [])
        unique = []
        seen = set()
        for row in rows:
            vi = int(row['vertex_index'])
            if vi in seen:
                continue
            seen.add(vi)
            unique.append(row)
            if len(unique) == n:
                break
        if len(unique) != n:
            raise RuntimeError(f'NEGATIVE_SHAPE_NOT_ENOUGH_SAFE_VERTICES_OBJECT_{oi}:{len(unique)}<{n}')
        plans.append({
            'object_index': int(oi),
            'changed_vertices': [
                {
                    'object_index': int(oi),
                    'vertex_index': int(row['vertex_index']),
                    'before_world_fixed': [int(x) for x in row['before_world_fixed']],
                    'requested_after_world_fixed': [int(x) for x in row['requested_after_world_fixed']],
                }
                for row in unique
            ],
        })
    return {
        'object_count': len(plans),
        'object_indices': sorted(object_vertices),
        'total_changed_vertices': sum(object_vertices.values()),
        'per_object_plans': plans,
    }


def _expect_candidate_block(
    *, root: pathlib.Path, settings: Settings, reg: AssetRegistry, resolver: ClientResolver,
    cert: CertificationRegistry, workspace: pathlib.Path, pristine_blend: pathlib.Path,
    manifest: dict[str, Any], tx: dict[str, Any], label: str, expected_substring: str, out: pathlib.Path,
) -> str:
    _install_transaction_into_workspace(
        root=root, settings=settings, pristine_blend=pristine_blend,
        manifest=manifest, transaction=tx, workspace=workspace, label=label,
    )
    before = len(cert.records())
    out.unlink(missing_ok=True)
    try:
        write_at_dragon_cross_object_candidate_workspace(
            reg, resolver, cert, settings,
            project_root=root, workspace_root=workspace, output=out,
        )
    except Exception as exc:
        err = f'{type(exc).__name__}:{exc}'
    else:
        raise RuntimeError(f'{label.upper()}_UNEXPECTED_PASS')
    if expected_substring not in err:
        raise RuntimeError(f'{label.upper()}_WRONG_ERROR:{err}')
    if out.exists() or len(cert.records()) != before:
        raise RuntimeError(f'{label.upper()}_CREATED_OUTPUT_OR_CERT')
    return err


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)

    # Every promotion attempt begins deauthorized.  A stale policy must never survive
    # a failed revalidation.
    policy_path = root / POLICY_REL
    policy_path.unlink(missing_ok=True)
    # V0.8.29 never reached policy creation, but remove any stale/hand-created legacy
    # policy as well so this corrective gate always begins cross-object deauthorized.
    (root / LEGACY_POLICY_REL).unlink(missing_ok=True)

    prior_v0829 = _strict_v0829_failure(root)
    manual, manual_path = _strict_manual(root)
    live, live_path = _strict_live(root)
    single_policy = load_and_validate_policy(root)
    single_policy_path = root / SINGLE_POLICY_REL
    single_policy_sha_before = _sha256(single_policy_path)
    if int(single_policy.get('production_max_vertices', -1)) != 8 or single_policy.get('single_object_only') is not True:
        raise RuntimeError('V0821_SINGLE_OBJECT_POLICY_SCOPE_UNEXPECTED')

    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0829')
    settings = Settings.discover(root, None)
    resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir)
    real_count_before = len(real_cert.records())
    real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True))
    source_sha_before = _sha256(source)
    if source_sha_before != single_policy.get('client_source_sha256'):
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0821_POLICY')

    # Re-run the complete isolated live-writer candidate as a physical regression.
    rerun_path = work / 'v0826_live_regression.json'
    rerun = run_live_candidate(root, rerun_path)
    if rerun.get('status') != 'PASS' or list(rerun.get('candidate_object_counts') or []) != [2, 3]:
        raise RuntimeError('V0830_LIVE_CANDIDATE_REGRESSION_FAILED')
    # run_live_candidate() is a library function: unlike its CLI main(), it returns
    # the report but does not persist --output.  V0.8.29 incorrectly assumed the
    # path existed and failed while hashing it.  Persist the returned evidence
    # atomically, then read it back before it becomes hash-bound promotion evidence.
    _write_json_atomic(rerun_path, rerun)
    if not rerun_path.is_file() or _json(rerun_path) != rerun:
        raise RuntimeError('V0830_LIVE_REGRESSION_REPORT_PERSISTENCE_MISMATCH')

    # Reproduce the actual V0.8.28 artist workspace with the exact candidate core,
    # but route the certification through the production relabel proxy in isolation.
    manual_work = root / 'pt_build/rare_rigid_cross_object_manual_candidate_v0828/at_dragon.smd/isolated_artist_workspace'
    if not (manual_work / 'workspace_manifest.json').is_file():
        raise RuntimeError('V0828_MANUAL_WORKSPACE_MISSING')
    isolated = CertificationRegistry(work / 'isolated_promotion_certifications')
    proxy = _CrossObjectProductionCertificationProxy(isolated)
    reproduced = work / 'manual_reproduced_promoted_core.smd'
    repro = write_at_dragon_cross_object_candidate_workspace(
        reg, resolver, proxy, settings,
        project_root=root, workspace_root=manual_work, output=reproduced,
    )
    if _sha256(reproduced) != manual.get('output_sha256'):
        raise RuntimeError('V0828_MANUAL_REPRODUCTION_OUTPUT_SHA_MISMATCH')
    promoted_records = [x for x in isolated.records() if x.get('test') == PROMOTED_TEST]
    if len(promoted_records) != 1:
        raise RuntimeError(f'PROMOTED_CERTIFICATION_PROXY_NOT_EXACTLY_ONE:{promoted_records}')

    # Fresh isolated workspace for unsupported-shape physical negatives.
    neg_cert = CertificationRegistry(work / 'isolated_negative_certifications')
    neg_workspace = work / 'negative_workspace'
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, neg_cert, settings, project_root=root, open_gui=False, reset=True,
        workspace_root=neg_workspace, workspace_origin='AUDIT_V0829_CROSS_OBJECT_PRODUCTION_PROMOTION',
    )
    edit_blend = pathlib.Path(manifest['edit_blend'])
    pristine = work / 'negative_pristine.blend'; shutil.copy2(edit_blend, pristine)
    safe, _ = _safe_rows(pathlib.Path(manifest['prepared_source']), pathlib.Path(manifest['skeleton']))

    # 2 objects but a 3+1 vertex distribution must remain unauthorized.
    shape_3plus1 = _transport_only_shape(safe, {0: 3, 5: 1})
    err_shape = _expect_candidate_block(
        root=root, settings=settings, reg=reg, resolver=resolver, cert=neg_cert,
        workspace=neg_workspace, pristine_blend=pristine, manifest=manifest,
        tx=shape_3plus1, label='negative_shape_3plus1',
        expected_substring='REQUIRES_EXACTLY_TWO_VERTICES_PER_OBJECT',
        out=work/'negative_shape_3plus1_should_not_exist.smd',
    )

    # Four objects / eight total vertices must remain unauthorized despite total<=8.
    shape_4objects = _transport_only_shape(safe, {0: 2, 1: 2, 5: 2, 8: 2})
    err_4objects = _expect_candidate_block(
        root=root, settings=settings, reg=reg, resolver=resolver, cert=neg_cert,
        workspace=neg_workspace, pristine_blend=pristine, manifest=manifest,
        tx=shape_4objects, label='negative_four_objects',
        expected_substring='CROSS_OBJECT_CANDIDATE_EXTRACTION_FAILED',
        out=work/'negative_four_objects_should_not_exist.smd',
    )

    writers_after = _writer_hashes(root)
    source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records())
    real_sha_after = _cert_sha(real_cert)
    single_policy_sha_after = _sha256(single_policy_path)
    if writers_after != writers_before or writers_after != EXPECTED_WRITER_HASHES:
        raise RuntimeError('V0830_WRITER_MODULES_CHANGED')
    if source_sha_after != source_sha_before:
        raise RuntimeError('V0830_CLIENT_CHANGED')
    if real_count_after != real_count_before or real_sha_after != real_sha_before:
        raise RuntimeError('V0830_REAL_CERTIFICATION_REGISTRY_CHANGED')
    if single_policy_sha_after != single_policy_sha_before:
        raise RuntimeError('V0830_SINGLE_OBJECT_POLICY_CHANGED')

    policy = {
        'format': POLICY_FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'logical': TARGET,
        'cross_object_production_authorized': True,
        'prior_v0829_failure_understood': True,
        'prior_v0829_failure_error': str(prior_v0829.get('error') or ''),
        'allowed_object_counts': list(ALLOWED_OBJECT_COUNTS),
        'vertices_per_object': VERTICES_PER_OBJECT,
        'max_total_changed_vertices': MAX_TOTAL_CHANGED,
        'interior_only': True,
        'manual_artist_proof': True,
        'manual_report_sha256': _sha256(manual_path),
        'manual_output_sha256': manual.get('output_sha256'),
        'live_writer_candidate_proof': True,
        'live_report_sha256': _sha256(live_path),
        'live_regression_report_sha256': _sha256(rerun_path),
        'single_object_policy_sha256': single_policy_sha_after,
        'client_source_sha256': source_sha_after,
        'writer_hashes': writers_after,
        'unsupported_3plus1_blocked': True,
        'unsupported_four_objects_blocked': True,
        'nine_vertex_blocked': rerun.get('nine_vertex_blocked') is True,
        'bounds_negative_blocked': rerun.get('negative_bounds_blocked') is True,
        'extent_bounds_changes_authorized': False,
        'topology_authorized': False,
        'more_than_3_objects_authorized': False,
        'other_vertices_per_object_shapes_authorized': False,
        'more_than_8_total_vertices_authorized': False,
        'policy': {
            'writer': 'V0.8.26 exact candidate writer core promoted only through a strict V0.8.30 policy/certification proxy; certified V0.8.9 writers remain byte-identical',
            'scope': 'at_dragon interior cross-object transactions: exactly 2 or 3 mesh objects and exactly 2 changed vertices per object; total 4 or 6',
            'single_object': 'V0.8.21 production policy remains authoritative for 1..8 changed vertices inside one mesh object',
            'deferred': 'extent/bounds changes, topology, >3 objects, any other vertices-per-object shape and >8 total vertices remain fail-closed',
        },
    }
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    staging = policy_path.with_suffix(policy_path.suffix + '.staging')
    staging.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    staging.replace(policy_path)

    return {
        'format': FORMAT,
        'status': 'PASS',
        'release_version': RELEASE_VERSION,
        'logical': TARGET,
        'prior_v0829_failure_understood': True,
        'prior_v0829_failure_error': str(prior_v0829.get('error') or ''),
        'manual_v0828_strict_pass': True,
        'manual_object_count': 2,
        'manual_changed_vertices': 4,
        'manual_output_reproduced_byte_identical': True,
        'live_v0826_strict_pass': True,
        'live_candidate_regression_pass': True,
        'live_regression_report_persisted': True,
        'live_regression_report': str(rerun_path),
        'live_regression_report_sha256': _sha256(rerun_path),
        'live_candidate_object_counts': [2, 3],
        'live_candidate_total_changed_vertices': [4, 6],
        'unsupported_3plus1_blocked': True,
        'unsupported_3plus1_error': err_shape,
        'unsupported_four_objects_blocked': True,
        'unsupported_four_objects_error': err_4objects,
        'nine_vertex_blocked': True,
        'bounds_negative_blocked': True,
        'real_certification_count_before': real_count_before,
        'real_certification_count_after': real_count_after,
        'real_certification_registry_modified': False,
        'single_object_policy_modified': False,
        'writer_modules_modified': False,
        'client_modified': False,
        'cross_object_production_policy_written': True,
        'cross_object_production_policy': str(policy_path),
        'cross_object_live_write_authorized': True,
        'production_single_object_max_vertices': 8,
        'production_cross_object_allowed_object_counts': [2, 3],
        'production_cross_object_vertices_per_object': 2,
        'production_cross_object_total_changed_vertices': [4, 6],
        'production_scope': 'single-object 1..8 via V0.8.21; cross-object exactly 2x2 or 3x2 interior via V0.8.30',
        'deferred': ['extent/bounds changes', 'topology', '>3 objects', 'other vertices-per-object shapes', '>8 total changed vertices'],
        'writer_hashes': writers_after,
        'client_source_sha256': source_sha_after,
        'next': 'cross-object exact proven shapes are production-authorized; next roadmap milestone is multi-bone outward extent research',
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.30 cross-object production-promotion gate')
    ap.add_argument('--root', required=True)
    ap.add_argument('--output', required=True)
    ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            'format': FORMAT, 'status': 'FAIL', 'release_version': RELEASE_VERSION,
            'logical': TARGET, 'error': f'{type(exc).__name__}:{exc}',
            'cross_object_live_write_authorized': False,
            'production_single_object_max_vertices': 8,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get('status') == 'PASS':
        print('rare_rigid_cross_object_production_promotion=PASS single_object_max=8 cross_object_shapes=2x2,3x2 extent=false topology=false client_modified=false')
        return 0
    print('rare_rigid_cross_object_production_promotion=FAIL')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
