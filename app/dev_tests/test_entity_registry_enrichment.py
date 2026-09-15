from __future__ import annotations

from types import SimpleNamespace

from pt_asset_tool.entity_catalog import entity_detail, query_entities


def _rows():
    return [
        {'path':'char/npc/Ahin/Ahin.smd','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'MODEL','ext':'.smd','size':10,'previewable':False},
        {'path':'char/npc/Ahin/Ahin.inx','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'CONFIG','ext':'.inx','size':20,'previewable':False},
        {'path':'char/npc/Ahin/Ahin.smb','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'ANIMATION','ext':'.smb','size':30,'previewable':False},
        {'path':'char/npc/Ahin/Ahin.tga','category':'NPC','folder':'Ahin','folder_path':'char/npc/Ahin','role':'TEXTURE','ext':'.tga','size':40,'previewable':True},
    ]


class FakeRegistry:
    def __init__(self):
        self.assets = [SimpleNamespace(
            asset_id='AST-AHIN',
            primary_path='char/npc/Ahin/Ahin.smd',
            family='SMD_MODEL_062_RIGID_PHYSIQUE',
            kind='SMD_MODEL_062',
            binding_mode='ROOT_SKELETON_BOUND',
            binding_source='VERIFIED_INX_LINKFILE',
            rigid_binding_ready=True,
            animation_binding_ready=True,
            binding_skeleton_smb='char/npc/Ahin/Ahin.smb',
            motions=['char/npc/Ahin/Ahin.smb'],
            configs=[{'inx':'char/npc/Ahin/Ahin.inx','motion_smb':'char/npc/Ahin/Ahin.smb'}],
        )]
        self.pairing = []

    def physical_dependency_status(self, asset):
        assert asset.asset_id == 'AST-AHIN'
        return {
            'status':'PASS',
            'rigid_binding_ready_physical':True,
            'animation_binding_ready_physical':True,
            'missing':[],
        }


def test_entity_query_exposes_registry_readiness_without_promoting_runtime():
    report = query_entities(_rows(), {'entity_count':0,'entities':[]}, registry=FakeRegistry())
    entity = report['items'][0]
    assert entity['registry_evidence'] is True
    assert entity['registry_asset_count'] == 1
    assert entity['registry_family_counts'] == {'SMD_MODEL_062_RIGID_PHYSIQUE': 1}
    assert entity['rigid_binding_ready_count'] == 1
    assert entity['animation_binding_ready_count'] == 1
    assert entity['binding_skeleton_paths'] == ['char/npc/Ahin/Ahin.smb']
    assert entity['runtime_status'] == 'UNPROVEN'
    assert entity['writer_status'] == 'UNAUTHORIZED'
    assert 'registry_assets' not in entity


def test_entity_detail_exposes_asset_and_physical_dependency_evidence():
    report = entity_detail(
        _rows(), {'entity_count':0,'entities':[]}, 'NPC|char/npc/ahin', registry=FakeRegistry()
    )
    assert report and report['status'] == 'PASS'
    entity = report['entity']
    assert entity['physical_rigid_binding_ready_count'] == 1
    assert entity['physical_animation_binding_ready_count'] == 1
    assert entity['registry_assets'][0]['asset_id'] == 'AST-AHIN'
    assert entity['registry_assets'][0]['physical_dependency_status']['status'] == 'PASS'
    assert report['policy']['registry_binding_is_runtime_certification'] is False
    assert report['client_modified'] is False


def test_cross_entity_pairing_is_recorded_without_merging_entity_identity():
    reg = FakeRegistry()
    reg.assets = []
    reg.pairing = [{
        'inx': 'char/npc/Bcn05_/Bcn05.inx',
        'model_smd': 'char/npc/Bcn05/Bcn05.smd',
        'motion_smb': 'char/npc/Bcn05/Bcn05.smb',
        'model_resolved': 'True',
        'motion_resolved': 'True',
    }]
    rows = [
        {'path':'char/npc/Bcn05_/Bcn05.inx','category':'NPC','folder':'Bcn05_','folder_path':'char/npc/Bcn05_','role':'CONFIG','ext':'.inx','size':1,'previewable':False},
        {'path':'char/npc/Bcn05/Bcn05.smd','category':'NPC','folder':'Bcn05','folder_path':'char/npc/Bcn05','role':'MODEL','ext':'.smd','size':1,'previewable':False},
    ]
    report = query_entities(rows, {'entity_count':0,'entities':[]}, registry=reg)
    by = {e['display_name']: e for e in report['items']}
    assert by['Bcn05_']['related_entity_keys'] == ['NPC|char/npc/bcn05']
    assert by['Bcn05_']['cross_entity_links'][0]['evidence'] == 'INX_PHYSICAL_PAIRING'
    assert by['Bcn05']['referenced_by_entity_keys'] == ['NPC|char/npc/bcn05_']
    assert by['Bcn05_']['runtime_status'] == 'UNPROVEN'
