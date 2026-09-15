from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import shutil
import struct
from typing import Any

from .certification import CertificationRegistry
from .config import Settings
from .registry import AssetRegistry
from .resolver import ClientResolver
from .rare_rigid_cross_object_production import POLICY_REL as CROSS_POLICY_REL, load_and_validate_cross_policy
from .rare_rigid_edit import prepare_at_dragon_edit_workspace, _reimport_and_check, plan_requested_at_dragon_edit
from .rare_rigid_extent_bridge import BOUND_OFFSETS, _expanded_bounds, _bound_changes
from .rare_rigid_geometry import SV, _invert_matrix_source, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_large_transaction_probe import EXPECTED_WRITER_HASHES
from .rare_rigid_multibone_bridge import TARGET, _combo, SOURCE_NORMAL_DELTA_LIMIT_FIXED
from .rare_rigid_normal_bridge import (
    NORMAL_TARGET_REIMPORT_LIMIT_FIXED,
    POSITION_REIMPORT_LIMIT_FIXED,
    _build_source_normal_state,
    _face_normal_source,
    _i32_safe,
    _updated_current_for_affected,
    _world_hist_vector,
)
from .rare_rigid_roundtrip import _parse_with_offsets
from .rare_support import prepare_model062_tooling_source
from .utils import sha256_file

RELEASE_VERSION = '0.8.31'
FORMAT = 'PT_RARE_RIGID_MULTIBONE_OUTWARD_EXTENT_PROBE_AUDIT_V1'
TARGET_KINDS = ('maxX', 'maxZ', 'maxY', 'dBound', 'Bound')
# Search is ordered from the smallest exact outward expansion.  These are not
# validation tolerances and do not alter any certified normal/position guards.
AXIS_EXTRAS_FIXED = (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _writer_hashes(root: pathlib.Path) -> dict[str, str]:
    return {rel: _sha256(pathlib.Path(root) / rel) for rel in EXPECTED_WRITER_HASHES}


def _cert_sha(cert: CertificationRegistry) -> str:
    return _sha256(cert.path) if cert.path.is_file() else hashlib.sha256(b'').hexdigest()


def _bounds_cover_point(sb: dict[str, int], p: tuple[int, int, int]) -> bool:
    x, y, z = (int(p[0]), int(p[1]), int(p[2]))
    if abs(x) > int(sb['maxX']) or abs(y) > int(sb['maxZ']) or abs(z) > int(sb['maxY']):
        return False
    xx, yy, zz = x >> 8, y >> 8, z >> 8
    d = abs(xx * xx + yy * yy + zz * zz)
    return d <= int(sb['dBound']) and math.isqrt(d) <= int(sb['Bound'])


def _radial_axis_target(old: tuple[int, int, int], stored: dict[str, int], axis: int, require_bound: bool) -> int:
    units = [int(old[0]) >> 8, int(old[1]) >> 8, int(old[2]) >> 8]
    other = sum(units[i] * units[i] for i in range(3) if i != axis)
    target_d = int(stored['dBound']) + 1
    if require_bound:
        # Bound=trunc(sqrt(dBound)); require a radius that necessarily advances Bound.
        target_d = max(target_d, (int(stored['Bound']) + 1) ** 2)
    need = max(0, target_d - other)
    mag_units = math.isqrt(need)
    if mag_units * mag_units < need:
        mag_units += 1
    return int(mag_units) << 8


def _requested_candidates(old: tuple[int, int, int], stored: dict[str, int], kind: str):
    if kind in ('maxX', 'maxZ', 'maxY'):
        axis = {'maxX': 0, 'maxZ': 1, 'maxY': 2}[kind]
        start = max(int(stored[kind]) + 1, abs(int(old[axis])) + 1)
        for extra in AXIS_EXTRAS_FIXED:
            mag = start + int(extra)
            for sign in (1, -1):
                q = list(old); q[axis] = sign * mag
                yield tuple(int(x) for x in q)
        return

    require_bound = kind == 'Bound'
    # Try every axis, preferring the axis requiring the least world-space motion.
    ranked: list[tuple[int, int, int]] = []
    for axis in range(3):
        mag = _radial_axis_target(old, stored, axis, require_bound)
        for sign in (1, -1):
            target = sign * mag
            ranked.append((abs(target - int(old[axis])), axis, target))
    for _, axis, base in sorted(ranked):
        for extra_units in (0, 1, 2, 4, 8, 16):
            sign = 1 if base >= 0 else -1
            q = list(old); q[axis] = int(base + sign * (extra_units << 8))
            yield tuple(int(x) for x in q)


def _world_positions(obj: dict[str, Any], bone_tms: dict[str, list[int]]) -> list[tuple[int, int, int]]:
    out = []
    for vi, v in enumerate(obj['vertices']):
        tm = bone_tms.get(obj['bones'][vi])
        if tm is None:
            raise ValueError(f'MISSING_BONE_TM_{obj["bones"][vi]}')
        out.append(_transform_point_fixed(tuple(int(x) for x in v[:3]), tm))
    return out


def _evaluate(obj: dict[str, Any], bone_tms: dict[str, list[int]], world: list[tuple[int, int, int]],
              state: dict[str, Any], vi: int, requested: tuple[int, int, int], target_kind: str) -> dict[str, Any] | None:
    incident = list(state['incidence'][vi])
    mixed_incident = [fi for fi in incident if len(_combo(obj, obj['faces'][fi])) > 1]
    if not mixed_incident or state['current'][vi] is None or requested == world[vi]:
        return None

    stored = {k: int(v) for k, v in obj['stored_bounds'].items()}
    expanded = _expanded_bounds(stored, requested)
    changed_fields = _bound_changes(stored, expanded)
    if target_kind not in changed_fields:
        return None
    if any(int(expanded[k]) < int(stored[k]) for k in expanded):
        return None

    bone = obj['bones'][vi]
    tm = bone_tms.get(bone)
    if tm is None:
        return None
    inv = _invert_matrix_source(tm)
    oldv = obj['vertices'][vi]
    old_local = tuple(int(x) for x in oldv[:3])
    new_local = _transform_point_fixed(requested, inv)
    if new_local == old_local or not all(_i32_safe(q) for q in new_local):
        return None
    reimport = _transform_point_fixed(new_local, tm)
    pos_error = max(abs(reimport[z] - requested[z]) for z in range(3))
    if pos_error > POSITION_REIMPORT_LIMIT_FIXED or not _bounds_cover_point(expanded, reimport):
        return None

    world2 = list(world); world2[vi] = requested
    changed_face_normals: dict[int, tuple[int, int, int]] = {}
    affected: set[int] = set()
    for fi in incident:
        f = obj['faces'][fi]; a, b, c = [int(x) for x in f[:3]]
        n = _face_normal_source(world2[a], world2[b], world2[c])
        if n is None:
            return None
        changed_face_normals[fi] = n; affected.update((a, b, c))
    if any(state['current'][av] is None for av in affected):
        return None
    current2 = _updated_current_for_affected(state, obj['faces'], changed_face_normals, affected)
    if current2 is None:
        return None

    affected_rows = []
    source_delta_max = 0; target_error_max = 0; affected_bones: set[str] = set()
    for av in sorted(affected):
        before_current = state['current'][av]
        assert before_current is not None
        after_current = current2[av]
        source_delta = tuple(after_current[z] - before_current[z] for z in range(3))
        source_delta_max = max(source_delta_max, max(abs(q) for q in source_delta))
        av_bone = obj['bones'][av]; affected_bones.add(av_bone)
        av_tm = bone_tms.get(av_bone)
        if av_tm is None:
            return None
        av_inv = _invert_matrix_source(av_tm)
        av_vertex = obj['vertices'][av]
        old_hist = _world_hist_vector(av_vertex, av_tm)
        residual = tuple(old_hist[z] - before_current[z] for z in range(3))
        target_vec = tuple(after_current[z] + residual[z] for z in range(3))
        desired_pos = requested if av == vi else world[av]
        target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
        local_ep = _transform_point_fixed(target_ep_world, av_inv)
        if not all(_i32_safe(q) for q in local_ep):
            return None
        actual_ep_world = _transform_point_fixed(local_ep, av_tm)
        actual_pos_world = reimport if av == vi else world[av]
        actual_vec = tuple(actual_ep_world[z] - actual_pos_world[z] for z in range(3))
        target_error = max(abs(actual_vec[z] - target_vec[z]) for z in range(3))
        target_error_max = max(target_error_max, target_error)
        affected_rows.append({
            'vertex_index': av, 'bone': av_bone, 'is_position_witness': av == vi,
            'before_local_position_fixed': list(int(x) for x in av_vertex[:3]),
            'after_local_position_fixed': list(new_local if av == vi else tuple(int(x) for x in av_vertex[:3])),
            'before_local_normal_endpoint_fixed': list(int(x) for x in av_vertex[3:6]),
            'after_local_normal_endpoint_fixed': list(local_ep),
            'before_world_position_fixed': list(world[av]),
            'desired_world_position_fixed': list(desired_pos),
            'expected_reimport_world_position_fixed': list(actual_pos_world),
            'before_current_source_normal_fixed': list(before_current),
            'after_current_source_normal_fixed': list(after_current),
            'current_source_normal_delta_fixed': list(source_delta),
            'before_historical_world_normal_fixed': list(old_hist),
            'historical_residual_vs_current_source_fixed': list(residual),
            'target_historical_world_normal_fixed': list(target_vec),
            'actual_reimport_world_normal_fixed': list(actual_vec),
            'target_reimport_error_fixed': target_error,
        })
    if len(affected_bones) < 2:
        return None
    if source_delta_max == 0 or source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
        return None
    if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
        return None

    return {
        'logical': TARGET, 'object_index': int(obj['index']), 'table_name': obj['table_name'], 'head_name': obj['head_name'],
        'vertex_index': int(vi), 'bone': bone, 'target_bound_kind': target_kind,
        'before_world_fixed': list(world[vi]), 'requested_after_world_fixed': list(requested),
        'expected_reimport_world_fixed': list(reimport), 'requested_reimport_error_fixed': int(pos_error),
        'before_local_fixed': list(old_local), 'after_local_fixed': list(new_local),
        'incident_face_indices': [int(x) for x in incident],
        'mixed_incident_face_indices': [int(x) for x in mixed_incident],
        'incident_face_count': len(incident), 'mixed_incident_face_count': len(mixed_incident),
        'affected_vertex_count': len(affected), 'affected_bone_count': len(affected_bones),
        'affected_bones': sorted(affected_bones, key=str.lower), 'affected_vertices': affected_rows,
        'max_current_source_normal_delta_fixed': int(source_delta_max),
        'max_target_reimport_normal_error_fixed': int(target_error_max),
        'stored_bounds_before': stored, 'stored_bounds_after': expanded, 'changed_bound_fields': changed_fields,
        'normal_policy': 'MULTIBONE_FINAL_GEOMETRY_SETGNORMALS_PLUS_PER_VERTEX_BONE_HISTORICAL_RESIDUAL',
        'bounds_policy': 'MONOTONIC_OUTWARD_EXPANSION_ONLY_FROM_EXACT_EDITED_WORLD_POINT',
        'guard_status': 'PASS',
    }


def discover_witnesses(prepared: pathlib.Path, skeleton: pathlib.Path) -> dict[str, Any]:
    model = _parse_with_offsets(prepared); bone_tms = _parse_skeleton_tms(skeleton)
    found: dict[str, dict[str, Any]] = {}
    attempts = {k: 0 for k in TARGET_KINDS}
    for kind in TARGET_KINDS:
        choices: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for oi, obj in enumerate(model['objects']):
            world = _world_positions(obj, bone_tms); state = _build_source_normal_state(world, obj['faces'])
            mixed_vertices: set[int] = set()
            for f in obj['faces']:
                if len(_combo(obj, f)) > 1:
                    mixed_vertices.update(int(v) for v in f[:3])
            for vi in sorted(mixed_vertices):
                for requested in _requested_candidates(world[vi], obj['stored_bounds'], kind):
                    attempts[kind] += 1
                    p = _evaluate(obj, bone_tms, world, state, vi, requested, kind)
                    if p is None:
                        continue
                    move = max(abs(int(requested[z]) - int(world[vi][z])) for z in range(3))
                    score = (
                        move,
                        int(p['max_current_source_normal_delta_fixed']),
                        int(p['max_target_reimport_normal_error_fixed']),
                        int(p['requested_reimport_error_fixed']),
                        -int(p['affected_bone_count']), oi, vi,
                    )
                    choices.append((score, p))
                    break
        if choices:
            choices.sort(key=lambda x: x[0]); found[kind] = choices[0][1]
    return {'found': found, 'attempts_by_kind': attempts}


def _patch(source: pathlib.Path, prepared: pathlib.Path, staging: pathlib.Path, plan: dict[str, Any]) -> dict[str, Any]:
    model = _parse_with_offsets(prepared); obj = model['objects'][int(plan['object_index'])]
    src = bytearray(pathlib.Path(source).read_bytes())
    if len(src) != len(pathlib.Path(prepared).read_bytes()):
        raise ValueError('PHYSICAL_PREPARED_SIZE_MISMATCH')
    allowed: list[list[int]] = []
    for row in plan['affected_vertices']:
        av = int(row['vertex_index']); off = int(obj['vertex_offset']) + av * SV
        old = struct.unpack_from('<6i', src, off)
        expected = tuple(int(x) for x in row['before_local_position_fixed'] + row['before_local_normal_endpoint_fixed'])
        if old != expected:
            raise ValueError(f'SOURCE_VERTEX_CHANGED_{av}')
        new_pos = tuple(int(x) for x in row['after_local_position_fixed'])
        new_ep = tuple(int(x) for x in row['after_local_normal_endpoint_fixed'])
        if bool(row['is_position_witness']):
            struct.pack_into('<6i', src, off, *(new_pos + new_ep)); allowed.append([off, off + SV])
        else:
            struct.pack_into('<3i', src, off + 12, *new_ep); allowed.append([off + 12, off + SV])
    os = int(obj['object_start']); patches = []
    before = plan['stored_bounds_before']; after = plan['stored_bounds_after']
    for key in ('maxZ', 'maxY', 'maxX', 'dBound', 'Bound'):
        if int(before[key]) == int(after[key]):
            continue
        off = os + BOUND_OFFSETS[key]
        if struct.unpack_from('<i', src, off)[0] != int(before[key]):
            raise ValueError(f'PHYSICAL_BOUND_CHANGED_{key}')
        struct.pack_into('<i', src, off, int(after[key])); allowed.append([off, off + 4])
        patches.append({'field': key, 'offset': off, 'before': int(before[key]), 'after': int(after[key])})
    if not patches:
        raise ValueError('NO_BOUND_PATCHES')
    staging.parent.mkdir(parents=True, exist_ok=True); staging.write_bytes(src)
    return {'allowed_byte_ranges': allowed, 'bound_patches': patches}


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def _compare(source: pathlib.Path, output: pathlib.Path, prepared_output: pathlib.Path,
             plan: dict[str, Any], patch: dict[str, Any], bone_tms: dict[str, list[int]]) -> dict[str, Any]:
    sb = pathlib.Path(source).read_bytes(); ob = pathlib.Path(output).read_bytes(); errors = []
    if len(sb) != len(ob): errors.append('FILE_SIZE')
    diff = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    outside = [i for i in diff if not _in_ranges(i, patch['allowed_byte_ranges'])]
    if outside: errors.append('NON_AUTHORIZED_BYTES_CHANGED')
    if not diff: errors.append('BYTE_IDENTICAL_AFTER_EDIT')
    out_model = _parse_with_offsets(prepared_output); obj = out_model['objects'][int(plan['object_index'])]
    if {k: int(v) for k, v in obj['stored_bounds'].items()} != {k: int(v) for k, v in plan['stored_bounds_after'].items()}:
        errors.append('OUTPUT_BOUNDS')
    max_normal_error = 0
    for row in plan['affected_vertices']:
        av = int(row['vertex_index']); v = obj['vertices'][av]
        if tuple(int(x) for x in v[:3]) != tuple(int(x) for x in row['after_local_position_fixed']): errors.append(f'POSITION_{av}')
        if tuple(int(x) for x in v[3:6]) != tuple(int(x) for x in row['after_local_normal_endpoint_fixed']): errors.append(f'NORMAL_{av}')
        tm = bone_tms[row['bone']]
        wp = _transform_point_fixed(tuple(int(x) for x in v[:3]), tm)
        we = _transform_point_fixed(tuple(int(x) for x in v[3:6]), tm)
        actual = tuple(we[z] - wp[z] for z in range(3)); target = tuple(int(x) for x in row['target_historical_world_normal_fixed'])
        err = max(abs(actual[z] - target[z]) for z in range(3)); max_normal_error = max(max_normal_error, err)
        if err > NORMAL_TARGET_REIMPORT_LIMIT_FIXED: errors.append(f'NORMAL_REIMPORT_{av}')
    # Protect the entire historical bound window except explicitly patched int32 fields.
    os = int(obj['object_start'])
    allowed_bound = {int(x['offset']) + j for x in patch['bound_patches'] for j in range(4)}
    bad_bound = [i for i in range(os + 44, os + 76) if sb[i] != ob[i] and i not in allowed_bound]
    if bad_bound: errors.append('BOUND_WINDOW_NON_FIELD_BYTES_CHANGED')
    if errors:
        raise RuntimeError('MULTIBONE_EXTENT_COMPARE_FAILED:' + ','.join(errors))
    return {
        'check': 'PASS', 'diff_byte_count': len(diff), 'all_non_authorized_bytes_byte_identical': not outside,
        'changed_bound_fields': [x['field'] for x in patch['bound_patches']],
        'bound_window_non_field_bytes_byte_identical': not bad_bound,
        'max_target_reimport_normal_error_fixed': max_normal_error,
    }


def run(root: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root).resolve(); output = pathlib.Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / (output.stem + '_workspace')
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)

    cross_policy = load_and_validate_cross_policy(root)
    cross_policy_path = root / CROSS_POLICY_REL; cross_sha_before = _sha256(cross_policy_path)
    writers_before = _writer_hashes(root)
    if writers_before != EXPECTED_WRITER_HASHES:
        raise RuntimeError('CERTIFIED_WRITER_HASH_MISMATCH_BEFORE_V0831')

    settings = Settings.discover(root, None); resolver = ClientResolver(settings.client_root)
    reg = AssetRegistry(settings.inventory, settings.pairing, resolver=resolver)
    real_cert = CertificationRegistry(settings.certifications_dir); real_count_before = len(real_cert.records()); real_sha_before = _cert_sha(real_cert)
    source = pathlib.Path(resolver.resolve(TARGET, required=True)); source_sha_before = _sha256(source)
    if source_sha_before != cross_policy.get('client_source_sha256'):
        raise RuntimeError('CLIENT_SOURCE_SHA_DIVERGES_FROM_V0830_POLICY')

    isolated_cert = CertificationRegistry(work / 'isolated_preview_certifications')
    workspace = work / 'isolated_workspace'
    manifest = prepare_at_dragon_edit_workspace(
        reg, resolver, isolated_cert, settings, project_root=root, open_gui=False, reset=True,
        workspace_root=workspace, workspace_origin='AUDIT_V0831_MULTIBONE_OUTWARD_EXTENT_PROBE',
    )
    prepared = pathlib.Path(manifest['prepared_source']); skeleton = pathlib.Path(manifest['skeleton'])
    discovery = discover_witnesses(prepared, skeleton); found = discovery['found']
    if not found:
        raise RuntimeError('NO_SAFE_MULTIBONE_OUTWARD_EXTENT_WITNESS')

    bone_tms = _parse_skeleton_tms(skeleton); rows = []
    # Execute every discovered bound class independently from the pristine source.
    for kind in TARGET_KINDS:
        plan = found.get(kind)
        if plan is None:
            continue
        case = work / f'extent_{kind}'; case.mkdir(parents=True, exist_ok=True)
        plan_path = case / 'plan.json'; plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staging = case / 'rebuilt_multibone_extent.smd.staging'; final = case / 'rebuilt_multibone_extent.smd'
        patch = _patch(source, prepared, staging, plan)
        prepared_output = case / 'prepared_output' / pathlib.PurePosixPath(TARGET)
        prepare_model062_tooling_source(staging, prepared_output)
        binary = _compare(source, staging, prepared_output, plan, patch, bone_tms)
        preview = json.loads((workspace / 'base_preview' / 'summary.json').read_text(encoding='utf-8'))
        validation = _reimport_and_check(
            reg=reg, resolver=resolver, certifications=isolated_cert, settings=settings,
            project_root=root, preview=preview, skeleton=skeleton, prepared_output=prepared_output,
            plan=plan, work=case / 'validation',
        )
        staging.replace(final)
        rows.append({
            'status': 'PASS', 'target_bound_kind': kind, 'object_index': int(plan['object_index']),
            'vertex_index': int(plan['vertex_index']), 'affected_bone_count': int(plan['affected_bone_count']),
            'affected_bones': list(plan['affected_bones']), 'requested_reimport_error_fixed': int(plan['requested_reimport_error_fixed']),
            'max_current_source_normal_delta_fixed': int(plan['max_current_source_normal_delta_fixed']),
            'max_target_reimport_normal_error_fixed': int(plan['max_target_reimport_normal_error_fixed']),
            'stored_bounds_before': plan['stored_bounds_before'], 'stored_bounds_after': plan['stored_bounds_after'],
            'changed_bound_fields': list(plan['changed_bound_fields']),
            'all_non_authorized_bytes_byte_identical': bool(binary['all_non_authorized_bytes_byte_identical']),
            'bound_window_non_field_bytes_byte_identical': bool(binary['bound_window_non_field_bytes_byte_identical']),
            'transport_position_error': float(validation['transport'].get('max_position_error', validation['transport'].get('position_error', 0.0)) or 0.0),
            'transport_uv_error': float(validation['transport'].get('max_uv_error', validation['transport'].get('uv_error', 0.0)) or 0.0),
            'witness_check': validation['witness'].get('check'), 'output_smd': str(final), 'output_sha256': _sha256(final),
        })

    # Existing production paths MUST still reject an extent edit.  The probe only
    # establishes physical evidence; no policy or production dispatch is widened.
    from .rare_rigid_multivertex import plan_requested_at_dragon_transaction
    first = rows[0]; first_plan = found[first['target_bound_kind']]
    vi = int(first_plan['vertex_index'])
    production_extent_blocked = False; production_extent_error = ''
    try:
        plan_requested_at_dragon_transaction(prepared, skeleton, changes=[
            {'object_index': int(first_plan['object_index']), 'vertex_index': vi,
             'after_world_fixed': list(first_plan['requested_after_world_fixed'])},
            # A second duplicate-like no-op is not used: call the single-vertex production
            # planner through rare_rigid_edit instead so the extent guard is exercised.
        ])
    except Exception:
        # The multi planner rejects count=1 before bounds; use exact single planner below.
        pass
    try:
        plan_requested_at_dragon_edit(
            prepared, skeleton, object_index=int(first_plan['object_index']), vertex_index=vi,
            requested_world_fixed=tuple(int(x) for x in first_plan['requested_after_world_fixed']),
        )
    except Exception as exc:
        production_extent_error = f'{type(exc).__name__}:{exc}'
        production_extent_blocked = 'EXTENT_OR_BOUND_MARGIN_CHANGE_DEFERRED' in production_extent_error
    if not production_extent_blocked:
        raise RuntimeError(f'PRODUCTION_EXTENT_NEGATIVE_NOT_BLOCKED:{production_extent_error}')

    writers_after = _writer_hashes(root); source_sha_after = _sha256(source)
    real_count_after = len(real_cert.records()); real_sha_after = _cert_sha(real_cert); cross_sha_after = _sha256(cross_policy_path)
    if writers_after != writers_before or writers_after != EXPECTED_WRITER_HASHES: raise RuntimeError('V0831_WRITER_MODULES_CHANGED')
    if source_sha_after != source_sha_before: raise RuntimeError('V0831_CLIENT_CHANGED')
    if real_count_after != real_count_before or real_sha_after != real_sha_before: raise RuntimeError('V0831_REAL_CERTIFICATION_CHANGED')
    if cross_sha_after != cross_sha_before: raise RuntimeError('V0831_CROSS_OBJECT_POLICY_CHANGED')

    coverage = sorted({f for r in rows for f in r['changed_bound_fields']})
    radial = any('dBound' in r['changed_bound_fields'] for r in rows)
    return {
        'format': FORMAT, 'status': 'PASS', 'release_version': RELEASE_VERSION, 'logical': TARGET,
        'v0830_cross_object_policy_valid': True, 'production_scope_unchanged': True,
        'probe_witness_count': len(rows), 'requested_target_kinds': list(TARGET_KINDS),
        'discovered_target_kinds': [r['target_bound_kind'] for r in rows], 'bound_field_coverage': coverage,
        'radial_bound_evidence_found': radial, 'attempts_by_kind': discovery['attempts_by_kind'], 'rows': rows,
        'production_extent_still_blocked': True, 'production_extent_error': production_extent_error,
        'multibone_outward_extent_write_authorized': False, 'extent_contraction_write_authorized': False,
        'topology_write_authorized': False,
        'real_certification_count_before': real_count_before, 'real_certification_count_after': real_count_after,
        'real_certification_registry_modified': False, 'cross_object_production_policy_modified': False,
        'writer_modules_modified': False, 'client_modified': False, 'writer_hashes': writers_after,
        'client_source_sha256': source_sha_after,
        'policy': {
            'scope': 'audit-only at_dragon outward extent probe: exactly one changed mixed-boundary vertex in one mesh object; affected normals may span multiple Physique bones',
            'bounds': 'only monotonic expansion proven directly by the exact edited world point is patched; no bound contraction or historical maximum reconstruction is attempted',
            'normal_bridge': 'joint affected face normals are recomputed once from final geometry and each affected normal endpoint is serialized through that vertex own bone inverse while preserving historical residual',
            'binary': 'authorized byte ranges are affected vertex/normal endpoint records plus only the 4-byte bound fields that provably grow; every other byte remains exact',
            'authorization': 'PASS is physical research evidence only; existing V0.8.21/V0.8.30 production policies remain unchanged and must continue blocking extent edits',
            'next_on_pass': 'build a saved-Blender multi-bone outward-extent candidate for the discovered physical witness set before any live writer or production authorization',
            'deferred': 'extent production writes, contraction, topology, multi-vertex extent composition and cross-object extent remain fail-closed',
        },
        'next': 'saved-Blender multi-bone outward extent candidate if this physical probe passes',
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='V0.8.31 at_dragon multi-bone outward extent audit-only probe')
    ap.add_argument('--root', required=True); ap.add_argument('--output', required=True); ns = ap.parse_args(argv)
    out = pathlib.Path(ns.output).expanduser().resolve()
    try:
        report = run(pathlib.Path(ns.root), out)
    except Exception as exc:
        report = {
            'format': FORMAT, 'status': 'FAIL', 'release_version': RELEASE_VERSION, 'logical': TARGET,
            'error': f'{type(exc).__name__}:{exc}', 'multibone_outward_extent_write_authorized': False,
            'production_single_object_max_vertices': 8, 'cross_object_production_shapes': ['2x2', '3x2'],
        }
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get('status') == 'PASS':
        print('rare_rigid_multibone_outward_extent_probe=PASS witnesses=%s extent_authorized=false client_modified=false' % report.get('probe_witness_count', 0))
        return 0
    print('rare_rigid_multibone_outward_extent_probe=FAIL')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
