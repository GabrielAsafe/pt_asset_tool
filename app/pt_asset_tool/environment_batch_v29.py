"""V29: conservative, preview-only batch planning for Stage072 trees.

No bpy dependency, no SMD writer. Groups are face-locked to the original
map; only groups with a plausible trunk are allowed in this first experiment.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math

FORMAT = 'PT_ETERVALE_ENVIRONMENT_BATCH_V29'
MAX_INSTANCES = 100


def plan_tree_instances(groups, *, source_face_count: int, source_sha256: str,
                        asset: str, lod: str = 'LOD0') -> dict:
    """Conservatively select 1 instance per trunk-bearing tree, not leaf scraps."""
    if lod != 'LOD0':
        raise ValueError('V29_REQUER_LOD0_ALTO')
    if not isinstance(source_face_count, int) or source_face_count <= 0:
        raise ValueError('V29_FACE_COUNT_INVALIDO')
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in source_sha256)):
        raise ValueError('V29_SOURCE_SHA_INVALIDO')
    if not isinstance(asset, str) or not asset.endswith('.smd'):
        raise ValueError('V29_ASSET_INVALIDO')
    if not isinstance(groups, list) or len(groups) > 250:
        raise ValueError('V29_GRUPOS_INVALIDOS')
    used_ids = set()
    face_ids = set()
    selections = []
    excluded = 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('V29_GROUP_INVALIDO')
        ident = group.get('id')
        if not isinstance(ident, str) or not ident or ident in used_ids:
            raise ValueError('V29_ID_DUPLICADO_OU_INVALIDO')
        used_ids.add(ident)
        if group.get('category') != 'ARVORE' or not group.get('trunk_faces') or group.get('review_status') == 'REJECTED':
            excluded += 1
            continue
        parts = group.get('faces', [])
        if not isinstance(parts, list) or not parts:
            raise ValueError('V29_ARVORE_SEM_FACES')
        if any(type(x) is not int or x < 0 or x >= source_face_count for x in parts):
            raise ValueError('V29_FACE_FORA_DA_MALHA')
        ids = set(parts)
        if len(ids) != len(parts) or ids & face_ids:
            raise ValueError('V29_FACE_DUPLICADA_ENTRE_ARVORES')
        if not set(group['trunk_faces']).issubset(ids):
            raise ValueError('V29_TRONCO_NAO_CONTIDO_NO_GRUPO')
        face_ids.update(ids)
        anchor = group.get('anchor_view')
        height = group.get('height_view')
        if (not isinstance(anchor, (list, tuple)) or len(anchor) != 3 or
                any(type(x) not in (float, int) or not math.isfinite(x) for x in anchor) or
                type(height) not in (int, float) or not math.isfinite(height) or
                not .1 <= height <= 200):
            raise ValueError('V29_ANCHOR_OU_ALTURA_INVALIDA')
        if group.get('accepted_for_runtime') is True:
            raise ValueError('V29_NAO_CERTIFICA_PUBLICACAO')
        selections.append({'id': ident, 'anchor_view':list(anchor), 'height_view':float(height),
                           'face_count':len(parts), 'faces':sorted(ids)})
    if not selections:
        raise ValueError('V29_SEM_ARVORES_COM_TRONCO')
    if len(selections) > MAX_INSTANCES:
        raise ValueError('V29_INSTANCIAS_ACIMA_DO_LIMITE')
    selections.sort(key=lambda g:g['id'])
    return {'format':FORMAT, 'version':1, 'asset':asset, 'source_sha256':source_sha256,
            'lod':lod, 'trees':selections, 'masked_face_indices':sorted(face_ids),
            'excluded_groups':excluded, 'count':len(selections),
            'preview_only':True, 'publish_enabled':False,
            'game_assets_modified':False, 'runtime_certified':False,
            'ground_certified':False}


def preview_record(plan, *, model_name, model_sha256, mask_originals, cache_manifest):
    """Small audit record. This NEVER implies human approval or game readiness."""
    if plan.get('format') != FORMAT or plan.get('lod') != 'LOD0' or not plan.get('preview_only'):
        raise ValueError('V29_PLANO_NAO_VALIDO')
    if cache_manifest.get('source_sha256') != model_sha256 or cache_manifest.get('publish_enabled') is not False:
        raise ValueError('V29_MODELO_CACHE_INCOMPATIVEL')
    return {'format':FORMAT, 'version':1, 'asset':plan['asset'],
            'source_sha256':plan['source_sha256'], 'model_name':model_name,
            'model_sha256':model_sha256, 'lod':'LOD0',
            'source_lod0_faces':cache_manifest['levels']['LOD0']['faces'],
            'instance_count':plan['count'], 'excluded_groups':plan['excluded_groups'],
            'masked_face_count':len(plan['masked_face_indices']) if mask_originals else 0,
            'instance_group_ids':[g['id'] for g in plan['trees']],
            'preview_only':True, 'approval_status':'NOT_APPROVED',
            'publish_enabled':False, 'game_assets_modified':False,
            'runtime_certified':False, 'ground_certified':False,
            'saved_utc':datetime.now(timezone.utc).isoformat()}
