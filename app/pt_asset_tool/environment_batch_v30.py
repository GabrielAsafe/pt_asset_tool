"""V30: explicit, reversible *experimental* full-vegetation preview.

The V29 mode remains conservative. V30 can include foliage-only fragments as
separate provisional instances; this is deliberately NOT semantic approval.
There is no game writer, no SMD mutation and no implicit V25 decisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

FORMAT = 'PT_ETERVALE_ENVIRONMENT_BATCH_V30'
MAX_INSTANCES = 100


def plan_complete_preview(groups, *, source_face_count: int, source_sha256: str,
                          asset: str, lod: str = 'LOD0') -> dict:
    if lod != 'LOD0':
        raise ValueError('V30_REQUER_LOD0_ALTO')
    if type(source_face_count) is not int or source_face_count <= 0:
        raise ValueError('V30_FACE_COUNT_INVALIDO')
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64 or
            any(char not in '0123456789abcdef' for char in source_sha256)):
        raise ValueError('V30_SOURCE_SHA_INVALIDO')
    if not isinstance(asset, str) or not asset.endswith('.smd'):
        raise ValueError('V30_ASSET_INVALIDO')
    if not isinstance(groups, list) or len(groups) > 250:
        raise ValueError('V30_GRUPOS_INVALIDOS')

    used_ids = set()
    face_ids = set()
    foliage = 0
    stems = 0
    excluded = 0
    trees = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('V30_GRUPO_INVALIDO')
        ident = group.get('id')
        if not isinstance(ident, str) or not ident or ident in used_ids:
            raise ValueError('V30_ID_DUPLICADO_OU_INVALIDO')
        used_ids.add(ident)
        if group.get('category') != 'ARVORE' or group.get('review_status') == 'REJECTED':
            excluded += 1
            continue
        if group.get('accepted_for_runtime') is True:
            raise ValueError('V30_NAO_CERTIFICA_PUBLICACAO')
        parts = group.get('faces')
        leaves = group.get('foliage_faces')
        trunk = group.get('trunk_faces')
        if not isinstance(parts, list) or not parts or not isinstance(leaves, list) or not isinstance(trunk, list):
            raise ValueError('V30_FACES_INVALIDAS')
        for segment in (parts, leaves, trunk):
            if any(type(i) is not int or i < 0 or i >= source_face_count for i in segment):
                raise ValueError('V30_FACE_FORA_DA_MALHA')
            if len(segment) != len(set(segment)):
                raise ValueError('V30_FACE_DUPLICADA')
        ids = set(parts)
        if ids != set(leaves) | set(trunk) or set(leaves) & set(trunk):
            raise ValueError('V30_PARTICAO_FACES_INVALIDA')
        if ids & face_ids:
            raise ValueError('V30_FACE_DUPLICADA_ENTRE_GRUPOS')
        face_ids.update(ids)
        anchor = group.get('anchor_view')
        height = group.get('height_view')
        if (not isinstance(anchor, (tuple, list)) or len(anchor) != 3 or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in anchor) or
            type(height) not in (int, float) or not math.isfinite(height) or
            not .1 <= height <= 200):
            raise ValueError('V30_ANCHOR_OU_ALTURA_INVALIDA')
        kind = 'WITH_TRUNK' if trunk else 'FOLIAGE_ONLY_UNVERIFIED'
        if trunk:
            stems += 1
        else:
            foliage += 1
        trees.append({'id':ident, 'anchor_view':list(anchor), 'height_view':float(height),
                      'placement':kind, 'face_count':len(ids), 'faces':sorted(ids)})
    if not trees:
        raise ValueError('V30_SEM_GRUPOS')
    if len(trees) > MAX_INSTANCES:
        raise ValueError('V30_INSTANCIAS_ACIMA_DO_LIMITE')
    trees.sort(key=lambda t:(0 if t['placement']=='WITH_TRUNK' else 1, t['id']))
    return {'format':FORMAT, 'version':1, 'asset':asset, 'source_sha256':source_sha256,
            'lod':'LOD0', 'trees':trees, 'masked_face_indices':sorted(face_ids),
            'count':len(trees), 'with_trunk':stems, 'foliage_only':foliage,
            'excluded_groups':excluded, 'preview_only':True, 'publish_enabled':False,
            'game_assets_modified':False, 'runtime_certified':False,
            'wall_mounting_certified':False, 'foliage_semantics_certified':False}


def preview_record(plan, *, model_name, model_sha256, mask_originals,
                   cache_manifest, wall_candidates, residual_material_faces):
    if plan.get('format') != FORMAT or plan.get('lod') != 'LOD0' or not plan.get('preview_only'):
        raise ValueError('V30_PLANO_INVALIDO')
    if (cache_manifest.get('source_sha256') != model_sha256 or
            cache_manifest.get('publish_enabled') is not False):
        raise ValueError('V30_CACHE_INCOMPATIVEL')
    if (type(wall_candidates) is not int or not 0 <= wall_candidates <= plan['foliage_only'] or
            type(residual_material_faces) is not int or residual_material_faces < 0):
        raise ValueError('V30_DIAGNOSTICO_INVALIDO')
    return {'format':FORMAT, 'version':1, 'asset':plan['asset'],
            'source_sha256':plan['source_sha256'], 'model_name':model_name,
            'model_sha256':model_sha256, 'lod':'LOD0',
            'source_lod0_faces':cache_manifest['levels']['LOD0']['faces'],
            'instance_count':plan['count'], 'with_trunk':plan['with_trunk'],
            'foliage_only_unverified':plan['foliage_only'],
            'wall_candidates_unverified':wall_candidates,
            'residual_suspect_material_faces':residual_material_faces,
            'masked_face_count':len(plan['masked_face_indices']) if mask_originals else 0,
            'instance_group_ids':[g['id'] for g in plan['trees']],
            'preview_only':True, 'approval_status':'NOT_APPROVED',
            'publish_enabled':False, 'game_assets_modified':False,
            'runtime_certified':False, 'wall_mounting_certified':False,
            'saved_utc':datetime.now(timezone.utc).isoformat()}
