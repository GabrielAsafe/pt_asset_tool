from __future__ import annotations

import json
import pathlib
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from pt_asset_tool.ui_app import UIContext, UIHandler


def request(url: str, token: str | None = None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if token: headers['X-PT-UI-Token']=token
    if data is not None: headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=data,headers=headers,method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=5) as r:
        return r.status,json.loads(r.read().decode())


def make(tmp_path: pathlib.Path):
    project=tmp_path/'project'; client=tmp_path/'client'; tool=project/'pt_asset_tool'
    tool.mkdir(parents=True); client.mkdir()
    # Fake backend supports --version and all allowed commands without side effects.
    (project/'pt_asset.py').write_text('''#!/usr/bin/env python3\nimport json,sys\nif sys.argv[1:]==["--version"]: print("9.9-test")\nelse: print(json.dumps({"status":"PASS","argv":sys.argv[1:]}))\n''')
    p=client/'char/tmABCD/at_dragon.smd'; p.parent.mkdir(parents=True); p.write_bytes(b'SMD')
    ctx=UIContext(project,client)
    server=ThreadingHTTPServer(('127.0.0.1',0),UIHandler); server.ctx=ctx; ctx.server=server
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    return project,client,ctx,server,thread,f'http://127.0.0.1:{server.server_address[1]}'


def test_bootstrap_catalog_and_arm_gate(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    try:
        _,b=request(url+'/api/bootstrap'); token=b['token']
        assert b['backend_version']=='9.9-test' and b['catalog']['file_count']==1
        _,c=request(url+'/api/catalog?q=dragon')
        assert c['total']==1
        try:
            request(url+'/api/action',token,{'action':'write_rare','path':'char/tmABCD/at_dragon.smd','options':{}})
        except urllib.error.HTTPError as e:
            assert e.code==409
        _,a=request(url+'/api/safety/arm',token,{'confirm':'ARM BUILD WRITES','seconds':60})
        assert a['write_armed'] is True
        # Arming never bypasses capability enforcement. This minimal fixture
        # has only a catalog file and no semantic/certified rare-model registry
        # evidence, so write_rare must remain rejected.
        try:
            request(url+'/api/action',token,{'action':'write_rare','path':'char/tmABCD/at_dragon.smd','options':{}})
            raise AssertionError('write_rare unexpectedly accepted without semantic capability')
        except urllib.error.HTTPError as e:
            assert e.code==409
        assert client.joinpath('char/tmABCD/at_dragon.smd').read_bytes()==b'SMD'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_invalid_post_token_rejected(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    try:
        try:
            request(url+'/api/reindex','bad-token',{})
        except urllib.error.HTTPError as e:
            assert e.code==403
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_tree_compare_endpoint_passes_filters(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    other=tmp_path/'other'; other.mkdir(); (other/'x.smd').write_bytes(b'x')
    try:
        _,b=request(url+'/api/bootstrap'); token=b['token']
        status,d=request(url+'/api/tree-compare',token,{
            'left':str(client),'right':str(other),'hash':True,'case_sensitive':True,
            'differences_only':True,'extensions':'smd,inx','category':'CHARACTER','path_contains':'tmABCD',
        })
        assert status==202
        cmd=d['job']['command']
        assert '--hash' in cmd and '--case-sensitive' in cmd and '--differences-only' in cmd
        assert cmd[cmd.index('--ext')+1]=='smd,inx'
        assert cmd[cmd.index('--category')+1]=='CHARACTER'
        assert cmd[cmd.index('--path-contains')+1]=='tmABCD'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_report_content_endpoint_is_restricted_to_pt_build(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    try:
        build=project/'pt_build'; build.mkdir(exist_ok=True)
        (build/'cmp.json').write_text(json.dumps({'format':'PT_ASSET_TREE_COMPARE_V2','status':'PASS','rows':[]}))
        status,d=request(url+'/api/report?name=cmp.json')
        assert status==200 and d['report']['status']=='PASS'
        try:
            request(url+'/api/report?name=../secret.json')
        except urllib.error.HTTPError as e:
            assert e.code==400
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_contract_source_config_and_audit_endpoint(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    source=tmp_path/'source'; reference=tmp_path/'reference'; donor=tmp_path/'official'
    source.mkdir(); reference.mkdir(); donor.mkdir()
    try:
        _,b=request(url+'/api/bootstrap'); token=b['token']
        status,c=request(url+'/api/contracts/config',token,{
            'source_root':str(source),
            'reference_source_root':str(reference),
            'donor_clients':[f'OFFICIAL={donor}'],
        })
        assert status==200
        assert c['source_root']==str(source.resolve())
        assert c['reference_source_root']==str(reference.resolve())
        assert c['donor_clients']==[f'OFFICIAL={donor.resolve()}']
        _,summary=request(url+'/api/contracts')
        assert summary['source_root']==str(source.resolve())
        status,d=request(url+'/api/contracts/analyze',token,{'mode':'player_classes'})
        assert status==202
        cmd=d['job']['command']
        assert 'player-class-contracts' in cmd
        assert '--source-root' in cmd and str(source.resolve()) in cmd
        assert '--reference-source-root' in cmd and str(reference.resolve()) in cmd
        assert '--donor-client' in cmd and f'OFFICIAL={donor.resolve()}' in cmd
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_catalog_entity_filter_and_system_visibility_toggle(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    try:
        npc=client/'char/npc/Ahin/Ahin.smd'; npc.parent.mkdir(parents=True,exist_ok=True); npc.write_bytes(b'SMD')
        cfg=client/'char/npc/Ahin/Ahin.inx'; cfg.write_bytes(b'INX')
        log=client/'logs/debug.log'; log.parent.mkdir(parents=True,exist_ok=True); log.write_bytes(b'LOG')
        ctx.catalog.rebuild()
        _,entities=request(url+'/api/entities?group=NPC')
        ahin=next(x for x in entities['items'] if x['display_name']=='Ahin')
        _,filtered=request(url+'/api/catalog?entity='+urllib.parse.quote(ahin['entity_key'],safe=''))
        assert {x['path'] for x in filtered['items']} == {'char/npc/Ahin/Ahin.smd','char/npc/Ahin/Ahin.inx'}
        _,normal=request(url+'/api/catalog?q=debug.log')
        assert normal['total']==0
        _,system=request(url+'/api/catalog?q=debug.log&show_system=1')
        assert system['total']==1 and system['items'][0]['visibility_tier']=='OPERATIONAL'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_client_enrichment_analysis_endpoint_and_report_query(tmp_path: pathlib.Path):
    project,client,ctx,server,thread,url=make(tmp_path)
    try:
        _,b=request(url+'/api/bootstrap'); token=b['token']
        status,d=request(url+'/api/client/analyze',token,{})
        assert status==202
        cmd=d['job']['command']
        assert cmd[-2:]==['audit','client-enrichment']
        status,r=request(url+'/api/client/report')
        assert status==200
        assert r['status']=='NO_REPORT'
        assert r['rows']==[]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
