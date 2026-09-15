from pathlib import Path
from types import SimpleNamespace
from pt_asset_tool.server_design_auto import run_server_design_auto


def _w(root:Path,rel:str,data:bytes=b'x'):
    p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)


def test_server_design_auto_builds_read_only_catalog(tmp_path):
    project=tmp_path/'app'; project.mkdir(); client=tmp_path/'client'; client.mkdir(); server=tmp_path/'server'; server.mkdir()
    _w(server,'GameServer/monster/Foo.inf',b'*model "char\\monster\\Foo\\Foo.ini"\n*link "name\\Foo.zhoon"\n')
    _w(server,'GameServer/npc/N.npc',b'*model "char\\npc\\N\\N.ini"\n')
    _w(server,'GameServer/OpenItem/I.txt',b'CODE I001\n')
    _w(server,'GameServer/Field/f.spm',b'*MAX_ACTOR 1')
    _w(server,'GameServer/Field/f.spp',b'\0'*2400)
    _w(server,'GameServer/Field/f.spc',b'\0'*50400)
    _w(server,'name/Foo.zhoon',b'*J_NAME "Foo"')
    _w(server,'char/monster/Foo/Foo.inx',b'inx')
    _w(server,'char/monster/Foo/Foo.smd',b'smd')
    _w(server,'char/monster/Foo/Foo.smb',b'smb')
    _w(server,'char/npc/N/N.inx',b'inx2')
    _w(server,'Field/f/f.smd',b'stage')
    _w(server,'LogItemData/1@2.itm',b'state')
    for d in ('Configs','DataServer','PostBox','FuncBox'):(server/d).mkdir(exist_ok=True)
    settings=SimpleNamespace(project_root=project,client_root=client,server_root=server)
    r=run_server_design_auto(settings)
    assert r['status']=='PASS'
    assert r['server_design_catalog_ready'] is True
    assert r['server_write_authorized'] is False
    assert r['entity_bundles']['definition_count']==2
    assert r['field_bundles']['field_bundle_count']==1
    assert r['item_bundles']['item_definition_count']==1
