from __future__ import annotations

from types import SimpleNamespace

from pt_asset_tool import ui_capabilities


class Resolver:
    def resolve(self, logical, required=False):
        return '/tmp/fake.inx' if logical else None


def test_static_asset_has_no_animation_head_or_lod_prompts():
    asset = SimpleNamespace(category='ITEM', family='SMD_MODEL_062_STATIC', animation_binding_ready=False, configs=[])
    ui = ui_capabilities.ui_options_for_asset(asset, Resolver(), model_info_options=[], head_candidates=[], animation_binding_ready_physical=False)
    assert ui['supports_paint'] is True
    assert ui['supports_animation'] is False
    assert ui['available_motions'] == []
    assert ui['supports_lod_selection'] is False
    assert ui['supports_head'] is False


def test_motion_inventory_uses_only_active_physical_clips_and_dedupes_aliases(monkeypatch):
    asset = SimpleNamespace(
        category='CHARACTER', family='SMD_MODEL_062_RIGID_PHYSIQUE', animation_binding_ready=True,
        binding_skeleton_smb='char/tmABCD/m2.smb',
        configs=[{'inx':'char/tmABCD/cmb01.inx','motion_smb':'char/tmABCD/m2.smb'}],
    )
    monkeypatch.setattr(ui_capabilities.inxcore, 'parse_inx', lambda p: {'motions':[
        {'index':0,'state_name':'STAND','motion_frame':3,'start':10,'end':20,'start_ok':True,'end_ok':True},
        {'index':1,'state_name':'IDLE','motion_frame':3,'start':10,'end':20,'start_ok':True,'end_ok':True},
        {'index':2,'state_name':'WALK','motion_frame':0,'start':21,'end':30,'start_ok':True,'end_ok':True},
    ]})
    inv = ui_capabilities.motion_inventory_for_asset(asset, Resolver())
    assert len(inv) == 1
    assert inv[0]['canonical'] == 'STAND'
    assert inv[0]['aliases'] == ['IDLE']
    ui = ui_capabilities.ui_options_for_asset(asset, Resolver(), animation_binding_ready_physical=True)
    assert ui['available_motions'] == ['STAND']
    assert ui['default_motion'] == 'STAND'
