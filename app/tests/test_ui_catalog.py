from __future__ import annotations

from pathlib import Path

from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore, infer_semantics


def test_semantic_ui_and_item_character_hints():
    assert infer_semantics('image/interface/panel.png', '.png') == ('UI', 'PANEL')
    assert infer_semantics('image/MapBox.tga', '.tga') == ('UI', 'UI_TEXTURE')
    assert infer_semantics('image/party/icon.png', '.png') == ('UI', 'PARTY_UI')
    assert infer_semantics('image/Sinimage/Items/Defense/itDA247.bmp', '.bmp') == ('UI', 'ITEM_ICON_DEFENSE')
    assert infer_semantics('char/tmABCD/TfbF01.smd', '.smd') == ('CHARACTER', 'BODY')
    assert infer_semantics('char/tmABCD/TfhF01.smd', '.smd') == ('CHARACTER', 'HEAD')
    assert infer_semantics('char/tmABCD/m2.smb', '.smb') == ('CHARACTER', 'SKELETON_MOTION')
    assert infer_semantics('image/NPC/Shop/shop01.smd', '.smd') == ('NPC', 'MODEL')


def test_catalog_annotation_never_touches_client(tmp_path: Path):
    client = tmp_path/'client'; build = tmp_path/'build'; client.mkdir(); build.mkdir()
    p = client/'char/tmABCD/TfbF01.smd'; p.parent.mkdir(parents=True); p.write_bytes(b'ORIGINAL')
    before = p.read_bytes()
    state = UIStateStore(build/'ui_state.json')
    idx = CatalogIndex(client, state); idx.rebuild()
    row = idx.apply_state_update('char/tmABCD/TfbF01.smd', {'favorite': True, 'tags': 'donor, candidate', 'notes': 'test'})
    assert row and row['favorite'] is True and row['tags'] == ['candidate', 'donor']
    assert p.read_bytes() == before
    assert (build/'ui_state.json').is_file()


def test_query_facets_and_search(tmp_path: Path):
    client = tmp_path/'client'; client.mkdir()
    files = ['image/interface/a.png','image/Sinimage/Items/Weapon/w.bmp','char/tmABCD/TfhF01.smd']
    for rel in files:
        p=client/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'x')
    state=UIStateStore(tmp_path/'state.json'); idx=CatalogIndex(client,state); idx.rebuild()
    r=idx.query(category='UI')
    assert r['total']==2 and {x['path'] for x in r['items']}=={'image/interface/a.png','image/Sinimage/Items/Weapon/w.bmp'}
    r=idx.query(q='TfhF01')
    assert r['total']==1 and r['items'][0]['role']=='HEAD'


def test_smd_header_routes_stage072_vs_model062(tmp_path: Path):
    client=tmp_path/'client'; client.mkdir()
    s72=client/'field/map072.smd'; s72.parent.mkdir(parents=True); s72.write_bytes(b'SMD Model data Ver 0.72\x00more')
    s62=client/'char/tmABCD/body.smd'; s62.parent.mkdir(parents=True); s62.write_bytes(b'SMD Model data Ver 0.62\x00more')
    idx=CatalogIndex(client,UIStateStore(tmp_path/'state.json')); idx.rebuild()
    a=idx.get_asset('field/map072.smd'); b=idx.get_asset('char/tmABCD/body.smd')
    assert a['physical_hint']=='SMD_MODEL_072' and 'view_stage072' in a['capabilities'] and 'write_rare' not in a['capabilities']
    assert b['physical_hint']=='SMD_MODEL_062' and b['capabilities']==['inspect']


def test_nonexistent_annotation_is_not_persisted(tmp_path: Path):
    client=tmp_path/'client'; client.mkdir(); state_path=tmp_path/'state.json'
    idx=CatalogIndex(client,UIStateStore(state_path)); idx.rebuild()
    assert idx.apply_state_update('../ghost.smd', {'favorite':True}) is None
    assert not state_path.exists()
