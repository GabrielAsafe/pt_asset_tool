from pathlib import Path
import json, struct
from pt_asset_tool.semantic_census import classify_semantic, physical_probe, _variant_key, _state_hint

def test_ui_classification_priority():
    x=classify_semantic('Image/Sinimage/Inter/Chat/ChatTap_01.bmp','.bmp')
    assert x.semantic_group=='UI' and x.semantic_role=='UI_CHAT' and x.confidence=='HIGH'

def test_item_icon_defense():
    x=classify_semantic('Image/Sinimage/Items/Defense/itDB150.bmp','.bmp')
    assert x.semantic_role=='UI_ITEM_ICON_DEFENSE'

def test_login_loading_and_chrselect():
    assert classify_semantic('StartImage/login/Loading/Loading1.bmp','.bmp').semantic_role=='UI_LOADING'
    y=classify_semantic('game/maps/chrselect/ship_floor.bmp','.bmp')
    assert y.semantic_group=='FRONTEND_SCENE' and y.semantic_role=='CHARACTER_SELECT_SCENE'

def test_monster_npc_and_char_are_not_overclaimed():
    assert classify_semantic('Monster/Goblin/a.smd','.smd').semantic_group=='MONSTER'
    assert classify_semantic('NPC/Town/shop.smd','.smd').semantic_group=='NPC'
    x=classify_semantic('char/tmABCD/foo.smd','.smd')
    assert x.semantic_role=='CHARACTER_ASSET_CANDIDATE' and x.confidence=='MEDIUM'

def test_registry_character_hint_is_candidate_not_runtime_proof():
    x=classify_semantic('weird/x.smd','.smd',{'category':'CHARACTER','family':'SMD_MODEL_062_RIGID_PHYSIQUE'})
    assert x.semantic_role=='CHARACTER_MODEL_CANDIDATE' and x.confidence=='MEDIUM'

def test_standard_bmp_probe(tmp_path: Path):
    p=tmp_path/'a.bmp'; b=bytearray(54+12); b[:2]=b'BM'; struct.pack_into('<I',b,14,40); struct.pack_into('<i',b,18,2); struct.pack_into('<i',b,22,2); struct.pack_into('<H',b,26,1); struct.pack_into('<H',b,28,24); p.write_bytes(b)
    r=physical_probe(p,'Image/Sinimage/a.bmp'); assert r['physical_family']=='BMP_STANDARD' and r['width']==2 and r['height']==2

def test_model_and_stage_headers(tmp_path: Path):
    p=tmp_path/'m.smd'; p.write_bytes(b'SMD Model data Ver 0.62\0'+b'X'*40); assert physical_probe(p,'char/m.smd')['physical_family']=='SMD_MODEL_062'
    q=tmp_path/'s.smd'; q.write_bytes(b'SMD Stage data Ver 0.72'+b'X'*40); assert physical_probe(q,'game/maps/s.smd')['physical_family']=='SMD_STAGE_072'

def test_variant_helpers_are_advisory():
    assert _variant_key('ChatTap_01.bmp')=='chattap'
    assert _state_hint('button-1.bmp')=='VARIANT_1'
    assert _variant_key('itDB150.bmp')=='itdb150'

def test_run_census_end_to_end_read_only(tmp_path: Path):
    import hashlib, shutil
    import pt_asset_tool.semantic_census as sc
    root=tmp_path/'root'; root.mkdir()
    (root/'pt_asset_tool').mkdir()
    src=Path(sc.__file__).parent
    for rel in sc.CERTIFIED_WRITERS:
        shutil.copy2(src/Path(rel).name, root/rel)
    client=tmp_path/'client'; (client/'Image/Sinimage/Inter/Chat').mkdir(parents=True)
    b=bytearray(54+12); b[:2]=b'BM'; struct.pack_into('<I',b,14,40); struct.pack_into('<i',b,18,2); struct.pack_into('<i',b,22,2); struct.pack_into('<H',b,26,1); struct.pack_into('<H',b,28,24)
    (client/'Image/Sinimage/Inter/Chat/ChatTap_01.bmp').write_bytes(b)
    (client/'char').mkdir(); (client/'char/model.smd').write_bytes(b'SMD Model data Ver 0.62\0'+b'X'*40)
    def tree_sha():
        h=hashlib.sha256()
        for p in sorted(client.rglob('*')):
            if p.is_file(): h.update(p.relative_to(client).as_posix().encode()); h.update(p.read_bytes())
        return h.hexdigest()
    before=tree_sha(); out=root/'pt_build/census.json'; report=sc.run_census(root,out,client); after=tree_sha()
    assert before==after
    assert report['client_read_only'] is True and report['file_count']==2
    assert report['ui']['file_count']==1
    assert out.is_file() and out.with_suffix('.csv').is_file() and out.with_suffix('.md').is_file()
    assert out.with_name('census_ui_catalog.json').is_file() and out.with_name('census_ui_catalog.csv').is_file()
