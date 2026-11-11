"""Bounded source/preview polygon budgets. Preview only; no source asset writes."""
from __future__ import annotations

MAX_SOURCE_VERTICES = 2_500_000
MAX_SOURCE_FACES = 3_500_000
TARGET_PREVIEW_VERTICES = 300_000
TARGET_PREVIEW_FACES = 260_000


def lod_plan(source_vertices: int, source_faces: int) -> dict:
    if source_vertices < 1 or source_faces < 1:
        raise ValueError('MODELO_SEM_GEOMETRIA')
    if source_vertices > MAX_SOURCE_VERTICES or source_faces > MAX_SOURCE_FACES:
        raise ValueError('MODELO_PESADO_DEMAIS_ATE_PARA_LOD_PRIVADO')
    ratio = min(1., TARGET_PREVIEW_VERTICES / source_vertices,
                TARGET_PREVIEW_FACES / source_faces)
    return {'ratio': round(ratio, 7), 'simplify': ratio < .999,
            'source_vertices':source_vertices, 'source_faces':source_faces,
            'target_preview_vertices':TARGET_PREVIEW_VERTICES,
            'target_preview_faces':TARGET_PREVIEW_FACES}
