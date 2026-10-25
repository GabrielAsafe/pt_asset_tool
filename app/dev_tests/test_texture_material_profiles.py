"""Regression tests for the opt-in safe 1x texture material routing."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pt_asset_tool import texture_material_pipeline as pipeline
from pt_asset_tool import texture_material_profiles as profiles


def make(root: Path, rel: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (12, 8), (123, 45, 67)).save(p)
    return p


def test_safety_default_and_path_classifier():
    for name in ('new_mask01.BMP', 'sky_c.BMP', 'line_light03.BMP', 'button.BMP',
                 'wood_normal.BMP', 'Image/UI/wall02.BMP', 'char/effect/stone01.BMP'):
        result = profiles.decide(name, role='diffuse_candidate')
        assert result['action'] == 'skip', (name, result)
    assert profiles.decide('Image/Field/wall02.bmp', role='diffuse_candidate')['material'] == 'stone'
    assert profiles.decide('ground02.TGA', role='diffuse_candidate')['material'] == 'terrain'
    assert profiles.decide('Image/Field/plank03.BMP', role='diffuse_candidate')['material'] == 'wood'
    assert profiles.decide('Npcb07.BMP', role='diffuse_candidate', context='client/char/npc/Barba')['material'] == 'skin'
    assert profiles.decide('cs_ground_line.BMP', role='diffuse_candidate', context='client/cSelect')['action'] == 'skip'
    assert profiles.decide('abc.BMP', role='diffuse_candidate')['action'] == 'skip'
    assert profiles.decide('stone_normal.png', role='normal_candidate')['action'] == 'skip'


def test_field_false_positives_are_excluded_even_with_override():
    # A real Summit inventory previously classified these as terrain diffuse.
    wall = profiles.decide('Field/AncientW/b_wall.bmp', role='diffuse_candidate')
    assert wall['material'] == 'stone' and wall['action'] == 'ai'
    for rel in (
        'Field/Fall_Game/floor_002lightingmap.bmp',
        'Field/Tower/ground_lightmap.dds',
        'Field/Dungeon/wall_01_normalmap.bmp',
        'Field/Fall_Game/ground_illuminationmap.tga',
        'Field/Slab/floor_ambientocclusion.bmp',
    ):
        decision = profiles.decide(rel, role='diffuse_candidate')
        assert decision['action'] == 'skip', (rel, decision)
        bypass = profiles.decide(rel, role='diffuse_candidate', config={
            'rules': [{'pattern': '*', 'material': 'terrain', 'action': 'ai'}]})
        assert bypass['action'] == 'skip', (rel, bypass)

    for rel in ('Field/Slab/a2_grass_01.bmp', 'Field/Slab/a2_grass_02.bmp'):
        decision = profiles.decide(rel, role='diffuse_candidate')
        assert (decision['material'], decision['action']) == ('foliage', 'skip')



def test_real_field_effect_path_and_ambiguous_sand_suffix_stay_out_of_ai(tmp_path):
    # False positives observed in the Summit client after the previous patch.
    # Four levels ensure the synthetic pytest directory name cannot bias context.
    root = tmp_path / 'assets' / 'packs' / 'client' / 'textures'
    cases = (
        'image/Sinimage/AssaEffect/GreatH/P/ground_ring.bmp',
        'image/Sinimage/AssaParticle/GreatH/P/ground01.bmp',
        'Field/dungeon/sand_m.bmp',
    )
    for rel in cases:
        result = profiles.decide(rel, role='diffuse_candidate')
        assert result['action'] == 'skip', (rel, result)
        overridden = profiles.decide(rel, role='diffuse_candidate', config={
            'rules': [{'pattern': '*', 'material': 'terrain', 'action': 'ai'}]})
        assert overridden['action'] == 'skip', (rel, overridden)
        make(root, rel)
    for rel in ('Field/AncientW/b_wall.bmp', 'Field/forest/dirt.bmp'):
        result = profiles.decide(rel, role='diffuse_candidate')
        assert result['action'] == 'ai', (rel, result)
        make(root, rel)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*.bmp')}
    report = profiles.scan(root, include=[], exact=[], all_=True,
                           config=profiles.load_profile_config(None))
    assert report['action_counts'] == {'ai': 2, 'skip': 3}, report
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*.bmp')} == before


def test_scan_blocks_technical_and_grass_for_ai(tmp_path):
    root = tmp_path / 'field'
    paths = ('Field/AncientW/b_wall.bmp', 'Field/Fall_Game/floor_002lightingmap.bmp',
             'Field/Slab/a2_grass_01.bmp', 'Field/Dirt/ground12.bmp')
    for rel in paths:
        make(root, rel)
    before = {rel:(root/rel).read_bytes() for rel in paths}
    report = profiles.scan(root, include=[], exact=[], all_=True,
                           config=profiles.load_profile_config(None))
    decisions = {r['source']:r for r in report['decisions']}
    assert report['action_counts'] == {'ai': 2, 'skip': 2}
    assert decisions[paths[1]]['action'] == 'skip'
    assert decisions[paths[2]]['action'] == 'skip'
    assert {rel:(root/rel).read_bytes() for rel in paths} == before


def test_override_opt_in_but_not_technical_or_mask(tmp_path):
    config = {'format': profiles.FORMAT, 'actions': {'terrain': 'light'},
              'rules': [{'pattern': '*ground*.bmp', 'action': 'ai', 'material': 'terrain'},
                        {'pattern': '*mystery*.bmp', 'material': 'stone'}]}
    path = tmp_path/'profiles.json'; path.write_text(json.dumps(config))
    loaded = profiles.load_profile_config(path)
    assert profiles.decide('ground01.bmp', role='diffuse_candidate', config=loaded)['action'] == 'ai'
    assert profiles.decide('mystery.bmp', role='diffuse_candidate', config=loaded)['action'] == 'ai'
    assert profiles.decide('new_mask_ground01.bmp', role='diffuse_candidate', config=loaded)['action'] == 'skip'
    assert profiles.decide('ground_normal.bmp', role='normal_candidate', config=loaded)['action'] == 'skip'
    for broken in ({'format': profiles.FORMAT, 'actions': {'terrain': 'erase'}},
                   {'format': profiles.FORMAT, 'rules': [{'action': 'ai'}]},
                   {'format': 'OTHER'}):
        path.write_text(json.dumps(broken))
        with pytest.raises(ValueError):
            profiles.load_profile_config(path)


def test_scan_nondestructive_and_excludes_cselect(tmp_path):
    root=tmp_path/'assets'/'cSelect'
    make(root,'cs_ground_line.BMP')
    make(root,'new_mask02.BMP')
    before={p.name:p.read_bytes() for p in root.iterdir()}
    report=profiles.scan(root,include=[],exact=[],all_=True,config=profiles.load_profile_config(None))
    assert report['action_counts']=={'skip':2}
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
    assert list(root.iterdir()) and not (root/'overlay').exists()


def test_scan_distinguishes_ground_npc_and_technical(tmp_path):
    root=tmp_path/'field'
    for path in ('wall09.BMP','ground07.BMP','metal02.BMP','mystery.BMP','ground_normal.BMP'):
        make(root,path)
    report=profiles.scan(root,include=[],exact=[],all_=True,config=profiles.load_profile_config(None))
    assert report['action_counts']=={'ai':3,'skip':2},report
    assert report['client_publish_authorized'] is False


def test_profile_run_stages_only_safe_ai_without_upscale_or_source_mutation(tmp_path,monkeypatch):
    model=tmp_path/'weights.pth'; model.write_bytes(b'fake-model')
    config=tmp_path/'models.json'
    config.write_text(json.dumps({'models': {'default': {
        'engine':'external', 'model':str(model), 'sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
        'argv':['mock-model','{input}','{output}']}}}))
    source=tmp_path/'field'
    paths=[make(source,n) for n in ('wall01.BMP','ground02.BMP','new_mask03.BMP','sky_c.BMP','mystery.BMP')]
    original={p.name:p.read_bytes() for p in paths}

    def fake_run(cmd,**kwargs):
        with Image.open(cmd[1]) as im:
            im.save(cmd[2])
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(pipeline.subprocess,'run',fake_run)
    report=pipeline.prepare(source,tmp_path/'out',include=[],exact=[],all_=True,
                            config_path=config,profile=profiles.PROFILE,denoise='off',maps='off')
    assert report['status_counts']=={'staged':2,'skipped_profile':3},report['status_counts']
    assert report['upscale_performed'] is False
    assert report['model_ai_enabled'] is True
    assert report['readiness']['ai_1x_executed']
    for rec in report['records']:
        assert rec['input_unchanged']
        if rec['status']=='staged':
            assert rec['ai']['scale']==1 and rec['restoration']=='ai_dxt_1x'
            assert not rec.get('maps')
        else:
            assert rec.get('output') is None
    assert {p.name:p.read_bytes() for p in paths}==original
    assert pipeline.audit(tmp_path/'out'/'manifest.json')['client_publish_authorized'] is False
