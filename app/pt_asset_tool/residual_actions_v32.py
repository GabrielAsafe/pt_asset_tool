"""V32: semantic decisions for residual Stage vegetation (view-only)."""
from __future__ import annotations
import copy
import math

MAX_EXTRA_TREES = 12


def placement_from_bounds(points, *, seed, face_count, model, model_sha, scale):
    """Create an immutable view-space placement proposal; not ground-certified."""
    if type(seed) is not int or not 0 <= seed < face_count:
        raise ValueError('V32_SEMENTE_INVALIDA')
    if not isinstance(model, str) or not model.endswith('.blend.zip') or '/' in model or '\\' in model:
        raise ValueError('V32_MODELO_INVALIDO')
    if not isinstance(model_sha, str) or len(model_sha) != 64 or any(c not in '0123456789abcdef' for c in model_sha):
        raise ValueError('V32_SHA_MODELO_INVALIDO')
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or not .1 <= scale <= 10.:
        raise ValueError('V32_ESCALA_INVALIDA')
    pts = [tuple(x) for x in points]
    if not pts or any(len(x) != 3 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in x) for x in pts):
        raise ValueError('V32_POSICAO_INVALIDA')
    low = [min(x[k] for x in pts) for k in range(3)]
    high = [max(x[k] for x in pts) for k in range(3)]
    return {'seed':seed, 'model':model, 'model_sha256':model_sha,
            'lod':'LOD0', 'scale':float(scale),
            'anchor_view':[(low[0]+high[0])/2, (low[1]+high[1])/2, low[2]],
            'height_view':max(.4, high[2]-low[2]),
            'review_only':True, 'ground_certified':False}


def validate_replacements(doc, *, face_count):
    """Backward compatible: earlier V31 JSON files have no replacements key."""
    records = doc.get('v32_replacements', [])
    if not isinstance(records, list) or len(records) > MAX_EXTRA_TREES:
        raise ValueError('V32_INSTANCIAS_INVALIDAS')
    seen=set()
    for rec in records:
        if not isinstance(rec, dict) or not rec.get('review_only') is True or rec.get('ground_certified') is not False or rec.get('lod') != 'LOD0':
            raise ValueError('V32_REGISTO_INVALIDO')
        check=placement_from_bounds([rec.get('anchor_view')], seed=rec.get('seed'),
                  face_count=face_count, model=rec.get('model'),
                  model_sha=rec.get('model_sha256'), scale=rec.get('scale'))
        if rec.get('seed') in seen:
            raise ValueError('V32_SEMENTE_DUPLICADA')
        seen.add(rec['seed'])
        if rec['seed'] not in doc.get('extra_faces', []):
            raise ValueError('V32_SEMENTE_SEM_MASCARA')
        h=rec.get('height_view')
        if not isinstance(h,(int,float)) or isinstance(h,bool) or not math.isfinite(h) or not .4 <= h <= 1e4:
            raise ValueError('V32_ALTURA_INVALIDA')
    return records


def with_replacement(doc, replacement, *, face_count):
    existing=validate_replacements(doc,face_count=face_count)
    if len(existing) >= MAX_EXTRA_TREES:
        raise ValueError('V32_MAXIMO_12_ARVORES_EXTRA')
    if any(rec['seed'] == replacement['seed'] for rec in existing):
        raise ValueError('V32_ARVORE_JA_GUARDADA')
    out=copy.deepcopy(doc)
    out['v32_replacements']=existing+[copy.deepcopy(replacement)]
    validate_replacements(out,face_count=face_count)
    return out


def undo_last(doc, *, face_count):
    """Undo ONLY last V32 decision, never erase older V31 legacy selections."""
    validate_replacements(doc, face_count=face_count)
    selections=doc.get('selections', [])
    if not selections or selections[-1].get('v32_action') not in ('REPLACE_TREE', 'HIDE_LEAVES'):
        raise ValueError('V32_SEM_ACAO_RECENTE_PARA_DESFAZER')
    last=selections[-1]
    faces=last.get('v32_faces')
    if (not isinstance(faces,list) or not faces or len(set(faces))!=len(faces) or
        any(type(i) is not int or not 0 <= i < face_count for i in faces) or
        not set(faces).issubset(doc['extra_faces'])):
        raise ValueError('V32_ULTIMA_SELECAO_INVALIDA')
    out=copy.deepcopy(doc)
    out['extra_faces']=sorted(set(out['extra_faces'])-set(faces))
    out['selections'].pop()
    if last['v32_action']=='REPLACE_TREE':
        matches=[v for v in out.get('v32_replacements', []) if v['seed']==last['seed']]
        if len(matches)!=1:
            raise ValueError('V32_INSTANCIA_HISTORICA_INCONSISTENTE')
        out['v32_replacements']=[v for v in out['v32_replacements'] if v['seed'] != last['seed']]
    validate_replacements(out,face_count=face_count)
    return out,faces,last['v32_action'],last['seed']
