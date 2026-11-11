"""V10: collision isolation and matched-height Catalog panels."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pt_asset_tool import smd_preview_batch as batch
from pt_asset_tool.resolver import ClientResolver


def _fixture(tmp_path: Path, monkeypatch, *, exact_texture: bool = False):
    project = tmp_path / 'app'; project.mkdir()
    client = tmp_path / 'client'; client.mkdir()
    paths = [
        'char/a.smd', 'char/b.smd',
        'char/npcXms/Bonbori/bonbori.tga',
        'char/npcxms/Bonbori/bonbori.tga',
    ]
    for rel in paths:
        target = client / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'fixed-fixture')
    inv = project / 'inventory.json'
    inv.write_text(json.dumps({'canonical_client_root': str(client), 'records': [{'relative_path': x} for x in paths]}))
    pairing = project / 'pairing.csv'; pairing.write_text('dummy\n')
    monkeypatch.setattr(batch.Settings, 'discover', lambda *a, **k: SimpleNamespace(client_root=client, inventory=inv, pairing=pairing))
    monkeypatch.setattr(batch, 'blender_runtime_info', lambda *a, **k: {'ready': True, 'source':'FIXTURE', 'version':'FIXTURE', 'command':['noop']})
    texture = 'char/npcXms/Bonbori/bonbori.tga' if exact_texture else 'Char/NpcXms/Bonbori/bonbori.tga'
    assets = [
        SimpleNamespace(family='SMD_MODEL_062_STATIC', primary_path='char/a.smd', textures=[texture], visual_mode=''),
        SimpleNamespace(family='SMD_MODEL_062_STATIC', primary_path='char/b.smd', textures=[], visual_mode=''),
    ]
    class Registry:
        def __init__(self, *a, **k): self.assets = assets
        def resolve(self, rel): return next(x for x in assets if x.primary_path == rel)
    class Manager:
        def __init__(self, *a, **k): self.rendered = []
        def classify(self, plan): return {'status': 'MISSING', 'asset': plan['logical']}
        def render_now(self, plan, retry=True, force=False, cancel_event=None):
            self.rendered.append(plan['logical'])
            return {'status': 'READY', 'asset': plan['logical']}
    monkeypatch.setattr(batch, 'AssetRegistry', Registry)
    monkeypatch.setattr(batch, 'SmdPreviewManager', Manager)
    return project, client, paths


def test_real_case_collision_does_not_abort_other_previews(tmp_path, monkeypatch, capsys):
    project, client, paths = _fixture(tmp_path, monkeypatch)
    before = {x: (client / x).read_bytes() for x in paths}
    result = batch.run_batch(project, client, mode='warmup', workers=2)
    assert result['status'] == 'COMPLETE_WITH_BLOCKED'
    assert result['counts_final']['BLOCKED'] == 1
    assert result['counts_final']['READY'] == 1
    assert result['selected_for_render'] == 1
    assert result['items']['char/a.smd']['status'] == 'BLOCKED'
    assert 'CASE_COLLISION_AMBIGUOUS' in result['items']['char/a.smd']['detail']
    assert 'char/npcXms/Bonbori/bonbori.tga' in result['items']['char/a.smd']['detail']
    assert 'char/npcxms/Bonbori/bonbori.tga' in result['items']['char/a.smd']['detail']
    assert result['items']['char/b.smd']['status'] == 'READY'
    assert result['blocked_examples'][0]['asset'] == 'char/a.smd'
    assert 'SMD_PREVIEW_BATCH=PARTIAL_BLOCKED' in capsys.readouterr().out
    persisted = batch.read_batch_state(project)
    assert persisted['status'] == 'COMPLETE_WITH_BLOCKED'
    assert persisted['items']['char/a.smd']['status'] == 'BLOCKED'
    assert all((client / x).read_bytes() == content for x, content in before.items())


def test_exact_case_texture_is_safe_even_if_lowercase_collides(tmp_path, monkeypatch):
    project, client, _ = _fixture(tmp_path, monkeypatch, exact_texture=True)
    resolver = ClientResolver(client)
    resolver.prime_from_inventory(project / 'inventory.json')
    assert resolver.resolve('char/npcXms/Bonbori/bonbori.tga', required=False) == client / 'char/npcXms/Bonbori/bonbori.tga'
    result = batch.run_batch(project, client)
    assert result['status'] == 'COMPLETE'
    assert result['counts_final']['READY'] == 2
    assert not result['blocked_examples']


def test_uncategorized_programming_error_remains_visible(tmp_path, monkeypatch):
    project, client, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(batch, 'build_smd_preview_plan', lambda *a: (_ for _ in ()).throw(RuntimeError('CODE_FAULT')))
    with pytest.raises(RuntimeError, match='CODE_FAULT'):
        batch.run_batch(project, client)


def test_catalog_uses_one_shared_height_and_internal_scrollers():
    root = Path(__file__).parents[1] / 'pt_asset_tool' / 'ui_static'
    css = (root / 'app.css').read_text()
    js = (root / 'app.js').read_text()
    assert '#tab-catalog .catalog-panel > .table-wrap' in css
    assert '#tab-catalog .catalog-panel > .gallery' in css
    assert 'grid-template-rows:auto auto minmax(0,1fr) auto' in css
    assert '--catalog-viewport-height' in css
    assert 'scrollbar-gutter:stable' in css
    assert 'resizeCatalogPanels' in js
    assert "window.addEventListener('resize'" in js
    assert 'CASE COLLISION ${blocked}' in js
    assert 'blocked_examples' in js
