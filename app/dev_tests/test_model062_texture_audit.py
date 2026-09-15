from types import SimpleNamespace

from pt_asset_tool.model062_texture_audit import audit_model062_texture_presence


class Resolver:
    def __init__(self, paths):
        self.paths = dict(paths)
    def resolve(self, logical, required=False):
        if logical not in self.paths:
            raise FileNotFoundError(logical)
        return self.paths[logical]


def _asset(path='char/tmABCD/a.smd', domain_category='CHARACTER'):
    return SimpleNamespace(
        asset_id='A', primary_path=path, kind='SMD_MODEL_062', category=domain_category,
        runtime_path_aliases={}, textures=['tex/a.tga'],
    )


def test_model062_texture_presence_requires_every_face_used_reference(tmp_path, monkeypatch):
    a=_asset()
    reg=SimpleNamespace(assets=[a])
    tex=tmp_path/'a.tga'; tex.write_bytes(b'x')
    monkeypatch.setattr(
        'pt_asset_tool.model062_texture_audit._face_texture_scope',
        lambda **k:{'semantics':'FACE_REFERENCED_MATERIALS','used_material_ids':[0],'required_names':['tex/a.tga'],'error':None},
    )
    r=audit_model062_texture_presence(tmp_path,reg,Resolver({'tex/a.tga':tex}))
    assert r['status']=='PASS'
    assert r['pass_domains']==['PLAYER']
    assert r['required_texture_reference_count']==1
    assert r['client_modified'] is False


def test_model062_texture_presence_fails_closed_without_explicit_alias(tmp_path, monkeypatch):
    a=_asset('char/monster/a.smd','MOB_MONSTER')
    reg=SimpleNamespace(assets=[a])
    monkeypatch.setattr(
        'pt_asset_tool.model062_texture_audit._face_texture_scope',
        lambda **k:{'semantics':'FACE_REFERENCED_MATERIALS','used_material_ids':[0],'required_names':['missing.tga'],'error':None},
    )
    r=audit_model062_texture_presence(tmp_path,reg,Resolver({}))
    assert r['status']=='FAIL'
    assert r['by_domain']['MONSTER']['MISSING_TEXTURE_REFERENCE_COUNT']==1
    assert r['pass_domains']==[]


def test_model062_texture_presence_accepts_only_recorded_runtime_alias(tmp_path, monkeypatch):
    a=_asset('effect/a.smd','EFFECT')
    a.runtime_path_aliases={'old/a.tga':'new/a.tga'}
    reg=SimpleNamespace(assets=[a])
    tex=tmp_path/'a.tga'; tex.write_bytes(b'x')
    monkeypatch.setattr(
        'pt_asset_tool.model062_texture_audit._face_texture_scope',
        lambda **k:{'semantics':'FACE_REFERENCED_MATERIALS','used_material_ids':[1],'required_names':['old/a.tga'],'error':None},
    )
    r=audit_model062_texture_presence(tmp_path,reg,Resolver({'new/a.tga':tex}))
    assert r['status']=='PASS'
    assert r['by_domain']['EFFECT']['RUNTIME_ALIAS_REFERENCE_COUNT']==1
