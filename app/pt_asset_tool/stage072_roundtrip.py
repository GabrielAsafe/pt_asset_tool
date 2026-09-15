from __future__ import annotations

import hashlib
import json
import math
import pathlib
import struct

from .stage072_corpus import (
    DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, STAGE_VERTEX_SIZE, STAGE_FACE_SIZE,
    TEXLINK_SIZE, LIGHT_SIZE, parse_stage072,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _f32(v: float) -> float:
    return struct.unpack('<f', struct.pack('<f', float(v)))[0]


def _layout(parsed: dict) -> dict:
    counts = parsed['counts']
    mat_start = DFILE_HEADER_SIZE + STAGE_HEADER_SIZE
    mat_end = mat_start + int(parsed['material_blob_size'])
    vertex_base = mat_end
    face_base = vertex_base + int(counts['vertices']) * STAGE_VERTEX_SIZE
    tex_base = face_base + int(counts['faces']) * STAGE_FACE_SIZE
    light_base = tex_base + int(counts['texlinks']) * TEXLINK_SIZE
    area_base = light_base + int(counts['lights']) * LIGHT_SIZE
    return {
        'stage_header_start': DFILE_HEADER_SIZE,
        'stage_header_end': DFILE_HEADER_SIZE + STAGE_HEADER_SIZE,
        'material_start': mat_start,
        'material_end': mat_end,
        'vertex_base': vertex_base,
        'face_base': face_base,
        'texlink_base': tex_base,
        'light_base': light_base,
        'area_base': area_base,
    }


def _load_witness(path: pathlib.Path | str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _target(parsed: dict, edit: dict) -> tuple[dict, int, int]:
    payload = parsed.get('payload') or {}
    faces = payload.get('faces') or []
    fi = int(edit['face_index'])
    stage = int(edit['stage_index'])
    corner = int(edit['corner'])
    if not 0 <= fi < len(faces):
        raise ValueError(f'face index out of range: {fi}')
    face = faces[fi]
    chain = face.get('texlink_chain') or []
    if not 0 <= stage < len(chain):
        raise ValueError(f'stage index out of range: face={fi} stage={stage} depth={len(chain)}')
    if not 0 <= corner < 3:
        raise ValueError(f'corner out of range: {corner}')
    ti = int(chain[stage])
    return face, ti, corner


def strict_write_stage072_uv_witness(
    source: pathlib.Path | str,
    output: pathlib.Path | str,
    witness_report: pathlib.Path | str,
    *,
    expected_source_sha256: str | None = None,
    report_path: pathlib.Path | str | None = None,
) -> dict:
    source = pathlib.Path(source)
    output = pathlib.Path(output)
    data = source.read_bytes()
    source_sha = _sha(data)
    if expected_source_sha256 and source_sha.lower() != str(expected_source_sha256).lower():
        raise RuntimeError(f'source sha256 drift: expected={expected_source_sha256} actual={source_sha}')

    parsed = parse_stage072(source, include_payload=True)
    if parsed.get('full_parse') != 'PASS':
        raise RuntimeError('Stage0.72 source parser is not PASS')

    witness = _load_witness(witness_report)
    if str(witness.get('source_sha256') or '').lower() != source_sha.lower():
        raise RuntimeError('witness source_sha256 does not match source')
    edits = list(witness.get('uv_edits') or witness.get('edits') or [])
    if not edits:
        raise RuntimeError('witness contains no Stage0.72 UV edits')

    layout = _layout(parsed)
    out = bytearray(data)
    authorized_ranges: list[list[int]] = []
    applied = []
    seen = set()
    for edit in edits:
        face, ti, corner = _target(parsed, edit)
        fi = int(edit['face_index'])
        stage = int(edit['stage_index'])
        component = str(edit.get('component') or '').lower()
        if component not in {'u', 'v'}:
            raise ValueError(f'unsupported UV component: {component!r}')
        key = (fi, stage, corner, component)
        if key in seen:
            raise ValueError(f'duplicate witness target: {key}')
        seen.add(key)

        if int(edit.get('material_id', face['material'])) != int(face['material']):
            raise RuntimeError(f'witness material mismatch at face={fi}')
        tl = parsed['payload']['texlinks'][ti]
        ci = 0 if component == 'u' else 1
        before = float((tl['u'] if component == 'u' else tl['v'])[corner])
        witness_before = _f32(float(edit['before']))
        witness_after = _f32(float(edit['after']))
        if _f32(before) != witness_before:
            raise RuntimeError(f'witness source UV mismatch at {key}: source={before} witness={witness_before}')
        if not math.isfinite(witness_after) or abs(witness_after) > 1e6:
            raise ValueError(f'unsafe/non-finite witness UV at {key}: {witness_after!r}')
        if witness_after == witness_before:
            raise RuntimeError(f'witness edit quantized away at {key}')

        link_offset = layout['texlink_base'] + ti * TEXLINK_SIZE
        field_offset = link_offset + (0 if component == 'u' else 12) + corner * 4
        current = struct.unpack_from('<f', data, field_offset)[0]
        if current != witness_before:
            raise RuntimeError(f'file/parser UV mismatch at {key}: file={current} parser={witness_before}')
        struct.pack_into('<f', out, field_offset, witness_after)
        authorized_ranges.append([field_offset, field_offset + 4])
        applied.append({
            'face_index': fi,
            'material_id': int(face['material']),
            'stage_index': stage,
            'corner': corner,
            'component': component,
            'texlink_index': ti,
            'texlink_file_offset': link_offset,
            'field_file_offset': field_offset,
            'before': witness_before,
            'after': witness_after,
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bytes(out))
    output_sha = _sha(bytes(out))
    if output_sha == source_sha:
        raise RuntimeError('Stage0.72 witness output is byte-identical to source')
    rebuilt = parse_stage072(output, include_payload=True)
    if rebuilt.get('full_parse') != 'PASS':
        raise RuntimeError('rebuilt Stage0.72 parser is not PASS')

    result = {
        'tool': 'PT_STAGE072_STRICT_UV_WRITER_V1',
        'source': str(source),
        'output': str(output),
        'source_sha256': source_sha,
        'output_sha256': output_sha,
        'edit_count': len(applied),
        'applied_edits': applied,
        'authorized_byte_ranges': authorized_ranges,
        'source_parse': parsed.get('full_parse'),
        'rebuilt_parse': rebuilt.get('full_parse'),
        'client_modified': False,
        'check': 'PASS',
    }
    if report_path:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def _semantic_signature(parsed: dict) -> dict:
    payload = parsed.get('payload') or {}
    return {
        'counts': parsed.get('counts'),
        'file_header': parsed.get('file_header'),
        'runtime_pointers': parsed.get('runtime_pointers'),
        'lighting': parsed.get('lighting'),
        'stage_map_rect': parsed.get('stage_map_rect'),
        'material_face_counts': parsed.get('material_face_counts'),
        'texlink_depth_face_counts': parsed.get('texlink_depth_face_counts'),
        'max_texlink_depth': parsed.get('max_texlink_depth'),
        'materials': parsed.get('materials'),
        'faces': [
            (tuple(f.get('vertices') or []), int(f.get('material')), tuple(f.get('texlink_chain') or []))
            for f in payload.get('faces') or []
        ],
        'lights': payload.get('lights'),
        'texlink_pointer_fields': [
            (int(t.get('hTexture')), int(t.get('next_idx'))) for t in payload.get('texlinks') or []
        ],
        'vertex_colors': [tuple(v.get('color') or []) for v in payload.get('vertices') or []],
        'area_encoding': (parsed.get('area') or {}).get('encoding'),
        'opaque_trailing_bytes': (parsed.get('area') or {}).get('opaque_trailing_bytes'),
    }


def compare_stage072_uv_roundtrip(
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
    s = parse_stage072(source, include_payload=True)
    o = parse_stage072(output, include_payload=True)
    witness = _load_witness(witness_report)
    errors: list[str] = []
    if len(sb) != len(ob): errors.append('FILE_SIZE')
    if s.get('full_parse') != 'PASS': errors.append('SOURCE_PARSE')
    if o.get('full_parse') != 'PASS': errors.append('OUTPUT_PARSE')
    if _semantic_signature(s) != _semantic_signature(o): errors.append('NON_UV_SEMANTICS')

    layout_s = _layout(s)
    layout_o = _layout(o)
    if layout_s != layout_o: errors.append('LAYOUT')

    expected_bytes = set()
    witness_checks = []
    for edit in list(witness.get('uv_edits') or witness.get('edits') or []):
        face_s, ti_s, corner = _target(s, edit)
        face_o, ti_o, _ = _target(o, edit)
        if ti_s != ti_o: errors.append('WITNESS_TEXLINK_INDEX')
        component = str(edit.get('component') or '').lower()
        src_tl = s['payload']['texlinks'][ti_s]
        out_tl = o['payload']['texlinks'][ti_o]
        src_val = _f32(float((src_tl['u'] if component == 'u' else src_tl['v'])[corner]))
        out_val = _f32(float((out_tl['u'] if component == 'u' else out_tl['v'])[corner]))
        exp_before = _f32(float(edit['before']))
        exp_after = _f32(float(edit['after']))
        if src_val != exp_before: errors.append('WITNESS_SOURCE_VALUE')
        if out_val != exp_after: errors.append('WITNESS_OUTPUT_VALUE')
        field_offset = layout_s['texlink_base'] + ti_s*TEXLINK_SIZE + (0 if component == 'u' else 12) + corner*4
        expected_bytes.update(range(field_offset, field_offset+4))
        witness_checks.append({
            'face_index': int(edit['face_index']), 'stage_index': int(edit['stage_index']),
            'corner': corner, 'component': component, 'texlink_index': ti_s,
            'before': src_val, 'after': out_val, 'field_file_offset': field_offset,
        })

    diff_positions = [i for i, (a, b) in enumerate(zip(sb, ob)) if a != b]
    unexpected_diff_positions = [i for i in diff_positions if i not in expected_bytes]
    if unexpected_diff_positions: errors.append('UNEXPECTED_BYTE_DIFF')
    if not diff_positions: errors.append('NO_BYTE_DIFF')

    area_base = layout_s['area_base']
    material_exact = sb[layout_s['material_start']:layout_s['material_end']] == ob[layout_o['material_start']:layout_o['material_end']]
    stage_header_exact = sb[layout_s['stage_header_start']:layout_s['stage_header_end']] == ob[layout_o['stage_header_start']:layout_o['stage_header_end']]
    faces_exact = sb[layout_s['face_base']:layout_s['texlink_base']] == ob[layout_o['face_base']:layout_o['texlink_base']]
    lights_exact = sb[layout_s['light_base']:area_base] == ob[layout_o['light_base']:layout_o['area_base']]
    area_exact = sb[area_base:] == ob[layout_o['area_base']:]
    geometry_exact = sb[layout_s['vertex_base']:layout_s['face_base']] == ob[layout_o['vertex_base']:layout_o['face_base']]

    hnext_exact = True
    ntex = int(s['counts']['texlinks'])
    for ti in range(ntex):
        so = layout_s['texlink_base'] + ti*TEXLINK_SIZE + 24
        oo = layout_o['texlink_base'] + ti*TEXLINK_SIZE + 24
        if sb[so:so+8] != ob[oo:oo+8]:
            hnext_exact = False
            break

    opaque_n = int((s.get('area') or {}).get('opaque_trailing_bytes') or 0)
    opaque_exact = (sb[-opaque_n:] == ob[-opaque_n:]) if opaque_n else True
    checks = {
        'stage_header_byte_identical': stage_header_exact,
        'materials_byte_identical': material_exact,
        'geometry_byte_identical': geometry_exact,
        'faces_byte_identical': faces_exact,
        'lights_byte_identical': lights_exact,
        'stage_area_and_suffix_byte_identical': area_exact,
        'opaque_trailing_byte_identical': opaque_exact,
        'htexture_nexttex_byte_identical': hnext_exact,
        'non_witness_bytes_byte_identical': not unexpected_diff_positions,
    }
    for name, ok in checks.items():
        if not ok: errors.append(name.upper())

    result = {
        'tool': 'PT_STAGE072_STRICT_UV_ROUNDTRIP_COMPARE_V1',
        'source': str(source), 'output': str(output),
        'source_sha256': _sha(sb), 'output_sha256': _sha(ob),
        'source_parse': s.get('full_parse'), 'output_parse': o.get('full_parse'),
        'area_encoding': (s.get('area') or {}).get('encoding'),
        'opaque_trailing_bytes': opaque_n,
        'max_texlink_depth': int(s.get('max_texlink_depth') or 0),
        'witness_checks': witness_checks,
        'diff_byte_count': len(diff_positions),
        'unexpected_diff_byte_count': len(unexpected_diff_positions),
        **checks,
        'errors': errors,
        'check': 'PASS' if not errors else 'FAIL',
        'client_modified': False,
    }
    if report_path:
        rp = pathlib.Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if errors:
        raise RuntimeError(f'Stage0.72 strict UV roundtrip compare failed: {errors[:8]}')
    return result
