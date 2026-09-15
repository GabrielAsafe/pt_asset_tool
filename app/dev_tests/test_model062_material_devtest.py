from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.model062_material_devtest import choose_model062_material_representatives


def _asset(i, domain_path, family='SMD_MODEL_062_STATIC', materials=1):
    return SimpleNamespace(
        asset_id=f'A{i}', primary_path=domain_path, family=family, kind='SMD_MODEL_062',
        material_count=materials, object_count=i+1, size=100+i, category='CHARACTER',
    )


def test_material_representatives_cover_only_model062_with_materials():
    reg=SimpleNamespace(assets=[
        _asset(1,'char/npc/A/A.smd',materials=2),
        _asset(2,'char/npc/B/B.smd',materials=1),
        _asset(3,'char/npc/C/C.smd',family='STAGE_072_MAP_SEPARATE',materials=5),
        _asset(4,'char/npc/D/D.smd',materials=0),
    ])
    rows=choose_model062_material_representatives(reg,'NPC',limit=4)
    assert {x['asset'] for x in rows} == {'char/npc/A/A.smd','char/npc/B/B.smd'}


def test_model062_material_corpus_requires_all_physical_assets(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pt_asset_tool.model062_material_devtest import audit_model062_material_physical_corpus
    a=SimpleNamespace(asset_id='a',primary_path='char/a.smd',family='SMD_MODEL_062_STATIC',category='CHARACTER',material_count=2)
    reg=SimpleNamespace(assets=[a])
    p=tmp_path/'a.smd'; p.write_bytes(b'x')
    class R:
        def resolve(self,*args,**kwargs): return p
    monkeypatch.setattr('pt_asset_tool.model062_material_devtest.locate_materials',lambda data:{'material_count':2,'materials':[{'in_use':True},{'in_use':False}]})
    r=audit_model062_material_physical_corpus(reg,R())
    assert r['status']=='PASS'
    assert r['pass_domains']==['PLAYER']
    assert r['by_domain']['PLAYER']['MATERIAL_COUNT']==2


def test_model062_material_corpus_fails_on_inventory_layout_drift(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pt_asset_tool.model062_material_devtest import audit_model062_material_physical_corpus
    a=SimpleNamespace(asset_id='a',primary_path='effect/a.smd',family='SMD_MODEL_062_STATIC',category='EFFECT',material_count=2)
    reg=SimpleNamespace(assets=[a])
    p=tmp_path/'a.smd'; p.write_bytes(b'x')
    class R:
        def resolve(self,*args,**kwargs): return p
    monkeypatch.setattr('pt_asset_tool.model062_material_devtest.locate_materials',lambda data:{'material_count':1,'materials':[{'in_use':True}]})
    r=audit_model062_material_physical_corpus(reg,R())
    assert r['status']=='FAIL'
    assert r['by_domain']['EFFECT']['FAIL_COUNT']==1


def test_material_representatives_cover_every_present_model062_family_before_complexity_fill():
    reg=SimpleNamespace(assets=[
        _asset(1,'char/npc/R1/R1.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE',materials=8),
        _asset(2,'char/npc/R2/R2.smd',family='SMD_MODEL_062_RIGID_PHYSIQUE',materials=7),
        _asset(3,'char/npc/S1/S1.smd',family='SMD_MODEL_062_STATIC',materials=1),
    ])
    rows=choose_model062_material_representatives(reg,'NPC',limit=2)
    assert len(rows)==2
    assert {x['family'] for x in rows} == {'SMD_MODEL_062_RIGID_PHYSIQUE','SMD_MODEL_062_STATIC'}
