from __future__ import annotations

import hashlib
import json
import math
import pathlib
import struct
from typing import Iterable

from .multilayer_texlink import parse_multilayer_semantics


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _f32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def _load_witness(path: pathlib.Path | str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _object_by_index(report: dict, index: int) -> dict:
    rows = report.get('objects') or []
    if not 0 <= int(index) < len(rows):
        raise ValueError(f'object index out of range: {index}')
    row = rows[int(index)]
    if int(row.get('index', -1)) != int(index):
        raise ValueError(f'object index mismatch: requested={index} row={row.get("index")}')
    return row


def _chain_target(report: dict, edit: dict) -> tuple[dict, dict, dict]:
    oi = int(edit['object_index'])
    fi = int(edit['face_index'])
    si = int(edit['stage_index'])
    corner = int(edit['corner'])
    obj = _object_by_index(report, oi)
    faces = obj.get('face_rows') or []
    if not 0 <= fi < len(faces):
        raise ValueError(f'face index out of range: object={oi} face={fi}')
    face = faces[fi]
    chain = face.get('chain') or []
    if not 0 <= si < len(chain):
        raise ValueError(f'stage index out of range: object={oi} face={fi} stage={si} depth={len(chain)}')
    if not 0 <= corner < 3:
        raise ValueError(f'corner out of range: {corner}')
    return obj, face, chain[si]


def strict_write_texlink_uv_witness(
    source: pathlib.Path | str,
    output: pathlib.Path | str,
    witness_report: pathlib.Path | str,
    *,
    expected_source_sha256: str | None = None,
    report_path: pathlib.Path | str | None = None,
) -> dict:
    """Apply only the UV components explicitly authorized by a witness report.

    The source SMD is copied byte-for-byte and the authorized float fields are
    patched in place. Face pointers, NextTex, hTexture, materials, geometry,
    animation and Physique payloads are never rebuilt or reserialized.
    """
    source = pathlib.Path(source)
    output = pathlib.Path(output)
    data = source.read_bytes()
    source_sha = _sha(data)
    if expected_source_sha256 and source_sha.lower() != str(expected_source_sha256).lower():
        raise RuntimeError(f'source sha256 drift: expected={expected_source_sha256} actual={source_sha}')

    parsed = parse_multilayer_semantics(source)
    if parsed.get('source_semantics') != 'PASS':
        raise RuntimeError('TexLink source semantics are not PASS')
    if int(parsed.get('max_layers') or 0) != 2:
        raise RuntimeError(f'writer V1 requires max_layers=2; got {parsed.get("max_layers")}')

    witness = _load_witness(witness_report)
    if str(witness.get('source_sha256') or '').lower() != source_sha.lower():
        raise RuntimeError('witness source_sha256 does not match source')
    edits = list(witness.get('edits') or [])
    if not edits:
        raise RuntimeError('witness contains no TexLink UV edits')

    out = bytearray(data)
    authorized_ranges: list[list[int]] = []
    applied = []
    seen_targets = set()

    for edit in edits:
        obj, face, link = _chain_target(parsed, edit)
        oi = int(edit['object_index'])
        fi = int(edit['face_index'])
        si = int(edit['stage_index'])
        corner = int(edit['corner'])
        component = str(edit.get('component') or '').lower()
        if component not in {'u', 'v'}:
            raise ValueError(f'unsupported witness component: {component!r}')
        key = (oi, fi, si, corner, component)
        if key in seen_targets:
            raise ValueError(f'duplicate witness target: {key}')
        seen_targets.add(key)

        expected_obj_name = str(edit.get('object_name') or '')
        if expected_obj_name and expected_obj_name.lower() != str(obj.get('name') or '').lower():
            raise RuntimeError(
                f'witness object name mismatch: index={oi} witness={expected_obj_name!r} source={obj.get("name")!r}'
            )
        if int(edit.get('material_id', face.get('material_id'))) != int(face.get('material_id')):
            raise RuntimeError(f'witness material mismatch at object={oi} face={fi}')

        uv = link.get('uv') or []
        before = float(uv[corner][0 if component == 'u' else 1])
        witness_before = float(edit['before'])
        witness_after = float(edit['after'])
        if not _close(before, witness_before, 1e-6):
            raise RuntimeError(
                f'witness source UV mismatch at {key}: source={before:.9g} witness={witness_before:.9g}'
            )
        if not math.isfinite(witness_after) or abs(witness_after) > 1e6:
            raise ValueError(f'unsafe/non-finite witness UV at {key}: {witness_after!r}')
        before_f32 = _f32(before)
        after_f32 = _f32(witness_after)
        if before_f32 == after_f32:
            raise RuntimeError(f'witness edit quantized away at {key}')

        link_offset = int(link['file_offset'])
        field_offset = link_offset + (0 if component == 'u' else 12) + corner * 4
        current = struct.unpack_from('<f', data, field_offset)[0]
        if current != before_f32:
            raise RuntimeError(
                f'file/parser UV mismatch at {key}: file={current:.9g} parser={before_f32:.9g}'
            )
        struct.pack_into('<f', out, field_offset, after_f32)
        authorized_ranges.append([field_offset, field_offset + 4])
        applied.append({
            'object_index': oi,
            'object_name': obj.get('name'),
            'face_index': fi,
            'material_id': int(face.get('material_id')),
            'stage_index': si,
            'corner': corner,
            'component': component,
            'texlink_index': int(link.get('texlink_index')),
            'texlink_file_offset': link_offset,
            'field_file_offset': field_offset,
            'before': before_f32,
            'after': after_f32,
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bytes(out))
    output_sha = _sha(bytes(out))
    if output_sha == source_sha:
        raise RuntimeError('TexLink witness output is byte-identical to source')

    rebuilt = parse_multilayer_semantics(output)
    if rebuilt.get('source_semantics') != 'PASS':
        raise RuntimeError('rebuilt TexLink semantics are not PASS')

    result = {
        'tool': 'PT_MULTILAYER_TEXLINK_STRICT_WRITER_V1',
        'source': str(source),
        'output': str(output),
        'source_sha256': source_sha,
        'output_sha256': output_sha,
        'edit_count': len(applied),
        'applied_edits': applied,
        'authorized_byte_ranges': authorized_ranges,
        'source_semantics': parsed.get('source_semantics'),
        'rebuilt_semantics': rebuilt.get('source_semantics'),
        'htexture_slot_mapping': rebuilt.get('htexture_slot_mapping'),
        'client_modified': False,
        'check': 'PASS',
    }
    if report_path:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def _structure_signature(report: dict) -> list:
    rows = []
    for obj in report.get('objects') or []:
        faces = []
        for face in obj.get('face_rows') or []:
            chain = []
            for link in face.get('chain') or []:
                chain.append((
                    int(link.get('texlink_index')),
                    int(link.get('stage_index')),
                    int(link.get('hTexture')),
                    int(link.get('next')),
                ))
            faces.append((
                tuple(int(v) for v in face.get('vertices') or []),
                int(face.get('material_id')),
                tuple(chain),
            ))
        rows.append((
            int(obj.get('index')),
            str(obj.get('name')),
            int(obj.get('vertices')),
            int(obj.get('faces')),
            int(obj.get('texlinks')),
            tuple(faces),
        ))
    return rows


def compare_texlink_roundtrip(
    source: pathlib.Path | str,
    output: pathlib.Path | str,
    witness_report: pathlib.Path | str,
    *,
    report_path: pathlib.Path | str | None = None,
) -> dict:
    source = pathlib.Path(source)
    output = pathlib.Path(output)
    sb = source.read_bytes()
    ob = output.read_bytes()
    s = parse_multilayer_semantics(source)
    o = parse_multilayer_semantics(output)
    witness = _load_witness(witness_report)
    errors: list[str] = []

    if len(sb) != len(ob):
        errors.append('FILE_SIZE')
    if s.get('source_semantics') != 'PASS':
        errors.append('SOURCE_SEMANTICS')
    if o.get('source_semantics') != 'PASS':
        errors.append('OUTPUT_SEMANTICS')
    if _structure_signature(s) != _structure_signature(o):
        errors.append('TEXLINK_STRUCTURE')
    if s.get('materials') != o.get('materials'):
        errors.append('MATERIALS')

    expected_ranges: list[list[int]] = []
    expected_bytes = set()
    witness_checks = []
    for edit in list(witness.get('edits') or []):
        _obj_s, _face_s, link_s = _chain_target(s, edit)
        _obj_o, _face_o, link_o = _chain_target(o, edit)
        corner = int(edit['corner'])
        component = str(edit.get('component') or '').lower()
        ci = 0 if component == 'u' else 1
        before = float(link_s['uv'][corner][ci])
        after = float(link_o['uv'][corner][ci])
        expected_before = _f32(float(edit['before']))
        expected_after = _f32(float(edit['after']))
        if before != expected_before:
            errors.append('WITNESS_SOURCE_VALUE')
        if after != expected_after:
            errors.append('WITNESS_OUTPUT_VALUE')
        field_offset = int(link_s['file_offset']) + (0 if component == 'u' else 12) + corner * 4
        expected_ranges.append([field_offset, field_offset + 4])
        expected_bytes.update(range(field_offset, field_offset + 4))
        witness_checks.append({
            'object_index': int(edit['object_index']),
            'face_index': int(edit['face_index']),
            'stage_index': int(edit['stage_index']),
            'corner': corner,
            'component': component,
            'before': before,
            'after': after,
            'expected_after': expected_after,
            'field_file_offset': field_offset,
        })

    if not witness_checks:
        errors.append('WITNESS_EMPTY')

    diff_bytes = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    if len(sb) != len(ob):
        diff_outside = ['SIZE_MISMATCH']
    else:
        diff_outside = [i for i in diff_bytes if i not in expected_bytes]
    if diff_outside:
        errors.append('NON_WITNESS_BYTES_CHANGED')
    if not diff_bytes:
        errors.append('BYTE_IDENTICAL_AFTER_EDIT')

    # Because structure includes hTexture/NextTex values and the byte diff is
    # restricted to U/V float fields, these pointer fields are byte-identical.
    htexture_nexttex_byte_identical = not bool(diff_outside) and len(sb) == len(ob)

    result = {
        'tool': 'PT_MULTILAYER_TEXLINK_ROUNDTRIP_COMPARE_V1',
        'source': str(source),
        'output': str(output),
        'source_sha256': _sha(sb),
        'output_sha256': _sha(ob),
        'source_semantics': s.get('source_semantics'),
        'output_semantics': o.get('source_semantics'),
        'max_layers_preserved': s.get('max_layers') == o.get('max_layers'),
        'multilayer_faces_preserved': s.get('multilayer_faces') == o.get('multilayer_faces'),
        'htexture_slot_mapping_preserved': s.get('htexture_slot_mapping') == o.get('htexture_slot_mapping') == 'SMATERIAL_SM_TEXTURE_SLOT_EXACT',
        'texlink_structure_exact': _structure_signature(s) == _structure_signature(o),
        'htexture_nexttex_byte_identical': htexture_nexttex_byte_identical,
        'materials_exact': s.get('materials') == o.get('materials'),
        'witness_checks': witness_checks,
        'authorized_byte_ranges': expected_ranges,
        'diff_byte_count': len(diff_bytes),
        'diff_bytes_outside_witness': diff_outside,
        'non_witness_bytes_byte_identical': not bool(diff_outside) and len(sb) == len(ob),
        'byte_identical': sb == ob,
        'intentional_uv_edit': True,
        'errors': errors,
        'client_modified': False,
        'check': 'PASS' if not errors else 'FAIL',
    }
    if report_path:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if errors:
        raise RuntimeError('TexLink roundtrip compare failed: ' + ','.join(errors))
    return result
