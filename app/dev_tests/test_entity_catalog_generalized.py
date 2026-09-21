from __future__ import annotations

from types import SimpleNamespace

from pt_asset_tool.entity_catalog import entity_detail, query_entities


def _row(path, category, role, *, preview=False, folder='', folder_path=''):
    import pathlib
    p = pathlib.PurePosixPath(path)
    return {
        'path': path, 'category': category, 'role': role, 'ext': p.suffix.lower(),
        'size': 1, 'previewable': preview,
        'folder': folder or p.parent.name, 'folder_path': folder_path or p.parent.as_posix(),
    }


class CharacterAndItemRegistry:
    pairing = []

    def __init__(self):
        self.assets = [
            SimpleNamespace(
                asset_id='ATALANTA-BODY', primary_path='char/tmABCD/AtBody01.smd', category='CHARACTER',
                family='SMD_MODEL_062_RIGID_PHYSIQUE', kind='SMD_MODEL_062',
                binding_mode='ROOT_SKELETON_BOUND', binding_source='VERIFIED_INX_LINKFILE',
                rigid_binding_ready=True, animation_binding_ready=True,
                binding_skeleton_smb='char/tmABCD/m2.smb', motions=['char/tmABCD/m2.smb'],
                textures=['image/Character/Atalanta/body01.tga'],
                configs=[{'inx':'char/tmABCD/mb01.inx','motion_inx':'char/tmABCD/cmb01.inx','motion_smb':'char/tmABCD/m2.smb'}],
            ),
            SimpleNamespace(
                asset_id='ITEM-ITDA247', primary_path='image/Sinimage/Items/DropItem/itDA247.smd', category='ITEM',
                family='SMD_MODEL_062_STATIC', kind='SMD_MODEL_062',
                binding_mode='SELF_CONTAINED', binding_source='MODEL_LOCAL',
                rigid_binding_ready=False, animation_binding_ready=False, binding_skeleton_smb='', motions=[],
                textures=['image/Sinimage/Items/DropItem/itDA247.tga'], configs=[],
            ),
        ]

    def physical_dependency_status(self, asset):
        return {'status':'PASS', 'rigid_binding_ready_physical':bool(asset.rigid_binding_ready),
                'animation_binding_ready_physical':bool(asset.animation_binding_ready), 'missing':[]}


def test_character_entity_collects_verified_model_texture_config_audio_and_icon():
    rows = [
        _row('char/tmABCD/AtBody01.smd', 'CHARACTER', 'BODY'),
        _row('char/tmABCD/mb01.inx', 'CHARACTER', 'CONFIG'),
        _row('char/tmABCD/cmb01.inx', 'CHARACTER', 'CONFIG'),
        _row('char/tmABCD/m2.smb', 'CHARACTER', 'SKELETON_MOTION'),
        _row('image/Character/Atalanta/body01.tga', 'TEXTURE', 'TEXTURE', preview=True),
        _row('sound/Character/Atalanta/skill.wav', 'AUDIO', 'AUDIO'),
        _row('image/Sinimage/Skill/Atalanta/icon.bmp', 'UI', 'SKILL', preview=True),
        _row('image/Sinimage/Inter/MessageBox/HaBox/ha01.bmp', 'UI', 'MESSAGE_BOX', preview=True),
    ]
    d = entity_detail(rows, {'entity_count':0,'entities':[]}, 'CHARACTER|class:atalanta', registry=CharacterAndItemRegistry())
    assert d
    e = d['entity']
    assert 'char/tmABCD/AtBody01.smd' in e['model_paths']
    assert 'image/Character/Atalanta/body01.tga' in e['texture_paths']
    assert 'sound/Character/Atalanta/skill.wav' in e['audio_paths']
    assert 'image/Sinimage/Skill/Atalanta/icon.bmp' in e['icon_paths']
    assert 'image/Sinimage/Inter/MessageBox/HaBox/ha01.bmp' not in e['all_paths']
    assert any(x['type'] == 'MODEL_USES_TEXTURE' and x['evidence'] == 'SMD_MATERIAL_TEXLINK' for x in e['relationships'])


def test_item_entities_are_model_centric_and_link_texlink_texture():
    rows = [
        _row('image/Sinimage/Items/DropItem/itDA247.smd', 'ITEM', 'DROP_MODEL'),
        _row('image/Sinimage/Items/DropItem/itDA247.tga', 'ITEM', 'DROP_TEXTURE', preview=True),
        _row('image/Sinimage/Items/Defense/itDA247.bmp', 'UI', 'ITEM_ICON_DEFENSE', preview=True),
        _row('image/Sinimage/Items/DropItem/itWA101.smd', 'ITEM', 'DROP_MODEL'),
    ]
    r = query_entities(rows, {'entity_count':0,'entities':[]}, group='ITEM', registry=CharacterAndItemRegistry())
    by = {x['entity_key']: x for x in r['items']}
    assert 'ITEM|model:itda247' in by
    assert 'ITEM|model:itwa101' in by
    assert all(x['display_name'].casefold() != 'dropitem' for x in r['items'])
    assert 'image/Sinimage/Items/DropItem/itDA247.tga' in by['ITEM|model:itda247']['texture_paths']
    assert 'image/Sinimage/Items/Defense/itDA247.bmp' in by['ITEM|model:itda247']['icon_paths']
    assert any(x['type']=='MODEL_USES_TEXTURE' for x in by['ITEM|model:itda247']['relationships'])
    assert any(x['type']=='ITEM_HAS_ICON' for x in by['ITEM|model:itda247']['relationships'])


def test_monster_audio_folder_does_not_create_actor_entity_without_canonical_char_tree():
    rows = [
        _row('wav/Effects/monster/BlizzardGiant/attack.wav', 'MONSTER', 'AUDIO'),
        _row('wav/Effects/monster/BlizzardGiant/death.wav', 'MONSTER', 'AUDIO'),
    ]
    r = query_entities(rows, {'entity_count': 0, 'entities': []}, group='MONSTER', registry=SimpleNamespace(assets=[], pairing=[]))
    assert r['live_entity_count'] == 0
    assert r['items'] == []


def test_monster_canonical_char_folder_still_creates_actor_entity_and_collects_support():
    rows = [
        _row('char/monster/BlizzardGiant/BlizzardGiant.smd', 'MONSTER', 'MODEL'),
        _row('char/monster/BlizzardGiant/BlizzardGiant.tga', 'MONSTER', 'TEXTURE', preview=True),
        _row('wav/Effects/monster/BlizzardGiant/attack.wav', 'MONSTER', 'AUDIO'),
    ]
    r = query_entities(rows, {'entity_count': 0, 'entities': []}, group='MONSTER', registry=SimpleNamespace(assets=[], pairing=[]))
    assert r['live_entity_count'] == 1
    assert r['items'][0]['display_name'] == 'BlizzardGiant'
    assert r['items'][0]['model_paths'] == ['char/monster/BlizzardGiant/BlizzardGiant.smd']
    assert r['items'][0]['audio_paths'] == ['wav/Effects/monster/BlizzardGiant/attack.wav']
    assert any(x['type'] == 'ENTITY_HAS_SUPPORT_ASSET' for x in r['items'][0]['relationships'])
