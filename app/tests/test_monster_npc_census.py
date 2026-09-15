from __future__ import annotations
import json
from pathlib import Path
from pt_asset_tool import monster_npc_census as m


def test_integrated_monster_npc_dependency_census(tmp_path: Path):
    client=tmp_path/'client'; client.mkdir()
    (client/'image/Monster/Wolf').mkdir(parents=True)
    (client/'image/NPC/Shop').mkdir(parents=True)
    (client/'image/Monster/Wolf/wolf01.smd').write_bytes(b'SMD Model data Ver 0.62'+b'\0'*64)
    (client/'image/Monster/Wolf/wolf.smb').write_bytes(b'SMB')
    (client/'image/Monster/Wolf/wolf.bmp').write_bytes(b'BM'+b'\0'*20)
    (client/'image/Monster/Wolf/wolf.inx').write_bytes(b'image\\Monster\\Wolf\\wolf01.smd\0image\\Monster\\Wolf\\wolf.smb\0image\\Monster\\Wolf\\wolf.bmp\0')
    (client/'image/NPC/Shop/shop01.smd').write_bytes(b'SMD Model data Ver 0.62'+b'\0'*64)
    (client/'image/NPC/Shop/shop.inf').write_bytes(b'image/NPC/Shop/shop01.smd\0')
    census=tmp_path/'census.json'
    census.write_text(json.dumps({'rows':[
        {'relative_path':'image/Monster/Wolf/wolf01.smd','group':'MONSTER','role':'MONSTER_ASSET'},
        {'relative_path':'image/Monster/Wolf/wolf.smb','group':'MONSTER','role':'MONSTER_ASSET'},
        {'relative_path':'image/Monster/Wolf/wolf.bmp','group':'MONSTER','role':'MONSTER_ASSET'},
        {'relative_path':'image/Monster/Wolf/wolf.inx','group':'MONSTER','role':'MONSTER_ASSET'},
        {'relative_path':'image/NPC/Shop/shop01.smd','group':'NPC','role':'NPC_ASSET'},
        {'relative_path':'image/NPC/Shop/shop.inf','group':'NPC','role':'NPC_ASSET'},
    ]}))
    before={p.relative_to(client).as_posix():p.read_bytes() for p in client.rglob('*') if p.is_file()}
    r=m.inventory(client,census)
    after={p.relative_to(client).as_posix():p.read_bytes() for p in client.rglob('*') if p.is_file()}
    assert before==after
    assert r['semantic_counts']=={'MONSTER':4,'NPC':2}
    assert r['priority_monster_families'] and r['priority_npc_families']
    assert r['dependency_edge_count']>=4
    assert r['client_read_only'] is True


def test_delta_candidates_are_explicitly_unproven(tmp_path: Path):
    client=tmp_path/'client'; (client/'image/NPC/New').mkdir(parents=True)
    (client/'image/NPC/New/n.smd').write_bytes(b'SMD Model data Ver 0.62')
    census=tmp_path/'census.json'; census.write_text('{"rows":[]}')
    r=m.inventory(client,census)
    a=r['assets'][0]
    assert a['semantic_group']=='NPC'
    assert a['semantic_role']=='UNPROVEN_DELTA_CANDIDATE'
