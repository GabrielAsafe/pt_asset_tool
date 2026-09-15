from __future__ import annotations

from types import SimpleNamespace

from pt_asset_tool.model062_corpus import audit_model062_physical_corpus


def _asset(asset_id, path, family, category, *, objects=1, vertices=3, faces=1, mats=1, texlinks=1):
    return SimpleNamespace(
        asset_id=asset_id, primary_path=path, family=family, category=category,
        object_count=objects, total_vertices=vertices, total_faces=faces,
        material_count=mats, source_record={'total_texlinks':texlinks},
    )


def test_model062_physical_corpus_checks_mode_and_counts_by_family_domain(tmp_path, monkeypatch):
    rigid=_asset('R','char/test/r.smd','SMD_MODEL_062_RIGID_PHYSIQUE','CHARACTER')
    static=_asset('S','Items/s.smd','SMD_MODEL_062_STATIC','WEAPON_ITEM')
    mixed=_asset('M','Effect/m.smd','SMD_MODEL_062_MIXED_PHYSIQUE','EFFECT',objects=2,vertices=6,faces=2,texlinks=2)
    registry=SimpleNamespace(assets=[rigid,static,mixed])
    physical={}
    for a in registry.assets:
        p=tmp_path/(a.asset_id+'.smd'); p.write_bytes(a.asset_id.encode()); physical[a.primary_path]=p
    resolver=SimpleNamespace(resolve=lambda logical,required=True:physical[logical])
    def obj(name, phys):
        return {'name':name,'phys':phys,'nv':3,'nf':1,'nt':1,'nr':0,'np':0,'ns':0}
    parsed={
        b'R':{'mat_count':1,'objects':{'r':obj('r',True)}},
        b'S':{'mat_count':1,'objects':{'s':obj('s',False)}},
        b'M':{'mat_count':1,'objects':{'mr':obj('mr',True),'ms':obj('ms',False)}},
    }
    monkeypatch.setattr('pt_asset_tool.model062_corpus.parse_model062_bytes',lambda data:parsed[data])
    result=audit_model062_physical_corpus(registry,resolver)
    assert result['status']=='PASS'
    assert result['asset_count']==3
    assert result['physical_mixed_count']==1
    assert result['pass_domains_by_family']['SMD_MODEL_062_RIGID_PHYSIQUE']==['PLAYER']
    assert result['pass_domains_by_family']['SMD_MODEL_062_STATIC']==['WEAPON_ITEM']
    assert result['pass_domains_by_family']['SMD_MODEL_062_MIXED_PHYSIQUE']==['EFFECT']


def test_model062_physical_corpus_fails_family_when_inventory_mode_disagrees(tmp_path, monkeypatch):
    static=_asset('S','Items/s.smd','SMD_MODEL_062_STATIC','WEAPON_ITEM')
    registry=SimpleNamespace(assets=[static])
    p=tmp_path/'s.smd'; p.write_bytes(b'S')
    resolver=SimpleNamespace(resolve=lambda *a,**k:p)
    monkeypatch.setattr(
        'pt_asset_tool.model062_corpus.parse_model062_bytes',
        lambda data:{'mat_count':1,'objects':{'s':{'name':'s','phys':True,'nv':3,'nf':1,'nt':1,'nr':0,'np':0,'ns':0}}},
    )
    result=audit_model062_physical_corpus(registry,resolver)
    assert result['status']=='FAIL'
    assert result['failure_count']==1
    assert result['pass_domains_by_family']['SMD_MODEL_062_STATIC']==[]
    assert result['by_family_domain']['SMD_MODEL_062_STATIC']['WEAPON_ITEM']['status']=='FAIL'
