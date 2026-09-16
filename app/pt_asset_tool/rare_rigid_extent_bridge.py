from __future__ import annotations

import json
import math
import pathlib
import struct
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import SV, _invert_matrix_source, _parse_skeleton_tms, _transform_point_fixed
from .rare_rigid_normal_bridge import (
    NORMAL_TARGET_REIMPORT_LIMIT_FIXED,
    POSITION_REIMPORT_LIMIT_FIXED,
    _build_source_normal_state,
    _face_normal_source,
    _i32_safe,
    _updated_current_for_affected,
    _world_hist_vector,
)
from .rare_rigid_preview import _prepare_one_preview
from .rare_rigid_roundtrip import CANDIDATES, DEFERRED_MULTI_BONE, _parse_with_offsets
from .rare_support import prepare_model062_tooling_source
from .utils import run_logged, sha256_file

# Object-header offsets relative to smOBJ3D start. These are the physical
# fields written by AddVertex()/SaveFile in Model0.62.
BOUND_OFFSETS = {
    'maxZ': 44,
    'maxY': 52,
    'maxX': 60,
    'dBound': 68,
    'Bound': 72,
}

# Five physical representatives intentionally cover every bound field.
TARGET_KIND_BY_FILE = {
    'char/tmABCD/ar0nass.smd': 'maxX',
    'char/tmABCD/CartolaFS.smd': 'maxZ',
    'char/tmABCD/CartolaMG.smd': 'maxY',
    'char/tmABCD/CartolaPS.smd': 'dBound',
    'char/tmABCD/CartolaSH.smd': 'Bound',
}

# Extent witnesses can change the SourceCode normal more than the interior
# V0.8.1 witness. This is not an approximation limit; it is only a guard
# against pathological/near-degenerate witness selection. Endpoint reimport
# remains subject to the independently measured <=128 fixed-unit gate.
SOURCE_NORMAL_DELTA_LIMIT_FIXED = 4096
SEARCH_EXTRA_FIXED = 4096


def _point_radius_bound(p: tuple[int, int, int]) -> int:
    x, y, z = p
    xx, yy, zz = x >> 8, y >> 8, z >> 8
    return abs(xx * xx + yy * yy + zz * zz)


def _expanded_bounds(stored: dict[str, int], requested: tuple[int, int, int]) -> dict[str, int]:
    """Exact monotonic AddVertex-style expansion for one edited world point.

    We never infer a contraction from lossy ReformPhysique reconstruction.
    Historical fields are preserved unless the edited point *proves* a larger
    bound by itself. This makes outward expansion exact while inward bound
    shrinkage remains fail-closed.
    """
    out = {k: int(stored[k]) for k in ('maxZ', 'maxY', 'maxX', 'dBound', 'Bound')}
    x, y, z = requested
    out['maxX'] = max(out['maxX'], abs(int(x)))
    out['maxZ'] = max(out['maxZ'], abs(int(y)))
    out['maxY'] = max(out['maxY'], abs(int(z)))
    d = _point_radius_bound(requested)
    if d > out['dBound']:
        out['dBound'] = d
        out['Bound'] = math.trunc(math.sqrt(float(d)))
    return out


def _bound_changes(before: dict[str, int], after: dict[str, int]) -> list[str]:
    return [k for k in ('maxX', 'maxZ', 'maxY', 'dBound', 'Bound') if int(before[k]) != int(after[k])]


def _candidate_requested(old: tuple[int, int, int], stored: dict[str, int], kind: str):
    """Yield deterministic outward-only requested points, smallest first."""
    if kind in ('maxX', 'maxZ', 'maxY'):
        axis = {'maxX': 0, 'maxZ': 1, 'maxY': 2}[kind]
        old_abs = abs(int(old[axis]))
        start = max(int(stored[kind]) + 1, old_abs + 1)
        extras = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
        for sign in (1, -1):
            for extra in extras:
                q = list(old)
                q[axis] = sign * (start + extra)
                yield tuple(int(x) for x in q)
        return

    # dBound/Bound proof uses the historical Z/maxY axis because these assets
    # already sit near the radial bound there, minimizing geometry distortion.
    start = max(int(stored['maxY']) + 1, abs(int(old[2])) + 1)
    for sign in (1, -1):
        for extra in range(0, SEARCH_EXTRA_FIXED + 1):
            q = (int(old[0]), int(old[1]), sign * (start + extra))
            d = _point_radius_bound(q)
            if d <= int(stored['dBound']):
                continue
            b = math.trunc(math.sqrt(float(d)))
            if kind == 'Bound' and b <= int(stored['Bound']):
                continue
            if kind == 'dBound' and b != int(stored['Bound']):
                # Separate representative: prove dBound can change while Bound
                # remains byte-identical.
                continue
            yield q
            # The first qualifying radial coordinate for each sign is the
            # smallest monotonic expansion; later values are unnecessary.
            break


def _evaluate_candidate(obj: dict[str, Any], tm: list[int], inv: list[int], world: list[tuple[int, int, int]],
                        state: dict[str, Any], vi: int, requested: tuple[int, int, int]) -> dict[str, Any] | None:
    incident = list(state['incidence'][vi])
    if not incident or state['current'][vi] is None or requested == world[vi]:
        return None
    oldv = obj['vertices'][vi]
    old_local = tuple(int(x) for x in oldv[:3])
    new_local = _transform_point_fixed(requested, inv)
    if new_local == old_local or not all(_i32_safe(q) for q in new_local):
        return None
    reimport = _transform_point_fixed(new_local, tm)
    pos_error = max(abs(reimport[z] - requested[z]) for z in range(3))
    if pos_error > POSITION_REIMPORT_LIMIT_FIXED:
        return None

    world2 = list(world)
    world2[vi] = requested
    changed_face_normals: dict[int, tuple[int, int, int]] = {}
    affected: set[int] = set()
    for fi in incident:
        f = obj['faces'][fi]
        a, b, c = [int(x) for x in f[:3]]
        n = _face_normal_source(world2[a], world2[b], world2[c])
        if n is None:
            return None
        changed_face_normals[fi] = n
        affected.update((a, b, c))
    if any(state['current'][av] is None for av in affected):
        return None
    current2 = _updated_current_for_affected(state, obj['faces'], changed_face_normals, affected)
    if current2 is None:
        return None

    affected_rows = []
    source_delta_max = 0
    target_error_max = 0
    for av in sorted(affected):
        before_current = state['current'][av]
        assert before_current is not None
        after_current = current2[av]
        source_delta = tuple(after_current[z] - before_current[z] for z in range(3))
        source_delta_max = max(source_delta_max, max(abs(q) for q in source_delta))
        av_vertex = obj['vertices'][av]
        old_hist = _world_hist_vector(av_vertex, tm)
        residual = tuple(old_hist[z] - before_current[z] for z in range(3))
        target_vec = tuple(after_current[z] + residual[z] for z in range(3))
        desired_pos = requested if av == vi else world[av]
        target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
        local_ep = _transform_point_fixed(target_ep_world, inv)
        if not all(_i32_safe(q) for q in local_ep):
            return None
        actual_ep_world = _transform_point_fixed(local_ep, tm)
        actual_pos_world = reimport if av == vi else world[av]
        actual_vec = tuple(actual_ep_world[z] - actual_pos_world[z] for z in range(3))
        target_error = max(abs(actual_vec[z] - target_vec[z]) for z in range(3))
        target_error_max = max(target_error_max, target_error)
        affected_rows.append({
            'vertex_index': av,
            'is_position_witness': av == vi,
            'before_local_position_fixed': list(int(x) for x in av_vertex[:3]),
            'after_local_position_fixed': list(new_local if av == vi else tuple(int(x) for x in av_vertex[:3])),
            'before_local_normal_endpoint_fixed': list(int(x) for x in av_vertex[3:6]),
            'after_local_normal_endpoint_fixed': list(local_ep),
            'before_world_position_fixed': list(world[av]),
            'desired_world_position_fixed': list(desired_pos),
            'expected_reimport_world_position_fixed': list(reimport if av == vi else world[av]),
            'before_current_source_normal_fixed': list(before_current),
            'after_current_source_normal_fixed': list(after_current),
            'current_source_normal_delta_fixed': list(source_delta),
            'before_historical_world_normal_fixed': list(old_hist),
            'historical_residual_vs_current_source_fixed': list(residual),
            'target_historical_world_normal_fixed': list(target_vec),
            'actual_reimport_world_normal_fixed': list(actual_vec),
            'target_reimport_error_fixed': target_error,
        })
    if source_delta_max == 0 or source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
        return None
    if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
        return None
    return {
        'requested_after_world_fixed': list(requested),
        'expected_reimport_world_fixed': list(reimport),
        'requested_reimport_error_fixed': pos_error,
        'after_local_fixed': list(new_local),
        'local_delta_fixed': [new_local[z] - old_local[z] for z in range(3)],
        'incident_face_indices': [int(x) for x in incident],
        'incident_face_count': len(incident),
        'affected_vertex_count': len(affected),
        'affected_vertices': affected_rows,
        'max_current_source_normal_delta_fixed': source_delta_max,
        'max_target_reimport_normal_error_fixed': target_error_max,
    }


def choose_extent_witness(model: dict[str, Any], bones: dict[str, list[int]], target_kind: str) -> dict[str, Any]:
    if target_kind not in ('maxX', 'maxZ', 'maxY', 'dBound', 'Bound'):
        raise ValueError(f'unsupported extent target {target_kind}')
    choices: list[tuple[tuple[int, ...], dict[str, Any]]] = []
    for oi, obj in enumerate(model['objects']):
        bset = sorted(set(obj['bones']), key=str.lower)
        if len(bset) != 1:
            continue
        bone = bset[0]
        tm = bones.get(bone)
        if tm is None:
            continue
        inv = _invert_matrix_source(tm)
        world = [_transform_point_fixed(tuple(int(x) for x in v[:3]), tm) for v in obj['vertices']]
        state = _build_source_normal_state(world, obj['faces'])
        stored = {k: int(v) for k, v in obj['stored_bounds'].items()}
        for vi, incident in enumerate(state['incidence']):
            if not incident or state['current'][vi] is None:
                continue
            old_world = world[vi]
            oldv = obj['vertices'][vi]
            for requested in _candidate_requested(old_world, stored, target_kind):
                new_bounds = _expanded_bounds(stored, requested)
                changes = _bound_changes(stored, new_bounds)
                if target_kind not in changes:
                    continue
                if target_kind == 'dBound' and 'Bound' in changes:
                    continue
                if target_kind == 'Bound' and not {'dBound', 'Bound'}.issubset(changes):
                    continue
                ev = _evaluate_candidate(obj, tm, inv, world, state, vi, requested)
                if ev is None:
                    continue
                move = max(abs(int(requested[z]) - int(old_world[z])) for z in range(3))
                score = (
                    int(ev['max_current_source_normal_delta_fixed']),
                    int(ev['max_target_reimport_normal_error_fixed']),
                    int(ev['affected_vertex_count']), int(ev['incident_face_count']),
                    move, oi, vi,
                )
                plan = {
                    'object_index': oi, 'table_name': obj['table_name'], 'head_name': obj['head_name'],
                    'bone': bone, 'vertex_index': vi,
                    'before_world_fixed': list(old_world),
                    'before_local_fixed': list(int(x) for x in oldv[:3]),
                    'target_bound_kind': target_kind,
                    'stored_bounds_before': stored,
                    'stored_bounds_after': new_bounds,
                    'changed_bound_fields': changes,
                    'normal_policy': 'PRESERVE_HISTORICAL_RESIDUAL_PLUS_CURRENT_SOURCE_SETGNORMALS_DELTA',
                    'bounds_policy': 'MONOTONIC_OUTWARD_EXPANSION_ONLY_PRESERVE_HISTORICAL_FIELDS_UNLESS_EDIT_PROVES_LARGER_VALUE',
                    **ev,
                }
                choices.append((score, plan))
                # _candidate_requested is ordered smallest-first; once one
                # candidate works for this vertex/sign, larger variants are not
                # preferable for the same structural proof.
                break
    if not choices:
        raise ValueError(f'no safe single-bone outward extent witness for {target_kind}')
    choices.sort(key=lambda x: x[0])
    return choices[0][1]


def patch_extent_bridge(source_physical: pathlib.Path, prepared_source: pathlib.Path, output_physical: pathlib.Path,
                        plan: dict[str, Any]) -> dict[str, Any]:
    model = _parse_with_offsets(prepared_source)
    oi = int(plan['object_index']); vi = int(plan['vertex_index'])
    obj = model['objects'][oi]
    if len(set(obj['bones'])) != 1 or obj['bones'][vi] != plan['bone']:
        raise ValueError('single-bone extent witness changed since planning')
    src = bytearray(pathlib.Path(source_physical).read_bytes())
    normalized = pathlib.Path(prepared_source).read_bytes()
    if len(src) != len(normalized):
        raise ValueError('physical/prepared size mismatch')
    allowed_ranges: list[list[int]] = []
    changed_records = []
    for row in plan['affected_vertices']:
        av = int(row['vertex_index'])
        off = int(obj['vertex_offset']) + av * SV
        old = struct.unpack_from('<6i', src, off)
        expected_old = tuple(row['before_local_position_fixed'] + row['before_local_normal_endpoint_fixed'])
        if old != expected_old:
            raise ValueError(f'source vertex[{av}] changed: {old} != {expected_old}')
        new_pos = tuple(int(x) for x in row['after_local_position_fixed'])
        new_ep = tuple(int(x) for x in row['after_local_normal_endpoint_fixed'])
        if bool(row['is_position_witness']):
            struct.pack_into('<6i', src, off, *(new_pos + new_ep))
            allowed_ranges.append([off, off + SV])
        else:
            struct.pack_into('<3i', src, off + 12, *new_ep)
            allowed_ranges.append([off + 12, off + SV])
        changed_records.append({'vertex_index': av, 'record_offset': off, 'old_record': list(old), 'new_record': list(new_pos + new_ep)})

    object_start = int(obj['object_start'])
    bound_patches = []
    before = plan['stored_bounds_before']; after = plan['stored_bounds_after']
    for key in ('maxZ', 'maxY', 'maxX', 'dBound', 'Bound'):
        oldv, newv = int(before[key]), int(after[key])
        if newv == oldv:
            continue
        off = object_start + BOUND_OFFSETS[key]
        physical_old = struct.unpack_from('<i', src, off)[0]
        if physical_old != oldv:
            raise ValueError(f'{key} physical value changed: {physical_old} != {oldv}')
        struct.pack_into('<i', src, off, newv)
        allowed_ranges.append([off, off + 4])
        bound_patches.append({'field': key, 'offset': off, 'before': oldv, 'after': newv})
    if plan['target_bound_kind'] not in {x['field'] for x in bound_patches}:
        raise ValueError('target bound field was not patched')
    output_physical.parent.mkdir(parents=True, exist_ok=True)
    output_physical.write_bytes(src)
    return {'allowed_byte_ranges': allowed_ranges, 'changed_records': changed_records, 'bound_patches': bound_patches}


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def compare_extent_bridge(source_physical: pathlib.Path, output_physical: pathlib.Path, prepared_output: pathlib.Path,
                          plan: dict[str, Any], patch: dict[str, Any], tm: list[int]) -> dict[str, Any]:
    sb = pathlib.Path(source_physical).read_bytes(); ob = pathlib.Path(output_physical).read_bytes()
    errors: list[str] = []
    if len(sb) != len(ob): errors.append('FILE_SIZE')
    if sb[:24] != ob[:24]: errors.append('PHYSICAL_HEADER24_CHANGED')
    diff = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    outside = [i for i in diff if not _in_ranges(i, patch['allowed_byte_ranges'])]
    if outside: errors.append('NON_AUTHORIZED_BYTES_CHANGED')
    if not diff: errors.append('BYTE_IDENTICAL_AFTER_EDIT')

    out_model = _parse_with_offsets(prepared_output)
    obj = out_model['objects'][int(plan['object_index'])]
    if {k: int(v) for k, v in obj['stored_bounds'].items()} != {k: int(v) for k, v in plan['stored_bounds_after'].items()}:
        errors.append('OUTPUT_BOUNDS')
    max_target_error = 0
    for row in plan['affected_vertices']:
        av = int(row['vertex_index']); v = obj['vertices'][av]
        if tuple(v[:3]) != tuple(row['after_local_position_fixed']): errors.append(f'OUTPUT_POSITION_{av}')
        if tuple(v[3:6]) != tuple(row['after_local_normal_endpoint_fixed']): errors.append(f'OUTPUT_NORMAL_ENDPOINT_{av}')
        wp = _transform_point_fixed(tuple(int(x) for x in v[:3]), tm)
        we = _transform_point_fixed(tuple(int(x) for x in v[3:6]), tm)
        vec = tuple(we[z] - wp[z] for z in range(3))
        target = tuple(int(x) for x in row['target_historical_world_normal_fixed'])
        err = max(abs(vec[z] - target[z]) for z in range(3))
        max_target_error = max(max_target_error, err)
        if err > NORMAL_TARGET_REIMPORT_LIMIT_FIXED: errors.append(f'NORMAL_TARGET_REIMPORT_{av}')

    # Every byte in the 32-byte historical bounds window that is not one of
    # the explicitly patched 4-byte fields must remain byte-identical.
    os = int(obj['object_start'])
    allowed_bound_offsets = {os + BOUND_OFFSETS[x['field']] + j for x in patch['bound_patches'] for j in range(4)}
    bound_window_changes = [i for i in range(os + 44, os + 76) if sb[i] != ob[i]]
    bad_bound_window = [i for i in bound_window_changes if i not in allowed_bound_offsets]
    if bad_bound_window: errors.append('BOUND_WINDOW_NON_FIELD_BYTES_CHANGED')

    result = {
        'check': 'PASS' if not errors else 'FAIL', 'errors': errors,
        'source_sha256': sha256_file(source_physical), 'output_sha256': sha256_file(output_physical),
        'file_size': len(sb), 'diff_byte_count': len(diff), 'diff_bytes_outside_authorized_ranges': outside,
        'physical_header24_byte_identical': sb[:24] == ob[:24],
        'all_non_authorized_bytes_byte_identical': not outside and len(sb) == len(ob),
        'changed_bound_fields': [x['field'] for x in patch['bound_patches']],
        'bound_window_non_field_bytes_byte_identical': not bad_bound_window,
        'max_target_reimport_normal_error_fixed': max_target_error,
        'client_modified': False,
    }
    if errors:
        raise RuntimeError('rare rigid extent compare failed: ' + ','.join(errors))
    return result


def _run_one(*, reg, resolver, certifications, settings, project_root: pathlib.Path,
             binding: dict[str, Any], logical: str, target_kind: str, work: pathlib.Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    base_preview_work = work / 'base_preview'
    preview = _prepare_one_preview(
        reg=reg, resolver=resolver, certifications=certifications, settings=settings,
        project_root=project_root, binding=binding, logical=logical,
        work=base_preview_work, open_gui=False,
    )
    source = pathlib.Path(resolver.resolve(logical, required=True))
    prepared = base_preview_work / 'prepared' / pathlib.PurePosixPath(logical)
    skeleton = pathlib.Path(resolver.resolve(preview['motion_smb'], required=True))
    model = _parse_with_offsets(prepared); bone_tms = _parse_skeleton_tms(skeleton)
    plan = choose_extent_witness(model, bone_tms, target_kind); plan['logical'] = logical
    plan_path = work / 'extent_witness_plan.json'
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    witness_blend = work / 'edited_witness.blend'; witness_report = work / 'blender_witness.json'
    witness_script = project_root / 'pt_asset_tool/blender/witness_rare_rigid_geometry.py'
    run_logged(settings.blender_command() + [
        '--background', str(preview['preview_blend']), '--python-exit-code', '1', '--python', str(witness_script), '--',
        '--plan', str(plan_path), '--out', str(witness_blend), '--report', str(witness_report),
    ], work / '03_blender_witness.log')
    wr = json.loads(witness_report.read_text(encoding='utf-8'))
    if wr.get('check') != 'PASS' or list(wr.get('after_world_fixed') or []) != plan['requested_after_world_fixed']:
        raise RuntimeError(f'Blender witness failed: {wr}')

    output = work / 'rebuilt_rare_outward_extent.smd'
    patch = patch_extent_bridge(source, prepared, output, plan)
    prepared_output = work / 'prepared_output' / pathlib.PurePosixPath(logical)
    prepare_model062_tooling_source(output, prepared_output)
    tm = bone_tms[plan['bone']]
    binary = compare_extent_bridge(source, output, prepared_output, plan, patch, tm)

    root_src = pathlib.Path(resolver.resolve(preview['root_model'], required=True))
    source_inx = pathlib.Path(resolver.resolve(preview['source_inxs'][0], required=True))
    target_inx = pathlib.Path(resolver.resolve(preview['target_inx'], required=True))
    overlay_root = base_preview_work / 'textures' / 'texture_overlay_client'
    if not overlay_root.is_dir(): raise RuntimeError('base preview texture overlay missing')
    rebuilt_blend = work / 'rebuilt_preview.blend'; import_report = work / 'rebuilt_import.json'
    importer_script = project_root / 'pt_asset_tool/blender/import_rare_rigid_context.py'
    common = [
        '--importer', str(project_root / 'pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py'),
        '--rare-smd', str(prepared_output), '--root-smd', str(root_src), '--skeleton', str(skeleton),
        '--rare-model-info', str(source_inx), '--root-model-info', str(target_inx), '--root-lod', str(preview['root_lod']),
        '--rare-visibility-policy', str(preview['rare_visibility_policy']), '--client-root', str(overlay_root),
        '--out', str(rebuilt_blend), '--report', str(import_report), '--logical', logical, '--root-logical', str(preview['root_model']),
    ]
    run_logged(settings.blender_command() + ['--background', '--python-exit-code', '1', '--python', str(importer_script), '--', *common], work / '04_rebuilt_import.log')
    imported = json.loads(import_report.read_text(encoding='utf-8'))
    if imported.get('check') != 'PASS': raise RuntimeError(f'rebuilt import failed: {imported}')

    transport_report = work / 'rebuilt_transport.json'; checker = project_root / 'pt_asset_tool/blender/check_rare_rigid_context.py'
    run_logged(settings.blender_command() + [
        '--background', str(rebuilt_blend), '--python-exit-code', '1', '--python', str(checker), '--',
        '--importer', str(project_root / 'pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py'),
        '--rare-smd', str(prepared_output), '--root-smd', str(root_src), '--skeleton', str(skeleton),
        '--rare-model-info', str(source_inx), '--root-model-info', str(target_inx), '--root-lod', str(preview['root_lod']),
        '--rare-visibility-policy', str(preview['rare_visibility_policy']), '--report', str(transport_report),
    ], work / '05_rebuilt_transport.log')
    transport = json.loads(transport_report.read_text(encoding='utf-8'))
    if transport.get('check') != 'PASS': raise RuntimeError(f'rebuilt transport failed: {transport}')

    witness_check = work / 'rebuilt_witness_check.json'; witness_checker = project_root / 'pt_asset_tool/blender/check_rare_rigid_geometry_witness.py'
    run_logged(settings.blender_command() + [
        '--background', str(rebuilt_blend), '--python-exit-code', '1', '--python', str(witness_checker), '--',
        '--plan', str(plan_path), '--report', str(witness_check),
    ], work / '06_rebuilt_witness.log')
    wc = json.loads(witness_check.read_text(encoding='utf-8'))
    if wc.get('check') != 'PASS': raise RuntimeError(f'rebuilt witness check failed: {wc}')

    cert = certifications.add(
        asset_id=str(getattr(reg.resolve(logical), 'asset_id', '') or ('RARE::' + logical)),
        asset_path=logical, family='MODEL062_ALT_MAGIC_BODY_EXACT',
        test='RARE_RIGID_SINGLE_BONE_OUTWARD_EXTENT_ROUNDTRIP', layer='AUTOMATIC', result='PASS',
        source_sha256=sha256_file(source), artifact_sha256=sha256_file(output),
        metadata={
            'write_scope': 'SINGLE_BONE_OUTWARD_EXTENT_EXPANSION_WITH_NORMAL_PROVENANCE_DELTA',
            'target_bound_kind': target_kind, 'changed_bound_fields': binary['changed_bound_fields'],
            'normal_policy': plan['normal_policy'], 'bounds_policy': plan['bounds_policy'],
            'object_index': plan['object_index'], 'vertex_index': plan['vertex_index'],
            'max_current_source_normal_delta_fixed': plan['max_current_source_normal_delta_fixed'],
            'max_target_reimport_normal_error_fixed': binary['max_target_reimport_normal_error_fixed'],
            'non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
            'client_modified': False,
        },
    )
    return {
        'logical': logical, 'check': 'PASS', 'target_bound_kind': target_kind,
        'object_index': plan['object_index'], 'head_name': plan['head_name'], 'bone': plan['bone'],
        'vertex_index': plan['vertex_index'], 'before_world_fixed': plan['before_world_fixed'],
        'requested_after_world_fixed': plan['requested_after_world_fixed'],
        'requested_reimport_error_fixed': plan['requested_reimport_error_fixed'],
        'changed_bound_fields': binary['changed_bound_fields'],
        'bounds_before': plan['stored_bounds_before'], 'bounds_after': plan['stored_bounds_after'],
        'max_current_source_normal_delta_fixed': plan['max_current_source_normal_delta_fixed'],
        'max_target_reimport_normal_error_fixed': binary['max_target_reimport_normal_error_fixed'],
        'all_non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
        'bound_window_non_field_bytes_byte_identical': binary['bound_window_non_field_bytes_byte_identical'],
        'transport_position_error': transport.get('max_position_abs_error'), 'transport_uv_error': transport.get('max_uv_abs_error'),
        'physique_mismatch_count': transport.get('physique_mismatch_count'), 'rebuilt_witness_world_fixed': wc.get('actual_world_fixed'),
        'rebuilt_smd': str(output), 'rebuilt_blend': str(rebuilt_blend), 'certification_id': cert['certification_id'],
        'client_modified': False,
    }


def audit_rare_rigid_outward_extent_roundtrip(reg, resolver, certifications, settings, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root); work = pathlib.Path(work); work.mkdir(parents=True, exist_ok=True)
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / 'binding_recheck', bundle=None)
    if binding.get('status') != 'PASS': raise RuntimeError('binding recheck failed')
    rows = []; errors = []
    for logical in CANDIDATES:
        try:
            rows.append(_run_one(
                reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                project_root=project_root, binding=binding, logical=logical,
                target_kind=TARGET_KIND_BY_FILE[logical], work=work / pathlib.PurePosixPath(logical).name,
            ))
        except Exception as exc:
            errors.append({'logical': logical, 'target_bound_kind': TARGET_KIND_BY_FILE.get(logical), 'error': f'{type(exc).__name__}: {exc}'})
    passed = sum(r.get('check') == 'PASS' for r in rows)
    complete = passed == len(CANDIDATES) and not errors
    coverage = sorted({f for r in rows for f in (r.get('changed_bound_fields') or [])})
    required_coverage = ['Bound', 'dBound', 'maxX', 'maxY', 'maxZ']
    coverage_complete = set(coverage) == set(required_coverage)
    if complete and not coverage_complete:
        complete = False
        errors.append({'error': f'bound field coverage incomplete: {coverage}'})
    result = {
        'format': 'PT_RARE_RIGID_SINGLE_BONE_OUTWARD_EXTENT_ROUNDTRIP_V1',
        'status': 'PASS' if complete else 'FAIL', 'expected': len(CANDIDATES), 'audited': len(rows), 'roundtrip_pass': passed,
        'single_bone_outward_extent_write_authorized': complete,
        'single_bone_position_write_authorized': complete,
        'single_bone_normal_provenance_write_authorized': complete,
        'write_scope': 'SINGLE_BONE_OUTWARD_EXTENT_EXPANSION_WITH_MONOTONIC_BOUNDS_AND_NORMAL_PROVENANCE_BRIDGE',
        'bound_field_coverage': coverage, 'bound_field_coverage_complete': coverage_complete,
        'extent_contraction_write_authorized': False, 'topology_write_authorized': False,
        'multi_bone_deferred': DEFERRED_MULTI_BONE,
        'max_requested_reimport_error_fixed': max([int(r.get('requested_reimport_error_fixed') or 0) for r in rows] or [0]),
        'max_current_source_normal_delta_fixed': max([int(r.get('max_current_source_normal_delta_fixed') or 0) for r in rows] or [0]),
        'max_target_reimport_normal_error_fixed': max([int(r.get('max_target_reimport_normal_error_fixed') or 0) for r in rows] or [0]),
        'non_authorized_bytes_exact_files': sum(bool(r.get('all_non_authorized_bytes_byte_identical')) for r in rows),
        'bound_window_non_field_bytes_exact_files': sum(bool(r.get('bound_window_non_field_bytes_byte_identical')) for r in rows),
        'physique_mismatch_total': sum(int(r.get('physique_mismatch_count') or 0) for r in rows),
        'errors': errors,
        'source_findings': {
            'AddVertex_bounds': 'maxX/maxZ/maxY are monotonic abs-coordinate maxima; dBound is the maximum shifted squared radius and Bound=trunc(sqrt(dBound))',
            'loss_bridge': 'untouched historical bounds are not reconstructed from lossy ReformPhysique coordinates; each field changes only when the edited world point itself proves a larger exact value',
            'normal_bridge': 'affected normals retain historical residual plus the current SourceCode SetGNormals delta from the geometry edit',
        },
        'policy': {
            'expansion': 'outward bound growth is exact because new_value=max(historical_value, exact edited world point contribution)',
            'contraction': 'bound shrinkage remains fail-closed because lossy Physique reconstruction cannot prove which untouched historical vertex owned the old maximum',
            'untouched': 'all bytes outside affected vertex/normal-endpoint fields and explicitly changed 4-byte bound fields remain byte-identical',
            'multi_bone': 'at_dragon remains deferred', 'client_modified': False,
        },
        'rows': rows, 'client_modified': False,
    }
    rp = work / 'rare_rigid_outward_extent_roundtrip_report.json'
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'); result['report'] = str(rp)
    return result
