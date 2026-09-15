from pathlib import Path
from pt_asset_tool.server_item_census import audit_server_item_bundles


def _w(root:Path,rel:str,data:bytes):
    p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)


def test_item_census_extracts_code_and_zhoon(tmp_path):
    project=tmp_path/'app'; project.mkdir(); server=tmp_path/'server'; server.mkdir()
    _w(server,'GameServer/OpenItem/A.txt',b'*CODE "SP149"\n*link "name\\A.zhoon"\n')
    _w(server,'name/A.zhoon',b'*J_NAME "A"')
    r=audit_server_item_bundles(project,server)
    assert r['item_definition_count']==1
    assert r['identity_parsed_count']==1
    assert r['rows'][0]['code']=='SP149'
    assert r['rows'][0]['zhoon'][0]['exists_server'] is True


def test_item_census_marks_duplicate_codes_review(tmp_path):
    project=tmp_path/'app'; project.mkdir(); server=tmp_path/'server'; server.mkdir()
    _w(server,'GameServer/OpenItem/A.txt',b'CODE XX01\n')
    _w(server,'GameServer/OpenItem/B.txt',b'CODE XX01\n')
    r=audit_server_item_bundles(project,server)
    assert r['duplicate_code_count']==1
    assert r['review_count']==2
    assert all('DUPLICATE_CODE' in x['reasons'] for x in r['rows'])


def test_item_census_uses_filename_code_without_inferring_visual(tmp_path):
    project=tmp_path/'app'; project.mkdir(); server=tmp_path/'server'; server.mkdir()
    _w(server,'gameserver/openitem/2_WA108.txt',b'*link "name\\WA108.zhoon"\n')
    _w(server,'gameserver/openitem/name/WA108.zhoon',b'*J_NAME "Item"')
    r=audit_server_item_bundles(project,server)
    assert r['item_definition_count']==1
    assert r['identity_parsed_count']==1
    row=r['rows'][0]
    assert row['code']=='WA108'
    assert row['identity_basis']=='OPENITEM_FILENAME_CODE_V6'
    assert row['zhoon'][0]['exists_server'] is True
    assert r['scope']['filename_code_is_not_visual_mapping'] is True
