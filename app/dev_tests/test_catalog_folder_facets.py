from __future__ import annotations

import pathlib

from pt_asset_tool.ui_catalog import CatalogIndex, UIStateStore, extension_description, infer_semantics


def test_entity_roles_are_granular():
    assert infer_semantics('char/npc/Ahin/Ahin.smd', '.smd') == ('NPC', 'MODEL')
    assert infer_semantics('char/npc/Ahin/Ahin.inx', '.inx') == ('NPC', 'CONFIG')
    assert infer_semantics('char/npc/Ahin/Ahin.smb', '.smb') == ('NPC', 'ANIMATION')
    assert infer_semantics('char/npc/Ahin/Ahin-body.tga', '.tga') == ('NPC', 'TEXTURE')
    assert infer_semantics('char/monster/Acero/Acero.smd', '.smd') == ('MONSTER', 'MODEL')


def test_extension_descriptions_are_human_readable():
    assert 'Modelo' in extension_description('.smd')
    assert 'anima' in extension_description('.smb').lower()
    assert 'binding' in extension_description('.inx').lower()
    assert extension_description('') == 'Arquivo sem extensão'


def test_folder_filter_uses_entity_directory(tmp_path: pathlib.Path):
    client = tmp_path / 'client'
    for rel in [
        'char/npc/Ahin/Ahin.smd',
        'char/npc/Ahin/Ahin.inx',
        'char/npc/Marina/Marina.smd',
        'char/monster/Acero/Acero.smd',
    ]:
        p = client / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'x')
    state = UIStateStore(tmp_path / 'state.json')
    cat = CatalogIndex(client, state)
    cat.rebuild()

    q = cat.query(category='NPC')
    folders = {x['label']: x for x in q['facets']['folders']}
    assert folders['Ahin']['value'] == 'char/npc/Ahin'
    assert folders['Ahin']['count'] == 2
    assert folders['Marina']['count'] == 1
    roles = {x['value']: x['count'] for x in q['facets']['roles']}
    assert roles['MODEL'] == 2
    assert roles['CONFIG'] == 1

    ahin = cat.query(category='NPC', folder='char/npc/Ahin')
    assert ahin['total'] == 2
    assert {x['role'] for x in ahin['items']} == {'MODEL', 'CONFIG'}
    assert all(x['folder'] == 'Ahin' for x in ahin['items'])


def test_ui_folder_facets_keep_useful_second_level():
    from pt_asset_tool.ui_catalog import infer_folder_bucket
    assert infer_folder_bucket('image/Sinimage/Inter/Chat/ChatDefault-1.tga', 'UI') == ('Inter/Chat', 'image/Sinimage/Inter/Chat')
    assert infer_folder_bucket('image/Sinimage/Items/Defense/itDB150.bmp', 'UI') == ('Items/Defense', 'image/Sinimage/Items/Defense')
    assert infer_folder_bucket('StartImage/Opening/M_Login.TGA', 'UI') == ('Opening', 'StartImage/Opening')
