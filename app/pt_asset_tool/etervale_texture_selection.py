"""Read-only texture picker for Etervale enhancement staging.

The catalogue is the only source of selectable paths; the POST handler rechecks
membership, source containment and the selected family before creating a job.
No live client or database writes occur here.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable

from .texture_upscale import SUPPORTED_SUFFIXES, _risk_class

FAMILIES = ('ui', 'world', 'characters', 'items', 'effects', 'other', 'all')
MAX_SELECTED = 100


def family_for_path(rel: str) -> str:
    """Conservative presentation groups; not a runtime asset-type guarantee."""
    key = '/' + str(rel).replace('\\', '/').lower().strip('/') + '/'
    if _risk_class(rel) == 'UI_ATLAS_RISK' or any(seg in key for seg in ('/ui/', '/sinimage/', '/interface/', '/interfaces/', '/font/', '/fonts/', '/cursor/', '/cursors/', '/login/', '/startimage/', '/clanimage/')):
        return 'ui'
    if any(seg in key for seg in ('/effect/', '/effects/', '/particle/', '/particles/')):
        return 'effects'
    if any(seg in key for seg in ('/char/', '/character/', '/characters/', '/monster/', '/npc/')):
        return 'characters'
    if any(seg in key for seg in ('/item/', '/items/', '/inventory/', '/weapon/', '/armor/')):
        return 'items'
    if any(seg in key for seg in ('/field/', '/terrain/', '/map/', '/maps/', '/stage/')):
        return 'world'
    return 'other'


def catalogue_texture_paths(assets: Iterable[dict]) -> list[str]:
    names = set()
    for asset in assets:
        rel = asset.get('path')
        if not isinstance(rel, str) or not rel or '\\' in rel:
            continue
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts or '.' in p.parts or len(p.parts) == 0:
            continue
        if p.suffix.lower() in SUPPORTED_SUFFIXES:
            names.add(rel)
    return sorted(names, key=lambda s: (s.casefold(), s))


def list_selection(assets: Iterable[dict], *, family: str = 'ui', search: str = '', offset: int = 0, limit: int = 100) -> dict:
    if family not in FAMILIES:
        raise ValueError('TEXTURE_FAMILY_INVALID')
    if not 0 <= offset <= 10000000 or not 1 <= limit <= 100:
        raise ValueError('TEXTURE_PAGE_INVALID')
    search = search.strip().casefold()
    if len(search) > 200:
        raise ValueError('TEXTURE_SEARCH_TOO_LONG')
    rows = catalogue_texture_paths(assets)
    counts = {f: 0 for f in FAMILIES}
    for path in rows:
        counts['all'] += 1
        counts[family_for_path(path)] += 1
    matches = [p for p in rows if (family == 'all' or family_for_path(p) == family) and search in p.casefold()]
    page = matches[offset:offset + limit]
    return {
        'family': family, 'search': search, 'offset': offset, 'limit': limit,
        'total': len(matches), 'counts': counts,
        'rows': [{'path': p, 'family': family_for_path(p), 'ui_atlas_risk': family_for_path(p) == 'ui'} for p in page],
        'maximum_selection': MAX_SELECTED,
    }


def validate_selected_paths(assets: Iterable[dict], client_root: Path, selected: object, *, family: str, include_ui: bool) -> list[str]:
    if family not in FAMILIES:
        raise ValueError('TEXTURE_FAMILY_INVALID')
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SELECTED:
        raise ValueError('TEXTURE_SELECTION_SIZE_INVALID')
    allowed = set(catalogue_texture_paths(assets))
    root = client_root.resolve(strict=True)
    seen = set()
    accepted = []
    for raw in selected:
        if not isinstance(raw, str) or not raw or len(raw) > 1024 or '\\' in raw:
            raise ValueError('TEXTURE_PATH_INVALID')
        rel = PurePosixPath(raw)
        if rel.is_absolute() or '..' in rel.parts or '.' in rel.parts or raw.startswith('/'):
            raise ValueError('TEXTURE_PATH_INVALID')
        if raw not in allowed or raw in seen:
            raise ValueError('TEXTURE_PATH_NOT_IN_CATALOG_OR_DUPLICATE')
        if family != 'all' and family_for_path(raw) != family:
            raise ValueError('TEXTURE_FAMILY_MISMATCH')
        target = (root / Path(*rel.parts)).resolve(strict=True)
        if root not in target.parents or not target.is_file():
            raise ValueError('TEXTURE_PATH_OUTSIDE_CLIENT')
        if family_for_path(raw) == 'ui' and not include_ui:
            raise ValueError('UI_ATLAS_REQUIRES_EXPLICIT_CONSENT')
        seen.add(raw)
        accepted.append(raw)
    return accepted
