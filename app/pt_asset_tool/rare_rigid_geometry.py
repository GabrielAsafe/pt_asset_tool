from __future__ import annotations

import json
import math
import pathlib
import struct
from typing import Any

from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_context import RARE_SMD_FILES
from .rare_support import prepare_model062_tooling_source
from .utils import norm_path

SH, SI, SO = 556, 40, 2236
SV, SF, ST, SR, SP, SS, SM = 24, 36, 32, 20, 16, 16, 64
FONE = 256
O_PHYS, O_NV, O_NF, O_NT = 16, 84, 88, 92
O_NR, O_NP, O_NS = 684, 688, 692
O_TM = 240
OBJ_HEAD_TYPE_NEW_NORMAL = 0x80000000


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from('<i', data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from('<I', data, off)[0]


def _cstr(raw: bytes) -> str:
    return raw.split(b'\0', 1)[0].decode('latin1', 'replace')


def _mget(m: list[int], r: int, c: int) -> int:
    return m[(r - 1) * 4 + (c - 1)]


def _trunc_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError('integer division by zero')
    return math.trunc(a / b)


def _transform_point_fixed(v: tuple[int, int, int], m: list[int]) -> tuple[int, int, int]:
    x, y, z = v
    rx = x * _mget(m, 1, 1) + y * _mget(m, 2, 1) + z * _mget(m, 3, 1)
    ry = x * _mget(m, 1, 2) + y * _mget(m, 2, 2) + z * _mget(m, 3, 2)
    rz = x * _mget(m, 1, 3) + y * _mget(m, 2, 3) + z * _mget(m, 3, 3)
    return (
        (rx >> 8) + _mget(m, 4, 1),
        (ry >> 8) + _mget(m, 4, 2),
        (rz >> 8) + _mget(m, 4, 3),
    )


def _invert_matrix_source(a: list[int]) -> list[int]:
    """Integer structure of smMatrixInvert used by ReformPhysique."""
    if abs(_mget(a, 4, 4) - FONE) > 1:
        raise ValueError(f"matrix _44 invalid: {_mget(a,4,4)}")
    if any(abs(_mget(a, r, 4)) > 1 for r in (1, 2, 3)):
        raise ValueError('matrix affine column invalid')

    a11, a12, a13 = _mget(a,1,1), _mget(a,1,2), _mget(a,1,3)
    a21, a22, a23 = _mget(a,2,1), _mget(a,2,2), _mget(a,2,3)
    a31, a32, a33 = _mget(a,3,1), _mget(a,3,2), _mget(a,3,3)
    det = (
        a11 * ((a22*a33 - a23*a32) >> 8)
        - a12 * ((a21*a33 - a23*a31) >> 8)
        + a13 * ((a21*a32 - a22*a31) >> 8)
    ) >> 8
    if det == 0:
        raise ValueError('matrix determinant is zero')
    det_inv = _trunc_div(FONE << 8, det)

    q = [0] * 16
    q[0]  = (det_inv * ((a22*a33 - a23*a32) >> 8)) >> 8
    q[1]  = -((det_inv * ((a12*a33 - a13*a32) >> 8)) >> 8)
    q[2]  = (det_inv * ((a12*a23 - a13*a22) >> 8)) >> 8
    q[4]  = -((det_inv * ((a21*a33 - a23*a31) >> 8)) >> 8)
    q[5]  = (det_inv * ((a11*a33 - a13*a31) >> 8)) >> 8
    q[6]  = -((det_inv * ((a11*a23 - a13*a21) >> 8)) >> 8)
    q[8]  = (det_inv * ((a21*a32 - a22*a31) >> 8)) >> 8
    q[9]  = -((det_inv * ((a11*a32 - a12*a31) >> 8)) >> 8)
    q[10] = (det_inv * ((a11*a22 - a12*a21) >> 8)) >> 8
    a41, a42, a43 = _mget(a,4,1), _mget(a,4,2), _mget(a,4,3)
    q[12] = -((a41*q[0] + a42*q[4] + a43*q[8]) >> 8)
    q[13] = -((a41*q[1] + a42*q[5] + a43*q[9]) >> 8)
    q[14] = -((a41*q[2] + a42*q[6] + a43*q[10]) >> 8)
    q[15] = FONE
    return q


def _object_layout(start: int, nv: int, nf: int, nt: int, nr: int, np: int, ns: int, physique: bool):
    vertices = start + SO
    faces = vertices + nv * SV
    texlinks = faces + nf * SF
    tmrot = texlinks + nt * ST
    tmpos = tmrot + nr * SR
    tmscale = tmpos + np * SP
    prevrot = tmscale + ns * SS
    phys = prevrot + nr * SM if physique else None
    end = (phys + nv * 32) if physique else (prevrot + nr * SM)
    return vertices, faces, phys, end


def _parse_rigid_model(path: pathlib.Path) -> dict[str, Any]:
    data = pathlib.Path(path).read_bytes()
    if len(data) < SH or not data.startswith(b'SMD Model data Ver 0.62'):
        raise ValueError('not normalized Model0.62')
    oc = _i32(data, 24)
    if oc <= 0 or SH + oc * SI > len(data):
        raise ValueError(f'invalid object count {oc}')
    objects = []
    for idx in range(oc):
        io = SH + idx * SI
        table_name = _cstr(data[io:io+32])
        length = _i32(data, io + 32)
        start = _i32(data, io + 36)
        if start < 0 or length < SO or start + length > len(data):
            raise ValueError(f'object[{idx}] invalid bounds')
        raw = data[start:start+SO]
        head = _u32(raw, 0)
        head_name = _cstr(raw[172:204])
        nv, nf, nt, nr, np, ns = [_i32(raw, o) for o in (O_NV,O_NF,O_NT,O_NR,O_NP,O_NS)]
        if min(nv,nf,nt,nr,np,ns) < 0:
            raise ValueError(f'object[{idx}] negative count')
        physique = _u32(raw, O_PHYS) != 0
        if not physique:
            raise ValueError(f'object[{idx}] expected Physique')
        vb, fb, ph, end = _object_layout(start,nv,nf,nt,nr,np,ns,physique)
        if end != start + length:
            raise ValueError(f'object[{idx}] length mismatch expected={start+length} got={end}')
        verts = [struct.unpack_from('<6i', data, vb + i*SV) for i in range(nv)]
        faces = [struct.unpack_from('<4H', data, fb + i*SF) for i in range(nf)]
        bones = [_cstr(data[ph+i*32:ph+(i+1)*32]) for i in range(nv)]
        if any(not b for b in bones):
            raise ValueError(f'object[{idx}] empty Physique name')
        objects.append({
            'index': idx,
            'table_name': table_name,
            'head_name': head_name,
            'head': head,
            'new_normal_flag': bool(head & OBJ_HEAD_TYPE_NEW_NORMAL),
            'vertices': verts,
            'faces': faces,
            'bones': bones,
            'stored_bounds': {
                'maxZ': _i32(raw,44), 'maxY': _i32(raw,52), 'maxX': _i32(raw,60),
                'dBound': _i32(raw,68), 'Bound': _i32(raw,72),
            },
        })
    return {'objects': objects}


def _parse_skeleton_tms(path: pathlib.Path) -> dict[str, list[int]]:
    data = pathlib.Path(path).read_bytes()
    if len(data) < SH or not data.startswith(b'SMD Model data Ver 0.62'):
        raise ValueError('motion SMB is not Model0.62 skeleton container')
    oc = _i32(data,24)
    bones: dict[str, list[int]] = {}
    for idx in range(oc):
        io = SH + idx * SI
        start = _i32(data, io + 36)
        if start < 0 or start + SO > len(data):
            raise ValueError(f'skeleton object[{idx}] invalid')
        raw = data[start:start+SO]
        name = _cstr(raw[172:204])
        if not name:
            raise ValueError(f'skeleton object[{idx}] empty name')
        if name in bones:
            raise ValueError(f'duplicate skeleton bone {name!r}')
        bones[name] = list(struct.unpack_from('<16i', raw, O_TM))
    return bones


def _error_stats(errors: list[tuple[int,int,int]]) -> dict[str, int]:
    if not errors:
        return {'count':0,'exact':0,'within1':0,'within2':0,'within8':0,'max_abs':0}
    maxes = [max(abs(x) for x in e) for e in errors]
    return {
        'count': len(errors),
        'exact': sum(m == 0 for m in maxes),
        'within1': sum(m <= 1 for m in maxes),
        'within2': sum(m <= 2 for m in maxes),
        'within8': sum(m <= 8 for m in maxes),
        'max_abs': max(maxes),
    }


def _source_bounds(points: list[tuple[int,int,int]]) -> dict[str,int]:
    if not points:
        return {'maxZ':0,'maxY':0,'maxX':0,'dBound':0,'Bound':0}
    maxx = max(abs(p[0]) for p in points)
    maxz = max(abs(p[1]) for p in points)  # Source AddVertex historical axis naming.
    maxy = max(abs(p[2]) for p in points)
    db = 0
    for x,y,z in points:
        xx, yy, zz = x >> 8, y >> 8, z >> 8
        db = max(db, abs(xx*xx + yy*yy + zz*zz))
    return {'maxZ':maxz,'maxY':maxy,'maxX':maxx,'dBound':db,'Bound':math.trunc(math.sqrt(db))}


def audit_rare_rigid_geometry_preflight(reg, resolver, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    """Audit the lossy Physique coordinate bridge before any Model0.62 geometry writer.

    This intentionally does not write a SMD.  It proves which rare files are
    single-bone rigid pieces and measures the fixed-point loss of the exact
    source matrix forward/inverse path for positions and serialized normal
    endpoints.
    """
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    binding = audit_rare_rigid_binding(reg, resolver, project_root=project_root, work=work/'binding')
    if binding.get('status') != 'PASS':
        return {
            'format':'PT_RARE_RIGID_GEOMETRY_PREFLIGHT_V1', 'status':'FAIL',
            'error':'binding audit failed', 'binding':binding,
            'geometry_write_authorized':False, 'client_modified':False,
        }

    rows = []
    errors = []
    total_objects = total_vertices = total_faces = mixed_faces_total = 0
    pos_errors_all: list[tuple[int,int,int]] = []
    normal_errors_all: list[tuple[int,int,int]] = []
    bounds_d_exact = bounds_b_exact = 0
    bounds_coord_delta_max = 0

    for brow in binding.get('rows') or []:
        logical = norm_path(brow.get('logical') or '')
        try:
            src = pathlib.Path(resolver.resolve(logical, required=True))
            prepared = work/'prepared_model062'/pathlib.PurePosixPath(logical)
            prepare_model062_tooling_source(src, prepared)
            motion = norm_path(brow.get('resolved_motion_smb') or '')
            motion_path = pathlib.Path(resolver.resolve(motion, required=True))
            bones = _parse_skeleton_tms(motion_path)
            model = _parse_rigid_model(prepared)

            file_pos_errors: list[tuple[int,int,int]] = []
            file_normal_errors: list[tuple[int,int,int]] = []
            object_rows = []
            file_mixed_faces = 0
            all_single_bone_objects = True
            file_bounds_d_exact = file_bounds_b_exact = 0
            file_bounds_coord_delta_max = 0

            for obj in model['objects']:
                obones = obj['bones']
                bset = sorted(set(obones), key=str.lower)
                all_single_bone_objects = all_single_bone_objects and len(bset) == 1
                mixed = 0
                for f in obj['faces']:
                    if any(v >= len(obones) for v in f[:3]):
                        raise ValueError(f"{obj['head_name']}: face vertex out of range")
                    if len({obones[v] for v in f[:3]}) > 1:
                        mixed += 1
                file_mixed_faces += mixed

                world_points: list[tuple[int,int,int]] = []
                for v, bone_name in zip(obj['vertices'], obones):
                    tm = bones.get(bone_name)
                    if tm is None:
                        raise ValueError(f"missing bone {bone_name!r}")
                    inv = _invert_matrix_source(tm)
                    pos = (v[0],v[1],v[2])
                    normal_point = (v[3],v[4],v[5])
                    wpos = _transform_point_fixed(pos, tm)
                    wnormal = _transform_point_fixed(normal_point, tm)
                    bpos = _transform_point_fixed(wpos, inv)
                    bnormal = _transform_point_fixed(wnormal, inv)
                    pe = tuple(bpos[i] - pos[i] for i in range(3))
                    ne = tuple(bnormal[i] - normal_point[i] for i in range(3))
                    file_pos_errors.append(pe); pos_errors_all.append(pe)
                    file_normal_errors.append(ne); normal_errors_all.append(ne)
                    world_points.append(wpos)

                rb = _source_bounds(world_points)
                sb = obj['stored_bounds']
                coord_delta = max(abs(rb[k] - sb[k]) for k in ('maxX','maxY','maxZ'))
                d_exact = rb['dBound'] == sb['dBound']
                b_exact = rb['Bound'] == sb['Bound']
                file_bounds_d_exact += int(d_exact); bounds_d_exact += int(d_exact)
                file_bounds_b_exact += int(b_exact); bounds_b_exact += int(b_exact)
                file_bounds_coord_delta_max = max(file_bounds_coord_delta_max, coord_delta)
                bounds_coord_delta_max = max(bounds_coord_delta_max, coord_delta)

                object_rows.append({
                    'index': obj['index'],
                    'table_name': obj['table_name'],
                    'head_name': obj['head_name'],
                    'vertices': len(obj['vertices']),
                    'faces': len(obj['faces']),
                    'bind_bone_count': len(bset),
                    'bind_bones': bset,
                    'mixed_bone_faces': mixed,
                    'new_normal_flag': obj['new_normal_flag'],
                    'reconstructed_bounds': rb,
                    'stored_bounds': sb,
                    'reconstructed_max_extent_delta_fixed': coord_delta,
                    'dBound_exact_after_reconstruct': d_exact,
                    'Bound_exact_after_reconstruct': b_exact,
                })

            total_objects += len(model['objects'])
            fv = sum(len(o['vertices']) for o in model['objects'])
            ff = sum(len(o['faces']) for o in model['objects'])
            total_vertices += fv; total_faces += ff; mixed_faces_total += file_mixed_faces
            single_bone_candidate = all_single_bone_objects and file_mixed_faces == 0
            rows.append({
                'logical': logical,
                'motion_smb': motion,
                'objects': len(model['objects']),
                'vertices': fv,
                'faces': ff,
                'single_bone_objects_only': all_single_bone_objects,
                'mixed_bone_faces': file_mixed_faces,
                'single_bone_rigid_geometry_candidate': single_bone_candidate,
                'position_forward_inverse': _error_stats(file_pos_errors),
                'normal_endpoint_forward_inverse': _error_stats(file_normal_errors),
                'bounds_dBound_exact_objects': file_bounds_d_exact,
                'bounds_Bound_exact_objects': file_bounds_b_exact,
                'bounds_max_extent_delta_fixed': file_bounds_coord_delta_max,
                'objects_detail': object_rows,
            })
        except Exception as exc:
            errors.append({'logical':logical,'error':f'{type(exc).__name__}: {exc}'})

    expected = len(RARE_SMD_FILES)
    candidates = [r['logical'] for r in rows if r.get('single_bone_rigid_geometry_candidate')]
    deferred = [r['logical'] for r in rows if not r.get('single_bone_rigid_geometry_candidate')]
    status = 'PASS' if len(rows) == expected and not errors else 'FAIL'
    result = {
        'format':'PT_RARE_RIGID_GEOMETRY_PREFLIGHT_V1',
        'status':status,
        'expected':expected,
        'audited':len(rows),
        'objects':total_objects,
        'vertices':total_vertices,
        'faces':total_faces,
        'mixed_bone_faces':mixed_faces_total,
        'single_bone_candidate_files':candidates,
        'single_bone_candidate_count':len(candidates),
        'multi_bone_deferred_files':deferred,
        'position_forward_inverse':_error_stats(pos_errors_all),
        'normal_endpoint_forward_inverse':_error_stats(normal_errors_all),
        'bounds_dBound_exact_objects':bounds_d_exact,
        'bounds_Bound_exact_objects':bounds_b_exact,
        'bounds_max_extent_delta_fixed':bounds_coord_delta_max,
        'errors':errors,
        'single_bone_rigid_geometry_preflight_complete_candidate': status == 'PASS' and len(candidates) == 5,
        'at_dragon_arbitrary_geometry_deferred': any(x.lower().endswith('/at_dragon.smd') for x in deferred),
        'geometry_write_authorized':False,
        'source_findings':{
            'SetGNormals':'computed before ReformPhysique; serialized nx/ny/nz are a normal endpoint, not a unit-vector field',
            'ReformPhysique':'position and normal endpoint are both transformed by source smMatrixInvert(bone.Tm)',
            'SaveFile':'writes transformed smVERTEX bytes followed by 32-byte Physique bone names',
            'loss_note':'forward/inverse fixed-point matrices are lossy; untouched position/normal bytes must never be regenerated',
        },
        'policy':{
            'single_bone_candidates':'classification only; writer requires a separate witness/roundtrip gate',
            'multi_bone':'mixed-bone faces require independent changed-normal proof before deformation writes',
            'untouched_bytes':'future writer must preserve untouched vertex and normal endpoint bytes exactly',
            'client_modified':False,
        },
        'rows':rows,
        'client_modified':False,
    }
    report = work/'rare_rigid_geometry_preflight_report.json'
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result['report'] = str(report)
    return result
