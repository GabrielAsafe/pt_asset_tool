from __future__ import annotations

import json
import pathlib
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from pt_asset_tool.ui_app import UIContext, UIHandler


def get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def test_entity_endpoint_groups_live_client(tmp_path: pathlib.Path):
    project = tmp_path / 'project'
    client = tmp_path / 'client'
    (project / 'pt_asset_tool').mkdir(parents=True)
    (project / 'data/reference/entity_catalog').mkdir(parents=True)
    (project / 'data/reference/entity_catalog/monster_npc_entities_v1.json').write_text(json.dumps({
        'format':'PT_ENTITY_CATALOG_SEED_V1','status':'PASS','entity_count':1,'monster_count':0,'npc_count':1,
        'entities':[{'entity_key':'NPC|char/npc/ahin','display_name':'Ahin','file_count':4}],
    }))
    (project / 'pt_asset.py').write_text('#!/usr/bin/env python3\nimport sys\nprint("9.9-test")\n')
    for rel, data in [
        ('char/npc/Ahin/Ahin.smd', b'SMD'),
        ('char/npc/Ahin/Ahin.inx', b'INX'),
        ('char/npc/Ahin/Ahin.smb', b'SMB'),
        ('char/npc/Ahin/Ahin.png', b'not-real-png'),
    ]:
        p = client / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    ctx = UIContext(project, client)
    server = ThreadingHTTPServer(('127.0.0.1', 0), UIHandler); server.ctx = ctx; ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        status, report = get(f'http://127.0.0.1:{server.server_address[1]}/api/entities?group=NPC')
        assert status == 200 and report['status'] == 'PASS'
        assert report['live_entity_count'] == 1
        assert report['items'][0]['display_name'] == 'Ahin'
        assert report['items'][0]['known_canonical_entity'] is True
        assert report['items'][0]['role_counts']['MODEL'] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
