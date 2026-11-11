"""Explicit source-hash-locked Stage0.72 preview review rules.

This does not represent a general SMD writer rule.  In the current Etervale
C# client, PristonSmdReader stores TexturePointer32, but BuildStageGroups and
PristonStageLinks.Resolve build geometry/UVs by TexLink indices; they do not
consume TexturePointer32.  The exact dark_boss.smd corpus SHA is the only
source entitled to the narrowly scoped preview parser exception below.
"""
from __future__ import annotations

DARK_BOSS_SOURCE_SHA256 = 'fff8acbe1cb39f70f376e380a21cfed760557c5af4ee73b2ad2ed26ebc39d706'
RULE_ID = 'DARK_BOSS_EXACT_SHA_NULL_HANDLE_ZERO_UV_PREVIEW_REVIEW'


def is_proven_null_zero_uv_preview(*, source_sha256: str, material_id: int,
                                    texture_count: int, animation_count: int,
                                    chain_length: int, stage_index: int,
                                    htexture: int, u: tuple[float, ...],
                                    v: tuple[float, ...]) -> bool:
    return (source_sha256 == DARK_BOSS_SOURCE_SHA256
            and material_id == 0 and texture_count == 1
            and animation_count == 0 and chain_length == 1
            and stage_index == 0 and htexture == 0
            and len(u) == len(v) == 3
            and all(x == 0.0 for x in (*u, *v)))
