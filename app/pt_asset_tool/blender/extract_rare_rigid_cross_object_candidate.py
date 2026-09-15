from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback

import bpy

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORMAT = 'PT_RARE_RIGID_CROSS_OBJECT_CANDIDATE_EXTRACT_V2'
_STAGE = 'BOOTSTRAP'


def _parse(argv):
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--max-changed', type=int, default=8)
    p.add_argument('--min-objects', type=int, default=2)
    p.add_argument('--max-objects', type=int, default=3)
    return p.parse_args(argv)


def _report_hint(argv):
    try:
        i = list(argv).index('--report')
        return pathlib.Path(list(argv)[i + 1]).expanduser().resolve()
    except Exception:
        return None


def _write_fatal(argv, exc):
    rp = _report_hint(argv)
    if rp is None:
        return
    try:
        rp.parent.mkdir(parents=True, exist_ok=True)
        result = {
            'format': FORMAT,
            'check': 'FAIL',
            'fatal': True,
            'fatal_stage': _STAGE,
            'fatal_error': f'{type(exc).__name__}:{exc}',
            'traceback_tail': traceback.format_exc().splitlines()[-16:],
            'project_root_bootstrapped': str(ROOT) in sys.path,
            'client_modified': False,
        }
        rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f"PT_RARE_CROSS_OBJECT_EXTRACT=FATAL stage={_STAGE} error={type(exc).__name__}:{exc}")
    except Exception:
        pass


def _objects_in_mode_indices():
    rows = []
    for o in getattr(bpy.context, 'objects_in_mode', []) or []:
        if o.type == 'MESH' and str(o.get('pt_rare_role', '')) == 'RARE':
            try:
                rows.append(int(o.get('pt_source_object_index', -1)))
            except Exception:
                pass
    return sorted(rows)


def main(argv):
    global _STAGE
    _STAGE = 'PARSE_ARGS'
    a = _parse(argv)
    _STAGE = 'IMPORT_BASE_HELPER'
    from pt_asset_tool.blender import extract_rare_rigid_edit as base

    _STAGE = 'READ_BASELINE'
    baseline = json.loads(pathlib.Path(a.baseline).read_text(encoding='utf-8'))
    errors = []
    changed = []
    diagnostics = []
    mode_objects_before = _objects_in_mode_indices()

    _STAGE = 'CANONICALIZE_MULTI_OBJECT_EDIT_TO_OBJECT'
    mode_before, mode_after, mode_changed = base.force_object_mode()
    mode_objects_after = _objects_in_mode_indices()

    _STAGE = 'COMPARE_OBJECT_SET_AND_SEMANTICS'
    bmap = {int(r['object_index']): r for r in baseline.get('rows') or []}
    rares = [o for o in bpy.data.objects if o.type == 'MESH' and str(o.get('pt_rare_role', '')) == 'RARE']
    omap = {int(o.get('pt_source_object_index', -1)): o for o in rares}
    if set(omap) != set(bmap):
        errors.append('RARE_OBJECT_SET_CHANGED')
    volatile = []
    max_uv = 0.0
    max_weight = 0.0
    for oi, br in sorted(bmap.items()):
        o = omap.get(oi)
        if o is None:
            continue
        if len(o.data.vertices) != int(br['vertex_count']):
            errors.append(f'VERTEX_COUNT_{oi}')
            continue
        current_transform = base.transform_state(o)
        if current_transform != br.get('transform_state'):
            errors.append(f'OBJECT_TRANSFORM_CHANGED_{oi}')
            diagnostics.append({'object_index': oi, 'kind': 'OBJECT_TRANSFORM'})
        current_fp = base.mesh_state_fingerprint(o)
        baseline_fp = br.get('mesh_state_fingerprint') or br.get('fingerprint')
        cur_sem = base.semantic_state(o)
        base_sem = br.get('semantic_state')
        if base_sem is None:
            errors.append(f'BASELINE_SEMANTIC_STATE_MISSING_{oi}')
        else:
            se, sd, uv_delta, w_delta = base.compare_semantic(base_sem, cur_sem, oi)
            errors.extend(se)
            diagnostics.extend(sd)
            max_uv = max(max_uv, uv_delta)
            max_weight = max(max_weight, w_delta)
        if current_fp != baseline_fp:
            volatile.append(oi)
            diagnostics.append({'object_index': oi, 'kind': 'MONOLITHIC_FINGERPRINT_MISMATCH_DIAGNOSTIC_ONLY'})
        before = br['positions_fixed']
        for vi, v in enumerate(o.data.vertices):
            after = base.f3(v.co)
            if after != before[vi]:
                changed.append({
                    'object_index': oi,
                    'object_name': o.name,
                    'vertex_index': vi,
                    'before_world_fixed': before[vi],
                    'after_world_fixed': after,
                })

    _STAGE = 'APPLY_CANDIDATE_SCOPE_GUARDS'
    changed_objects = sorted({int(r['object_index']) for r in changed})
    if not changed:
        errors.append('NO_VERTEX_POSITION_CHANGE')
    if len(changed) > int(a.max_changed):
        errors.append(f'TOO_MANY_VERTEX_POSITION_CHANGES_{len(changed)}')
    if not (int(a.min_objects) <= len(changed_objects) <= int(a.max_objects)):
        errors.append(f'CROSS_OBJECT_COUNT_OUTSIDE_CANDIDATE_SCOPE_{len(changed_objects)}')

    semantic_prefixes = (
        'OBJECT_NAME_', 'VERTEX_COUNT_', 'EDGE_COUNT_', 'POLYGON_COUNT_', 'LOOP_COUNT_',
        'EDGES_', 'POLYGONS_', 'MATERIAL_SLOTS_', 'VERTEX_GROUPS_', 'UV_STATE_CHANGED_',
        'PHYSIQUE_WEIGHT_STATE_CHANGED_', 'BASELINE_SEMANTIC_STATE_MISSING_'
    )
    semantic_errors = [x for x in errors if any(x.startswith(p) for p in semantic_prefixes)]
    result = {
        'format': FORMAT,
        'check': 'PASS' if not errors else 'FAIL',
        'errors': errors,
        'changed_vertex_count': len(changed),
        'changed_vertices': changed,
        'changed_object_indices': changed_objects,
        'transaction_cross_object': len(changed_objects) >= 2,
        'max_changed_authorized_candidate': int(a.max_changed),
        'min_objects': int(a.min_objects),
        'max_objects': int(a.max_objects),
        'diagnostics': diagnostics,
        'guard_scope': 'SAVED_BLENDER_CROSS_OBJECT_CANDIDATE_ONLY',
        'writer_input_mode_before': mode_before,
        'writer_input_mode_after': mode_after,
        'writer_input_object_mode_canonicalized': mode_changed,
        'objects_in_mode_before': mode_objects_before,
        'objects_in_mode_after': mode_objects_after,
        'project_root_bootstrapped': str(ROOT) in sys.path,
        'non_position_semantic_state_pass': len(semantic_errors) == 0,
        'volatile_fingerprint_mismatch_objects': volatile,
        'max_uv_state_delta': max_uv,
        'max_physique_weight_delta': max_weight,
        'selection_state_ignored': True,
        'client_modified': False,
    }
    _STAGE = 'WRITE_REPORT'
    rp = pathlib.Path(a.report).resolve()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(
        f"PT_RARE_CROSS_OBJECT_EXTRACT={result['check']} changed_vertices={len(changed)} "
        f"changed_objects={len(changed_objects)} max_changed={int(a.max_changed)} "
        f"mode_before={mode_before} semantic_state={str(result['non_position_semantic_state_pass']).lower()} "
        f"bootstrap={str(result['project_root_bootstrapped']).lower()}"
    )
    if errors:
        raise RuntimeError(','.join(errors))


if __name__ == '__main__':
    av = sys.argv
    av = av[av.index('--') + 1:] if '--' in av else []
    try:
        main(av)
    except Exception as exc:
        _write_fatal(av, exc)
        raise
