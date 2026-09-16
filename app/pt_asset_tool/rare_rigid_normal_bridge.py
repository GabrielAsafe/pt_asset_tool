from __future__ import annotations

import json
import math
import pathlib
import struct
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_geometry import (
    SV, _invert_matrix_source, _parse_rigid_model, _parse_skeleton_tms,
    _transform_point_fixed,
)
from .rare_rigid_preview import _prepare_one_preview
from .rare_rigid_roundtrip import CANDIDATES, DEFERRED_MULTI_BONE, _parse_with_offsets, _stored_bound_safe
from .rare_support import prepare_model062_tooling_source
from .utils import low_path, norm_path, run_logged, sha256_file

F32 = struct.Struct('<f')
I32_MIN = -0x80000000
I32_MAX = 0x7FFFFFFF
NORMAL_TARGET_REIMPORT_LIMIT_FIXED = 128
SOURCE_NORMAL_DELTA_LIMIT_FIXED = 512
POSITION_REIMPORT_LIMIT_FIXED = 20


def _f32(x: float | int) -> float:
    return F32.unpack(F32.pack(float(x)))[0]


def _i32_safe(x: int) -> bool:
    return I32_MIN <= int(x) <= I32_MAX


def _trunc_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError('division by zero')
    return math.trunc(a / b)


def _face_normal_source(p1: tuple[int, int, int], p2: tuple[int, int, int], p3: tuple[int, int, int]) -> tuple[int, int, int] | None:
    """Current SourceCode smOBJ3D::SetGNormals face contribution.

    The source computes the cross product in signed int, casts to float, uses
    sqrt(double(float expression)), then float division/multiply and C truncation.
    We fail closed on degenerate faces and any signed-int overflow candidate.
    """
    ci = ((p2[1] - p1[1]) * (p3[2] - p1[2])) - ((p2[2] - p1[2]) * (p3[1] - p1[1]))
    cj = ((p2[2] - p1[2]) * (p3[0] - p1[0])) - ((p2[0] - p1[0]) * (p3[2] - p1[2]))
    ck = ((p2[0] - p1[0]) * (p3[1] - p1[1])) - ((p2[1] - p1[1]) * (p3[0] - p1[0]))
    if not all(_i32_safe(q) for q in (ci, cj, ck)):
        return None
    if (ci, cj, ck) == (0, 0, 0):
        return None
    i, j, k = _f32(ci), _f32(cj), _f32(ck)
    ss = _f32(_f32(i * i) + _f32(j * j))
    ss = _f32(ss + _f32(k * k))
    d = _f32(math.sqrt(float(ss)))
    if d == 0.0 or not math.isfinite(d):
        return None
    out = []
    for q in (i, j, k):
        unit = _f32(q / d)
        scaled = _f32(unit * _f32(32767.0))
        if not math.isfinite(scaled):
            return None
        out.append(math.trunc(scaled))
    return tuple(out)  # type: ignore[return-value]


def _build_source_normal_state(world: list[tuple[int, int, int]], faces: list[tuple[int, ...]]) -> dict[str, Any]:
    sums = [[0, 0, 0] for _ in world]
    counts = [0 for _ in world]
    incidence: list[list[int]] = [[] for _ in world]
    face_normals: list[tuple[int, int, int] | None] = []
    invalid_vertices: set[int] = set()
    for fi, f in enumerate(faces):
        a, b, c = [int(x) for x in f[:3]]
        if not (0 <= a < len(world) and 0 <= b < len(world) and 0 <= c < len(world)):
            raise ValueError(f'face[{fi}] vertex OOB')
        for v in (a, b, c):
            incidence[v].append(fi)
        n = _face_normal_source(world[a], world[b], world[c])
        face_normals.append(n)
        if n is None:
            invalid_vertices.update((a, b, c))
            continue
        for v in (a, b, c):
            counts[v] += 1
            for z in range(3):
                sums[v][z] += n[z]
                if not _i32_safe(sums[v][z]):
                    invalid_vertices.add(v)
    current: list[tuple[int, int, int] | None] = []
    for vi in range(len(world)):
        if vi in invalid_vertices or counts[vi] != len(incidence[vi]) or counts[vi] == 0:
            current.append(None)
        else:
            current.append(tuple(_trunc_div(sums[vi][z], counts[vi]) for z in range(3)))
    return {
        'face_normals': face_normals,
        'sums': sums,
        'counts': counts,
        'incidence': incidence,
        'invalid_vertices': invalid_vertices,
        'current': current,
    }


def _updated_current_for_affected(
    state: dict[str, Any], faces: list[tuple[int, ...]], changed_face_normals: dict[int, tuple[int, int, int]], affected: set[int]
) -> dict[int, tuple[int, int, int]] | None:
    out: dict[int, tuple[int, int, int]] = {}
    for vi in affected:
        if state['current'][vi] is None:
            return None
        s = list(state['sums'][vi])
        for fi in state['incidence'][vi]:
            if fi not in changed_face_normals:
                continue
            old = state['face_normals'][fi]
            if old is None:
                return None
            new = changed_face_normals[fi]
            for z in range(3):
                s[z] += new[z] - old[z]
                if not _i32_safe(s[z]):
                    return None
        c = int(state['counts'][vi])
        out[vi] = tuple(_trunc_div(s[z], c) for z in range(3))
    return out


def _world_hist_vector(vertex: tuple[int, ...], tm: list[int]) -> tuple[int, int, int]:
    wp = _transform_point_fixed(tuple(int(x) for x in vertex[:3]), tm)
    we = _transform_point_fixed(tuple(int(x) for x in vertex[3:6]), tm)
    return tuple(we[z] - wp[z] for z in range(3))


def choose_normal_bridge_witness(model: dict[str, Any], bones: dict[str, list[int]]) -> dict[str, Any]:
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
        for vi, incident in enumerate(state['incidence']):
            if not incident or state['current'][vi] is None:
                continue
            oldv = obj['vertices'][vi]
            old_local = tuple(int(x) for x in oldv[:3])
            old_world = world[vi]
            for delta in (256, -256, 512, -512):
                for axis in (0, 2, 1):
                    requested = list(old_world); requested[axis] += delta; requested_t = tuple(requested)
                    if not _stored_bound_safe(requested_t, obj['stored_bounds']):
                        continue
                    new_local = _transform_point_fixed(requested_t, inv)
                    if new_local == old_local or not all(_i32_safe(q) for q in new_local):
                        continue
                    reimport = _transform_point_fixed(new_local, tm)
                    pos_error = max(abs(reimport[z] - requested_t[z]) for z in range(3))
                    if pos_error > POSITION_REIMPORT_LIMIT_FIXED or not _stored_bound_safe(reimport, obj['stored_bounds']):
                        continue
                    world2 = list(world); world2[vi] = requested_t
                    changed_face_normals: dict[int, tuple[int, int, int]] = {}
                    affected: set[int] = set()
                    valid = True
                    for fi in incident:
                        f = obj['faces'][fi]; a, b, c = [int(x) for x in f[:3]]
                        n = _face_normal_source(world2[a], world2[b], world2[c])
                        if n is None:
                            valid = False; break
                        changed_face_normals[fi] = n
                        affected.update((a, b, c))
                    if not valid or any(state['current'][av] is None for av in affected):
                        continue
                    current2 = _updated_current_for_affected(state, obj['faces'], changed_face_normals, affected)
                    if current2 is None:
                        continue
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
                        desired_pos = requested_t if av == vi else world[av]
                        target_ep_world = tuple(desired_pos[z] + target_vec[z] for z in range(3))
                        local_ep = _transform_point_fixed(target_ep_world, inv)
                        if not all(_i32_safe(q) for q in local_ep):
                            valid = False; break
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
                    if not valid:
                        continue
                    if source_delta_max == 0 or source_delta_max > SOURCE_NORMAL_DELTA_LIMIT_FIXED:
                        continue
                    if target_error_max > NORMAL_TARGET_REIMPORT_LIMIT_FIXED:
                        continue
                    score = (
                        source_delta_max, target_error_max, len(affected), len(incident), pos_error,
                        abs(delta), oi, vi, axis,
                    )
                    choices.append((score, {
                        'logical': None,
                        'object_index': oi,
                        'table_name': obj['table_name'],
                        'head_name': obj['head_name'],
                        'bone': bone,
                        'vertex_index': vi,
                        'axis': 'xyz'[axis],
                        'delta_world_fixed': delta,
                        'delta_world': delta / 256.0,
                        'before_world_fixed': list(old_world),
                        'requested_after_world_fixed': list(requested_t),
                        'expected_reimport_world_fixed': list(reimport),
                        'requested_reimport_error_fixed': pos_error,
                        'before_local_fixed': list(old_local),
                        'after_local_fixed': list(new_local),
                        'local_delta_fixed': [new_local[z] - old_local[z] for z in range(3)],
                        'incident_face_indices': list(int(x) for x in incident),
                        'incident_face_count': len(incident),
                        'affected_vertex_count': len(affected),
                        'affected_vertices': affected_rows,
                        'max_current_source_normal_delta_fixed': source_delta_max,
                        'max_target_reimport_normal_error_fixed': target_error_max,
                        'normal_policy': 'PRESERVE_HISTORICAL_RESIDUAL_PLUS_CURRENT_SOURCE_SETGNORMALS_DELTA',
                        'bounds_header_policy': 'PRESERVE_BYTE_IDENTICAL_INTERIOR_WITNESS',
                    }))
    if not choices:
        raise ValueError('no safe single-bone normal-provenance witness')
    choices.sort(key=lambda x: x[0])
    return choices[0][1]


def patch_normal_bridge(source_physical: pathlib.Path, prepared_source: pathlib.Path, output_physical: pathlib.Path, plan: dict[str, Any]) -> dict[str, Any]:
    model = _parse_with_offsets(prepared_source)
    oi = int(plan['object_index']); vi = int(plan['vertex_index'])
    obj = model['objects'][oi]
    if len(set(obj['bones'])) != 1 or obj['bones'][vi] != plan['bone']:
        raise ValueError('single-bone witness changed since planning')
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
    output_physical.parent.mkdir(parents=True, exist_ok=True)
    output_physical.write_bytes(src)
    return {'allowed_byte_ranges': allowed_ranges, 'changed_records': changed_records}


def _in_ranges(i: int, ranges: list[list[int]]) -> bool:
    return any(int(lo) <= i < int(hi) for lo, hi in ranges)


def compare_normal_bridge(source_physical: pathlib.Path, output_physical: pathlib.Path, prepared_output: pathlib.Path, plan: dict[str, Any], patch: dict[str, Any], tm: list[int]) -> dict[str, Any]:
    sb = pathlib.Path(source_physical).read_bytes(); ob = pathlib.Path(output_physical).read_bytes()
    errors = []
    if len(sb) != len(ob): errors.append('FILE_SIZE')
    if sb[:24] != ob[:24]: errors.append('PHYSICAL_HEADER24_CHANGED')
    diff = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    outside = [i for i in diff if not _in_ranges(i, patch['allowed_byte_ranges'])]
    if outside: errors.append('NON_AUTHORIZED_BYTES_CHANGED')
    if not diff: errors.append('BYTE_IDENTICAL_AFTER_EDIT')
    out_model = _parse_with_offsets(prepared_output)
    obj = out_model['objects'][int(plan['object_index'])]
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
    object_start = int(obj['object_start'])
    bounds_exact = sb[object_start + 44:object_start + 76] == ob[object_start + 44:object_start + 76]
    if not bounds_exact: errors.append('BOUNDS_HEADER_CHANGED')
    result = {
        'check': 'PASS' if not errors else 'FAIL', 'errors': errors,
        'source_sha256': sha256_file(source_physical), 'output_sha256': sha256_file(output_physical),
        'file_size': len(sb), 'diff_byte_count': len(diff), 'diff_bytes_outside_authorized_ranges': outside,
        'physical_header24_byte_identical': sb[:24] == ob[:24],
        'all_non_authorized_bytes_byte_identical': not outside and len(sb) == len(ob),
        'bounds_header_byte_identical': bounds_exact,
        'max_target_reimport_normal_error_fixed': max_target_error,
        'client_modified': False,
    }
    if errors:
        raise RuntimeError('rare rigid normal provenance compare failed: ' + ','.join(errors))
    return result


def _run_one(*, reg, resolver, certifications, settings, project_root: pathlib.Path,
             binding: dict[str, Any], logical: str, work: pathlib.Path) -> dict[str, Any]:
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
    plan = choose_normal_bridge_witness(model, bone_tms); plan['logical'] = logical
    plan_path = work / 'normal_provenance_witness_plan.json'
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

    output = work / 'rebuilt_rare_normal_provenance.smd'
    patch = patch_normal_bridge(source, prepared, output, plan)
    prepared_output = work / 'prepared_output' / pathlib.PurePosixPath(logical)
    prepare_model062_tooling_source(output, prepared_output)
    tm = bone_tms[plan['bone']]
    binary = compare_normal_bridge(source, output, prepared_output, plan, patch, tm)

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
        test='RARE_RIGID_SINGLE_BONE_NORMAL_PROVENANCE_ROUNDTRIP', layer='AUTOMATIC', result='PASS',
        source_sha256=sha256_file(source), artifact_sha256=sha256_file(output),
        metadata={
            'write_scope': 'SINGLE_BONE_INTERIOR_VERTEX_POSITION_WITH_NORMAL_PROVENANCE_DELTA',
            'normal_policy': plan['normal_policy'], 'object_index': plan['object_index'], 'vertex_index': plan['vertex_index'],
            'affected_vertex_count': plan['affected_vertex_count'],
            'max_current_source_normal_delta_fixed': plan['max_current_source_normal_delta_fixed'],
            'max_target_reimport_normal_error_fixed': binary['max_target_reimport_normal_error_fixed'],
            'non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
            'bounds_header_byte_identical': binary['bounds_header_byte_identical'],
            'client_modified': False,
        },
    )
    return {
        'logical': logical, 'check': 'PASS', 'object_index': plan['object_index'], 'head_name': plan['head_name'],
        'bone': plan['bone'], 'vertex_index': plan['vertex_index'], 'delta_world': plan['delta_world'],
        'incident_face_count': plan['incident_face_count'], 'affected_vertex_count': plan['affected_vertex_count'],
        'max_current_source_normal_delta_fixed': plan['max_current_source_normal_delta_fixed'],
        'max_target_reimport_normal_error_fixed': binary['max_target_reimport_normal_error_fixed'],
        'requested_reimport_error_fixed': plan['requested_reimport_error_fixed'],
        'normal_policy': plan['normal_policy'], 'physical_header24_byte_identical': binary['physical_header24_byte_identical'],
        'all_non_authorized_bytes_byte_identical': binary['all_non_authorized_bytes_byte_identical'],
        'bounds_header_byte_identical': binary['bounds_header_byte_identical'],
        'transport_position_error': transport.get('max_position_abs_error'), 'transport_uv_error': transport.get('max_uv_abs_error'),
        'physique_mismatch_count': transport.get('physique_mismatch_count'), 'rebuilt_witness_world_fixed': wc.get('actual_world_fixed'),
        'rebuilt_smd': str(output), 'rebuilt_blend': str(rebuilt_blend), 'certification_id': cert['certification_id'],
        'client_modified': False,
    }


def audit_rare_rigid_normal_provenance_roundtrip(reg, resolver, certifications, settings, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root); work = pathlib.Path(work); work.mkdir(parents=True, exist_ok=True)
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work / 'binding_recheck', bundle=None)
    if binding.get('status') != 'PASS': raise RuntimeError('binding recheck failed')
    rows = []; errors = []
    for logical in CANDIDATES:
        try:
            rows.append(_run_one(reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                                 project_root=project_root, binding=binding, logical=logical,
                                 work=work / pathlib.PurePosixPath(logical).name))
        except Exception as exc:
            errors.append({'logical': logical, 'error': f'{type(exc).__name__}: {exc}'})
    passed = sum(r.get('check') == 'PASS' for r in rows)
    complete = passed == len(CANDIDATES) and not errors
    result = {
        'format': 'PT_RARE_RIGID_SINGLE_BONE_NORMAL_PROVENANCE_ROUNDTRIP_V1',
        'status': 'PASS' if complete else 'FAIL', 'expected': len(CANDIDATES), 'audited': len(rows), 'roundtrip_pass': passed,
        'single_bone_normal_provenance_write_authorized': complete,
        'single_bone_position_write_authorized': complete,
        'write_scope': 'SINGLE_BONE_INTERIOR_VERTEX_POSITION_WITH_HISTORICAL_RESIDUAL_PLUS_CURRENT_SETGNORMALS_DELTA',
        'extent_changing_geometry_write_authorized': False, 'topology_write_authorized': False,
        'multi_bone_deferred': DEFERRED_MULTI_BONE,
        'max_requested_reimport_error_fixed': max([int(r.get('requested_reimport_error_fixed') or 0) for r in rows] or [0]),
        'max_current_source_normal_delta_fixed': max([int(r.get('max_current_source_normal_delta_fixed') or 0) for r in rows] or [0]),
        'max_target_reimport_normal_error_fixed': max([int(r.get('max_target_reimport_normal_error_fixed') or 0) for r in rows] or [0]),
        'non_authorized_bytes_exact_files': sum(bool(r.get('all_non_authorized_bytes_byte_identical')) for r in rows),
        'bounds_header_exact_files': sum(bool(r.get('bounds_header_byte_identical')) for r in rows),
        'physique_mismatch_total': sum(int(r.get('physique_mismatch_count') or 0) for r in rows),
        'errors': errors,
        'source_findings': {
            'SetGNormals': 'face normal contribution is current SourceCode float pipeline; per-vertex vector is integer average then endpoint=position+vector before ReformPhysique',
            'provenance_bridge': 'preserve historical residual (stored runtime vector - current-source vector) and add only the current-source normal delta caused by the edited geometry',
            'ReformPhysique': 'new desired endpoints are serialized through exact source smMatrixInvert; fixed-point forward/inverse loss is measured rather than hidden',
        },
        'policy': {
            'normal': 'never wholesale-regenerate historical normals; only affected vertices receive historical residual + current SourceCode SetGNormals delta',
            'untouched': 'all bytes outside the moved vertex record and affected neighbor endpoint fields remain byte-identical',
            'bounds': 'witness remains inside historical bounds; extent-changing writes remain deferred',
            'multi_bone': 'at_dragon remains deferred until changed normals across different bone transforms are independently proven',
            'client_modified': False,
        },
        'rows': rows, 'client_modified': False,
    }
    rp = work / 'rare_rigid_normal_provenance_roundtrip_report.json'
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'); result['report'] = str(rp)
    return result
