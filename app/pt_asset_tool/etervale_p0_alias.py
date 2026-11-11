"""Scope-specific, fail-closed aliases grounded in WorldImport KeyMaps.cs.

A logical key resolves to the exact original spelling already present. Ambiguous
multiple keys still require an explicit occurrence (zero-based). We never
invent English aliases in formats whose importer only accepts Korean tokens.
"""
from __future__ import annotations

# Source: Etervale tools/PristonTale.WorldImport/KeyMaps.cs
FIELD = {
    '*ACTOR': ('*출연자', '*ACTOR'),
    '*BOSS_ACTOR': ('*출연자두목', '*BOSS_ACTOR'),
    '*MAX_ACTOR_POS': ('*최대동시출현수', '*MAX_ACTOR_POS'),
    '*DELAY': ('*출현간격', '*DELAY'),
    '*MAX_ACTOR': ('*출현수', '*MAX_ACTOR'),
}
GROUPS = {
    'Field': FIELD,
    'Monster': {'*LEVEL': ('*레벨',), '*EXP': ('*경험치',), '*GOLD': ('*골드',), '*DEFENCE': ('*방어력',)},
    'OpenItem': {'*LEVEL': ('*레벨',), '*PRICE': ('*가격',), '*WEIGHT': ('*무게',)},
    'NPC': {},
}


def logical_candidates(area: str, key: str) -> tuple[str, ...]:
    name = str(key).upper()
    groups = GROUPS.get(area, {})
    if name in groups:
        return groups[name]
    for tokens in groups.values():
        if any(name == token.upper() for token in tokens):
            return tokens
    return (key,)


def resolve(lines: list[str], area: str, key: str, occurrence: int | None, *, append: bool = False):
    from .etervale_native_pipeline import _leading
    options=logical_candidates(area,key)
    matches=[i for i,line in enumerate(lines) if _leading(line).casefold() in {v.casefold() for v in options}]
    if occurrence is not None:
        if isinstance(occurrence,bool) or not isinstance(occurrence,int) or occurrence < 0 or occurrence >= len(matches):
            raise ValueError('NATIVE_OCCURRENCE_INVALID')
        matches=[matches[occurrence]]
    if append:
        if len(matches)>1 and occurrence is None:
            raise ValueError(f'NATIVE_ALIAS_AMBIGUOUS_APPEND:{key}:{len(matches)}')
        if matches:
            return _leading(lines[matches[0]]), matches
        # Field ASCII aliases are accepted by the importer. In every other
        # domain the alias is merely an authoring convenience, not a token.
        if area != 'Field' and key.upper() in GROUPS.get(area, {}):
            raise ValueError('NATIVE_ALIAS_NEEDS_EXISTING_CANONICAL_KEY')
        return key,matches
    if len(matches)!=1:
        raise ValueError(f'NATIVE_OPERATION_REQUIRES_EXACT_MATCH:{key}:{len(matches)}')
    return _leading(lines[matches[0]]),matches
