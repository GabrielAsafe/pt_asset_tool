from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pt_asset_tool.ui_app as ui_app
from pt_asset_tool.entity_catalog import build_live_entities, query_built_entities
from pt_asset_tool.ui_app import UIContext


class FakeRegistry:
    def __init__(self, assets):
        self.assets = assets
        self.pairing = []
        self._by_path = {str(a.primary_path).casefold(): a for a in assets}

    def resolve(self, path):
        key = str(path).casefold()
        if key not in self._by_path:
            raise KeyError(path)
        return self._by_path[key]

    def physical_dependency_status(self, asset):
        return {
            'status': 'PASS',
            'rigid_binding_ready_physical': False,
            'animation_binding_ready_physical': False,
        }


def fake_asset(path: str, category: str, textures=(), configs=()):
    return SimpleNamespace(
        asset_id=path,
        primary_path=path,
        category=category,
        family='TEST',
        kind='TEST',
        binding_mode='NONE',
        binding_source=None,
        rigid_binding_ready=False,
        animation_binding_ready=False,
        binding_skeleton_smb=None,
        motions=[],
        textures=list(textures),
        configs=list(configs),
    )


def row(path: str, category: str, role: str, preview=False):
    p = Path(path)
    return {
        'path': path,
        'name': p.name,
        'ext': p.suffix.lower(),
        'size': 100,
        'category': category,
        'role': role,
        'folder': p.parent.name,
        'folder_path': p.parent.as_posix(),
        'physical_family': 'TEXTURE' if preview else 'MODEL',
        'previewable': preview,
    }


def test_entity_snapshot_is_cached_per_catalog_revision(tmp_path: Path, monkeypatch):
    project = tmp_path / 'project'
    client = tmp_path / 'client'
    (project / 'pt_asset_tool').mkdir(parents=True)
    client.mkdir()
    p = client / 'image/interface/a.png'
    p.parent.mkdir(parents=True)
    p.write_bytes(b'x')
    (project / 'pt_asset.py').write_text('#!/usr/bin/env python3\n')

    calls = {'n': 0}
    original = ui_app.build_live_entities

    def counted(*args, **kwargs):
        calls['n'] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ui_app, 'build_live_entities', counted)
    ctx = UIContext(project, client)
    try:
        first = ctx.entities_snapshot(None)
        second = ctx.entities_snapshot(None)
        assert first is second
        assert calls['n'] == 1

        ctx.catalog.rebuild()
        third = ctx.entities_snapshot(None)
        assert third is not second
        assert calls['n'] == 2
    finally:
        pass


def test_entity_list_payload_is_thin_even_when_detail_has_many_paths():
    entity = {
        'entity_key': 'ITEM|model:itda102',
        'semantic_group': 'ITEM',
        'display_name': 'itda102',
        'folder_root': 'image/Sinimage/Items/DropItem',
        'identity_evidence': 'ITEM_MODEL_CODE',
        'asset_count': 500,
        'all_paths': [f'x/{i}.bmp' for i in range(500)],
        'relationships': [{'type': 'X'}] * 100,
        'registry_assets': [{'path': 'x.smd'}],
        'role_counts': {'MODEL': 1, 'TEXTURE': 499},
        'extension_counts': {'.bmp': 499, '.smd': 1},
        'runtime_status': 'UNPROVEN',
        'writer_status': 'UNAUTHORIZED',
    }
    report = query_built_entities([entity], {}, group='ITEM', q='x/499', limit=10)
    assert len(report['items']) == 1
    summary = report['items'][0]
    assert 'all_paths' not in summary
    assert 'relationships' not in summary
    assert 'registry_assets' not in summary
    assert summary['asset_count'] == 500


def test_item_visual_bundle_groups_distinct_runtime_items_but_preserves_identity():
    texture = 'image/Sinimage/Items/DropItem/drda103.tga'
    rows = [
        row('image/Sinimage/Items/DropItem/itda102.smd', 'ITEM', 'DROP_MODEL'),
        row('image/Sinimage/Items/DropItem/itda301.smd', 'ITEM', 'DROP_MODEL'),
        row(texture, 'ITEM', 'DROP_TEXTURE', preview=True),
        row('char/tmABCD/a002.ini', 'CHARACTER', 'CONFIG'),
        row('char/tmABCD/body.smd', 'CHARACTER', 'BODY'),
    ]
    registry = FakeRegistry([
        fake_asset('image/Sinimage/Items/DropItem/itda102.smd', 'ITEM', [texture]),
        fake_asset('image/Sinimage/Items/DropItem/itda301.smd', 'ITEM', [texture]),
        fake_asset('char/tmABCD/body.smd', 'CHARACTER', [texture], [{'inx': 'char/tmABCD/a002.inx'}]),
    ])

    entities = build_live_entities(rows, {}, registry=registry)
    da102 = next(e for e in entities if e.get('entity_key') == 'ITEM|model:itda102')
    da301 = next(e for e in entities if e.get('entity_key') == 'ITEM|model:itda301')

    assert da102['entity_key'] != da301['entity_key']  # runtime/entity identity is not collapsed
    assert da102['visual_bundle_key'] == da301['visual_bundle_key']
    assert da102['visual_bundle_evidence'] == 'EXACT_FULL_TEXTURE_DEPENDENCY_SET'
    assert da102['visual_bundle_member_count'] == 2
    paths = {x.casefold() for x in da102['visual_bundle_paths']}
    assert 'image/sinimage/items/dropitem/drda103.tga' in paths
    assert 'image/sinimage/items/dropitem/itda102.smd' in paths
    assert 'image/sinimage/items/dropitem/itda301.smd' in paths
    # Equipped appearance joins only because its registry texture signature is identical.
    assert 'char/tmabcd/body.smd' in paths
    assert 'char/tmabcd/a002.ini' in paths


def test_frontend_cancels_stale_catalog_entity_requests_and_click_does_not_reload_catalog():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'pt_asset_tool/ui_static/app.js').read_text(encoding='utf-8')
    assert 'catalogAbort' in js and 'entityAbort' in js and 'entityFacetAbort' in js
    assert 'new AbortController()' in js
    select_start = js.index('async function selectAsset(path)')
    select_end = js.index('function relatedAssetsHtml', select_start)
    select_code = js[select_start:select_end]
    assert 'loadCatalog()' not in select_code
    entities_start = js.index('async function loadEntities()')
    entities_end = js.index('function serverMetric', entities_start)
    entities_code = js[entities_start:entities_end]
    assert 'await selectEntity(S.entity)' not in entities_code
