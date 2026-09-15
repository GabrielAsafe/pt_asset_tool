from __future__ import annotations

from pt_asset_tool.ui_catalog import infer_semantics


def test_documented_ui_subtrees_get_functional_roles():
    assert infer_semantics('StartImage/Opening/M_Login.TGA', '.tga') == ('UI', 'LOGIN')
    assert infer_semantics('StartImage/Opening/npc/opening_NPC_A.smd', '.smd') == ('UI', 'FRONTEND_NPC')
    assert infer_semantics('image/Sinimage/NPC/npc_face.bmp', '.bmp') == ('UI', 'NPC_DIALOG')
    assert infer_semantics('StartImage/login/Loading/Loading1.bmp', '.bmp') == ('UI', 'LOADING')
    assert infer_semantics('image/Sinimage/Inter/Chat/ChatDefault-1.tga', '.tga') == ('UI', 'CHAT')
    assert infer_semantics('image/Sinimage/Inter/ButtonInfo/InvenInfo.bmp', '.bmp') == ('UI', 'TOOLTIP')
    assert infer_semantics('image/Sinimage/Inter/sinGage/Bar_Exp.bmp', '.bmp') == ('UI', 'GAUGE')
    assert infer_semantics('image/Sinimage/Inter/SkillIcon/Select_Skill.bmp', '.bmp') == ('UI', 'SKILL')
    assert infer_semantics('image/Sinimage/Inter/ReStart/ReStartMain.bmp', '.bmp') == ('UI', 'RESPAWN')


def test_item_icons_are_not_confused_with_world_drop_assets():
    assert infer_semantics('image/Sinimage/Items/Defense/itDB150.bmp', '.bmp') == ('UI', 'ITEM_ICON_DEFENSE')
    assert infer_semantics('image/Sinimage/Items/Weapon/itWA101.bmp', '.bmp') == ('UI', 'ITEM_ICON_WEAPON')
    assert infer_semantics('image/Sinimage/Items/Accessory/item.bmp', '.bmp') == ('UI', 'ITEM_ICON_ACCESSORY')
    assert infer_semantics('image/Sinimage/Items/Premium/item.bmp', '.bmp') == ('UI', 'ITEM_ICON_PREMIUM')
    assert infer_semantics('image/Sinimage/Items/DropItem/drop.smd', '.smd') == ('ITEM', 'DROP_MODEL')
    assert infer_semantics('image/Sinimage/Items/DropItem/drop.tga', '.tga') == ('ITEM', 'DROP_TEXTURE')
    assert infer_semantics('image/Sinimage/Items/DropItem/drop.ase', '.ase') == ('ITEM', 'DROP_SOURCE_3D')


def test_generic_audio_and_physical_family_are_not_lost_to_other():
    from pt_asset_tool.ui_catalog import infer_physical_family

    assert infer_semantics('wav/Button.wav', '.wav') == ('AUDIO', 'AUDIO')
    assert infer_physical_family('wav/Button.wav', '.wav') == 'AUDIO'
    # Functional category remains MONSTER while physical family is AUDIO.
    assert infer_semantics('char/monster/Foo/attack.wav', '.wav')[0] == 'MONSTER'
    assert infer_physical_family('char/monster/Foo/attack.wav', '.wav') == 'AUDIO'
    # Package extension alone is not evidence that the file is an effect.
    assert infer_semantics('image/frame_animation.pkg', '.pkg')[0] != 'EFFECT'
