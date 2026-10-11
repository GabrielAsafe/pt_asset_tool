from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pt_asset_tool.general_asset_census as gac


def _write_plan(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        'canonical_path', 'action', 'category', 'deployability', 'selected_source',
        'selected_path', 'distinct_hash_count', 'variant_count', 'reason',
    ]
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter='\t')
        w.writeheader(); w.writerows(rows)


def test_general_census_separates_reachable_recovery_from_donor_only(monkeypatch, tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    client = tmp_path / 'client'; client.mkdir()
    server = tmp_path / 'server'; server.mkdir()
    donor = tmp_path / 'donor'; donor.mkdir()
    source = tmp_path / 'source'; source.mkdir()
    ref = tmp_path / 'ref'; ref.mkdir()

    inx = donor / 'char/monster/Foo/Foo.inx'
    inx.parent.mkdir(parents=True); inx.write_bytes(b'inx')
    wav = donor / 'wav/unused.wav'
    wav.parent.mkdir(parents=True); wav.write_bytes(b'wav')

    def fake_superset(*args, **kwargs):
        _write_plan(project / 'pt_build/aggregate/client_superset/all/provenance.tsv', [
            {'canonical_path':'char/monster/Foo/Foo.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(inx),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'},
            {'canonical_path':'wav/unused.wav','action':'RECOVER','category':'AUDIO','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(wav),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'},
        ])
        _write_plan(project / 'pt_build/aggregate/server_superset/all/provenance.tsv', [])
        return {'status':'PASS'}

    graph_dir = project / 'pt_build/vendor_graph'
    graph_dir.mkdir(parents=True)
    (graph_dir / 'graph.json').write_text(json.dumps({'nodes':[], 'edges':[]}), encoding='utf-8')

    monkeypatch.setattr(gac, 'build_summit_superset', fake_superset)
    monkeypatch.setattr(gac, 'build_dependency_graph', lambda *a, **k: {'status':'PASS','graph_dir':str(graph_dir)})
    monkeypatch.setattr(gac, 'audit_server_entity_bundles', lambda *a, **k: {'status':'PASS','rows':[{'kind':'MONSTER','definition':'GameServer/Monster/Foo.inf','model_reference':'char/monster/Foo/Foo.ini','zhoon':[]}], 'report':'entities.json'})
    monkeypatch.setattr(gac, 'audit_server_field_bundles', lambda *a, **k: {'status':'PASS','rows':[], 'report':'fields.json'})
    monkeypatch.setattr(gac, 'audit_server_item_bundles', lambda *a, **k: {'status':'PASS','rows':[], 'report':'items.json'})
    monkeypatch.setattr(gac, 'audit_client_manifests', lambda *a, **k: {'status':'PASS'})
    monkeypatch.setattr(gac, 'require_source_trees', lambda *a, **k: (SimpleNamespace(root=source), SimpleNamespace(root=ref)))
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[]})

    result = gac.audit_general_asset_census(
        project, client, server,
        source_root=source, reference_source_root=ref,
        donor_clients=[f'DONOR={donor}'], donor_servers=[],
    )
    assert result['status'] == 'PASS'
    queried = gac.query_general_asset_census(project, limit=50)
    by_path = {r['path'].casefold(): r for r in queried['rows']}
    assert by_path['char/monster/foo/foo.inx']['decision'] == 'RECOVERABLE_REACHABLE_CANDIDATE'
    assert by_path['char/monster/foo/foo.inx']['required_by_reachable_root'] == 'True'
    assert by_path['wav/unused.wav']['decision'] == 'DONOR_GAP_NOT_REACHED'
    assert result['policy']['plan_only'] is True
    assert result['policy']['production_authorized'] is False


def _base_general_monkeypatch(monkeypatch, project: Path, source: Path, ref: Path, *, client_plan=None, server_plan=None, graph=None, fields=None, entities=None):
    client_plan = client_plan or []
    server_plan = server_plan or []
    graph = graph or {'nodes': [], 'edges': []}
    fields = fields or []
    entities = entities or []

    def fake_superset(*args, **kwargs):
        _write_plan(project / 'pt_build/aggregate/client_superset/all/provenance.tsv', client_plan)
        _write_plan(project / 'pt_build/aggregate/server_superset/all/provenance.tsv', server_plan)
        return {'status': 'PASS'}

    graph_dir = project / 'pt_build/vendor_graph'
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')
    (graph_dir / 'summary.json').write_text(json.dumps({'nodes': len(graph.get('nodes', [])), 'edges': len(graph.get('edges', []))}), encoding='utf-8')

    monkeypatch.setattr(gac, 'build_summit_superset', fake_superset)
    monkeypatch.setattr(gac, 'build_dependency_graph', lambda *a, **k: {'status':'PASS','graph_dir':str(graph_dir)})
    monkeypatch.setattr(gac, 'audit_server_entity_bundles', lambda *a, **k: {'status':'PASS','rows':entities, 'report':str(project/'entities.json')})
    monkeypatch.setattr(gac, 'audit_server_field_bundles', lambda *a, **k: {'status':'PASS','rows':fields, 'report':str(project/'fields.json')})
    monkeypatch.setattr(gac, 'audit_server_item_bundles', lambda *a, **k: {'status':'PASS','rows':[], 'report':str(project/'items.json')})
    monkeypatch.setattr(gac, 'audit_client_manifests', lambda *a, **k: {'status':'PASS'})
    monkeypatch.setattr(gac, 'require_source_trees', lambda *a, **k: (SimpleNamespace(root=source), SimpleNamespace(root=ref)))


def test_player_reference_config_does_not_promote_donor_gap_without_current_witness(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    donor=tmp_path/'donor'; donor.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    p=donor/'char/tmABCD/ca018.inx'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    plan=[{'canonical_path':'char/tmABCD/ca018.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(p),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    gdir=project/'pt_build/asset_contracts'; gdir.mkdir(parents=True)
    (gdir/'player_class_contract_graph.json').write_text(json.dumps({
        'nodes':[
            {'node_id':'PLAYER_CLASS:Mechanician','node_type':'PLAYER_CLASS','attributes':{'status':'RUNTIME_JOB_ENABLED'}},
            {'node_id':'ASSET:char/tmabcd/ca018.inx','node_type':'ASSET','attributes':{'logical_path':'char/tmABCD/ca018.inx','resolution':{'status':'RECOVERABLE_REFERENCE','source_label':'DONOR','physical_path':str(p),'candidates':[]}}},
        ],
        'edges':[{'source':'PLAYER_CLASS:Mechanician','target':'ASSET:char/tmabcd/ca018.inx','relation':'USES_CLASS_CONFIG','evidence':'EU_REFERENCE_SOURCE:shared/character.h:1','status':'RECOVERABLE_REFERENCE'}],
    }),encoding='utf-8')
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'DONOR={donor}'],donor_servers=[])
    rows=gac.query_general_asset_census(project,limit=50)['rows']
    row=next(x for x in rows if x['path'].casefold()=='char/tmabcd/ca018.inx')
    assert row['decision']=='DONOR_GAP_NOT_REACHED'
    assert row['required_by_reachable_root']=='False'
    assert 'PLAYER_CLASS_REFERENCE' in row['review_evidence']
    assert r['recoverable_reachable_candidate_count']==0


def test_player_current_config_witness_can_promote_exact_donor_gap(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    donor=tmp_path/'donor'; donor.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    p=donor/'char/tmABCD/ca018.inx'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    plan=[{'canonical_path':'char/tmABCD/ca018.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(p),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [{'class':'Mechanician','logical_inx':'char/tmABCD/ca018.inx'}])
    gdir=project/'pt_build/asset_contracts'; gdir.mkdir(parents=True)
    (gdir/'player_class_contract_graph.json').write_text(json.dumps({
        'nodes':[
            {'node_id':'PLAYER_CLASS:Mechanician','node_type':'PLAYER_CLASS','attributes':{'status':'RUNTIME_JOB_ENABLED'}},
            {'node_id':'ASSET:char/tmabcd/ca018.inx','node_type':'ASSET','attributes':{'logical_path':'char/tmABCD/ca018.inx','resolution':{'status':'RECOVERABLE_REFERENCE','source_label':'DONOR','physical_path':str(p),'candidates':[]}}},
        ],
        'edges':[{'source':'PLAYER_CLASS:Mechanician','target':'ASSET:char/tmabcd/ca018.inx','relation':'USES_CLASS_CONFIG','evidence':'EU_REFERENCE_SOURCE:shared/character.h:1','status':'RECOVERABLE_REFERENCE'}],
    }),encoding='utf-8')
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'DONOR={donor}'],donor_servers=[])
    row=next(x for x in gac.query_general_asset_census(project,limit=50)['rows'] if x['path'].casefold()=='char/tmabcd/ca018.inx')
    assert row['decision']=='RECOVERABLE_REACHABLE_CANDIDATE'
    assert row['required_by_reachable_root']=='True'
    assert r['recoverable_reachable_candidate_count']==1


def test_field_missing_companion_preserves_ase_name_and_stays_review(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    spp=server/'GameServer/Field/Forest.ase.spp'; spp.parent.mkdir(parents=True); spp.write_bytes(b'x')
    fields=[{'basename':'forest','selected_stage':None,'spm':None,'spp':'GameServer/Field/Forest.ase.spp','spc':None}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, fields=fields)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[],donor_servers=[])
    rows=gac.query_general_asset_census(project,limit=100)['rows']
    paths={x['path'].casefold():x for x in rows}
    assert 'gameserver/field/forest.ase.spm' in paths
    assert 'gameserver/field/forest.ase.spc' in paths
    assert 'gameserver/field/forest.spm' not in paths
    assert paths['gameserver/field/forest.ase.spm']['decision']=='REVIEW_REFERENCE_NO_DONOR'
    assert r['missing_reachable_no_donor_count']==0


def test_inx_ase_source_reference_without_smd_is_review_not_blocker(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    inx=client/'char/monster/Foo/Foo.inx'; inx.parent.mkdir(parents=True); inx.write_bytes(b'x')
    graph={
        'nodes':[
            {'id':'server:def','path':'GameServer/Monster/Foo.inf'},
            {'id':'client:char/monster/foo/foo.inx','path':'char/monster/Foo/Foo.inx'},
            {'id':'client:char/monster/foo/source.ase','path':'char/monster/Foo/source.ase'},
        ],
        'edges':[
            {'src':'server:def','dst':'client:char/monster/foo/foo.inx','relation':'server_character_model','evidence':'GameServer/Monster/Foo.inf'},
            {'src':'client:char/monster/foo/foo.inx','dst':'client:char/monster/foo/source.ase','relation':'client_asset_reference','evidence':'embedded source path'},
        ],
    }
    _base_general_monkeypatch(monkeypatch, project, source, ref, graph=graph)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[],donor_servers=[])
    rows=gac.query_general_asset_census(project,limit=100)['rows']
    row=next(x for x in rows if x['path'].casefold()=='char/monster/foo/source.ase')
    assert row['decision']=='REVIEW_REFERENCE_NO_DONOR'
    assert row['required_by_reachable_root']=='False'
    assert 'INX_ASE_SOURCE_REFERENCE' in row['review_evidence']
    assert r['missing_reachable_no_donor_count']==0


def test_current_effect_token_maps_multi_donor_same_relative_part_to_strong_path(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    d1=tmp_path/'d1'; d1.mkdir()
    d2=tmp_path/'d2'; d2.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    rel='Effect/Particle/Script/Venom.part'
    p1=d1/rel; p1.parent.mkdir(parents=True); p1.write_bytes(b'same')
    p2=d2/rel; p2.parent.mkdir(parents=True); p2.write_bytes(b'same')
    plan=[{'canonical_path':rel,'action':'RECOVER_DEDUPED','category':'EFFECT','deployability':'RUNTIME','selected_source':'D1','selected_path':str(p1),'distinct_hash_count':'1','variant_count':'2','reason':'dedup'}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {
        'literal_refs':[],
        'class_skill_mentions':[{'class':'Mechanician','skill_name':'X','layer':'CLIENT_RUNTIME'}],
    })
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    gdir=project/'pt_build/asset_contracts'; gdir.mkdir(parents=True)
    (gdir/'player_class_contract_graph.json').write_text(json.dumps({
        'nodes':[
            {'node_id':'PLAYER_CLASS:Mechanician','node_type':'PLAYER_CLASS','attributes':{'status':'RUNTIME_JOB_ENABLED'}},
            {'node_id':'SKILL:Mechanician:SKILLID_X','node_type':'SKILL','attributes':{}},
            {'node_id':'EFFECT_TOKEN:venom','node_type':'EFFECT_TOKEN','attributes':{}},
            {'node_id':'ASSET:venom.part','node_type':'ASSET','attributes':{'logical_path':'Venom.part','resolution':{'status':'CONFLICT','physical_path':'','candidates':[f'D1:{p1}',f'D2:{p2}']}}},
        ],
        'edges':[
            {'source':'PLAYER_CLASS:Mechanician','target':'SKILL:Mechanician:SKILLID_X','relation':'HAS_SKILL','evidence':'EU_REFERENCE_SOURCE:skill.h:1','status':'REFERENCE_PROVEN'},
            {'source':'SKILL:Mechanician:SKILLID_X','target':'EFFECT_TOKEN:venom','relation':'USES_EFFECT_TOKEN','evidence':'CURRENT_SOURCE:handler.cpp:1','status':'CURRENT_RUNTIME_TOKEN'},
            {'source':'EFFECT_TOKEN:venom','target':'ASSET:venom.part','relation':'RESOLVES_PARTICLE_SCRIPT','evidence':'particle registry','status':'CONFLICT'},
        ],
    }),encoding='utf-8')
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'D1={d1}',f'D2={d2}'],donor_servers=[])
    row=next(x for x in gac.query_general_asset_census(project,limit=100)['rows'] if x['path'].casefold()==rel.casefold())
    assert row['decision']=='RECOVERABLE_REACHABLE_CANDIDATE'
    assert row['required_by_reachable_root']=='True'
    assert r['recoverable_reachable_candidate_count']==1


def _write_spc_add_npc(path: Path, *, model_ini: str, server_npc: str, name: str = 'NPC') -> None:
    import struct
    data = bytearray(100 * 504)
    struct.pack_into('<iI', data, 0, 504, 0x48470070)
    def put(off: int, size: int, value: str) -> None:
        raw = value.encode('ascii')
        assert len(raw) < size
        data[off:off+size] = raw + b'\x00' * (size - len(raw))
    put(8, 32, name)
    put(40, 64, model_ini)
    put(104, 60, server_npc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_npc_definition_inventory_does_not_promote_model_without_runtime_witness(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    donor=tmp_path/'donor'; donor.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    p=donor/'char/npc/Foo/Foo.inx'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    plan=[{'canonical_path':'char/npc/Foo/Foo.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(p),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'}]
    graph={
        'nodes':[
            {'id':'server:gameserver/npc/foo.npc','path':'GameServer/NPC/Foo.npc'},
            {'id':'client:char/npc/foo/foo.inx','path':'char/npc/Foo/Foo.inx'},
        ],
        'edges':[
            {'src':'server:gameserver/npc/foo.npc','dst':'client:char/npc/foo/foo.inx','relation':'server_character_model','evidence':'GameServer/NPC/Foo.npc'},
        ],
    }
    entities=[{'kind':'NPC','definition':'GameServer/NPC/Foo.npc','model_reference':'char/npc/Foo/Foo.ini','zhoon':[]}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan, graph=graph, entities=entities)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'DONOR={donor}'],donor_servers=[])
    row=next(x for x in gac.query_general_asset_census(project,limit=100)['rows'] if x['path'].casefold()=='char/npc/foo/foo.inx')
    assert row['decision']=='DONOR_GAP_NOT_REACHED'
    assert row['required_by_reachable_root']=='False'
    assert 'SERVER_ENTITY_MODEL' in row['review_evidence']
    assert 'SERVER_CHARACTER_MODEL' in row['review_evidence']
    assert r['recoverable_reachable_candidate_count']==0
    assert r['policy']['npc_definition_presence_alone_is_not_runtime_root'] is True


def test_active_standard_spc_without_configured_field_witness_stays_review(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    donor=tmp_path/'donor'; donor.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    p=donor/'char/npc/Foo/Foo.inx'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    plan=[{'canonical_path':'char/npc/Foo/Foo.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(p),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'}]
    spc_rel='GameServer/Field/Test.ase.spc'
    _write_spc_add_npc(server/spc_rel, model_ini='char\\npc\\Foo\\Foo.ini', server_npc='Foo.npc')
    fields=[{'basename':'test','selected_stage':'Field/Test/Test.smd','stage_candidates':['Field/Test/Test.smd'],'spm':None,'spp':None,'spc':spc_rel}]
    graph={
        'nodes':[
            {'id':'server:gameserver/npc/foo.npc','path':'GameServer/NPC/Foo.npc'},
            {'id':'client:char/npc/foo/foo.inx','path':'char/npc/Foo/Foo.inx'},
        ],
        'edges':[
            {'src':'server:gameserver/npc/foo.npc','dst':'client:char/npc/foo/foo.inx','relation':'server_character_model','evidence':'GameServer/NPC/Foo.npc'},
        ],
    }
    entities=[{'kind':'NPC','definition':'GameServer/NPC/Foo.npc','model_reference':'char/npc/Foo/Foo.ini','zhoon':[]}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan, graph=graph, fields=fields, entities=entities)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {'literal_refs':[], 'class_skill_mentions':[]})
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'DONOR={donor}'],donor_servers=[])
    row=next(x for x in gac.query_general_asset_census(project,limit=100)['rows'] if x['path'].casefold()=='char/npc/foo/foo.inx')
    assert row['decision']=='DONOR_GAP_NOT_REACHED'
    assert row['required_by_reachable_root']=='False'
    assert 'SPC_INSTALLED_FIELD_NPC_MODEL' in row['review_evidence']
    assert r['spc_runtime_counts']['STANDARD_ADD_NPC']==1
    assert r['spc_runtime_counts']['STANDARD_ADD_NPC_REVIEW_ONLY']==1
    assert r['recoverable_reachable_candidate_count']==0


def test_active_standard_spc_promotes_only_with_current_source_stage_witness(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    client=tmp_path/'client'; client.mkdir()
    server=tmp_path/'server'; server.mkdir()
    donor=tmp_path/'donor'; donor.mkdir()
    source=tmp_path/'source'; source.mkdir()
    ref=tmp_path/'ref'; ref.mkdir()
    p=donor/'char/npc/Foo/Foo.inx'; p.parent.mkdir(parents=True); p.write_bytes(b'x')
    plan=[{'canonical_path':'char/npc/Foo/Foo.inx','action':'RECOVER','category':'MODEL_OR_MOTION','deployability':'RUNTIME','selected_source':'DONOR','selected_path':str(p),'distinct_hash_count':'1','variant_count':'1','reason':'missing target'}]
    spc_rel='GameServer/Field/Test.ase.spc'
    _write_spc_add_npc(server/spc_rel, model_ini='char\\npc\\Foo\\Foo.ini', server_npc='Foo.npc')
    fields=[{'basename':'test','selected_stage':'Field/Test/Test.smd','stage_candidates':['Field/Test/Test.smd'],'spm':None,'spp':None,'spc':spc_rel}]
    graph={
        'nodes':[
            {'id':'server:gameserver/npc/foo.npc','path':'GameServer/NPC/Foo.npc'},
            {'id':'client:char/npc/foo/foo.inx','path':'char/npc/Foo/Foo.inx'},
        ],
        'edges':[
            {'src':'server:gameserver/npc/foo.npc','dst':'client:char/npc/foo/foo.inx','relation':'server_character_model','evidence':'GameServer/NPC/Foo.npc'},
        ],
    }
    entities=[{'kind':'NPC','definition':'GameServer/NPC/Foo.npc','model_reference':'char/npc/Foo/Foo.ini','zhoon':[]}]
    _base_general_monkeypatch(monkeypatch, project, source, ref, client_plan=plan, graph=graph, fields=fields, entities=entities)
    monkeypatch.setattr(gac, 'scan_source_evidence', lambda *a, **k: {
        'literal_refs':[{'value':'Field/Test/Test.ase','source_file':'SrcGame/src/field.cpp','line':10}],
        'class_skill_mentions':[],
    })
    monkeypatch.setattr(gac, 'parse_reference_class_configs', lambda *a, **k: [])
    r=gac.audit_general_asset_census(project,client,server,source_root=source,reference_source_root=ref,donor_clients=[f'DONOR={donor}'],donor_servers=[])
    row=next(x for x in gac.query_general_asset_census(project,limit=100)['rows'] if x['path'].casefold()=='char/npc/foo/foo.inx')
    assert row['decision']=='RECOVERABLE_REACHABLE_CANDIDATE'
    assert row['required_by_reachable_root']=='True'
    assert 'SPC_ACTIVE_NPC_MODEL' in row['reachability_evidence']
    assert r['spc_runtime_counts']['STANDARD_ADD_NPC']==1
    assert r['spc_runtime_counts']['STANDARD_ADD_NPC_STRONG']==1
    assert r['recoverable_reachable_candidate_count']==1
    assert r['field_runtime_witness_counts']['CURRENT_SOURCE_FIELD_STAGE_LITERAL']==1


def test_field_stage_witness_accepts_exact_ase_smd_sibling_alias():
    row={'stage_candidates':['Field/Room/office.smd'], 'selected_stage':'Field/Room/office.smd'}
    witness, basis = gac._field_source_stage_witness(row, {'field/room/office.ase'})
    assert witness == 'Field/Room/office.smd'
    assert basis == 'CURRENT_SOURCE_FIELD_STAGE_LITERAL'


def _bundle_plan_row(rel: str, path: Path, *, action: str = 'RECOVER') -> dict[str, str]:
    return {
        'canonical_path': rel,
        'action': action,
        'category': 'MODEL_OR_MOTION',
        'deployability': 'RUNTIME',
        'selected_source': 'D1',
        'selected_path': str(path),
        'distinct_hash_count': '1',
        'variant_count': '1',
        'reason': 'missing target',
    }


def test_client_recovery_bundle_closes_only_same_lineage_dependencies(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    donor=tmp_path/'d1'; donor.mkdir()
    inx=donor/'char/monster/Foo/Foo.inx'; inx.parent.mkdir(parents=True); inx.write_bytes(b'char\\monster\\Foo\\Foo.smd\x00')
    smd=donor/'char/monster/Foo/Foo.smd'; smd.write_bytes(b'SMD Model data Ver 0.62')
    tex=donor/'char/monster/Foo/foo.tga'; tex.write_bytes(b'tex')
    plan_rows=[
        _bundle_plan_row('char/monster/Foo/Foo.inx', inx),
        _bundle_plan_row('char/monster/Foo/Foo.smd', smd),
        _bundle_plan_row('char/monster/Foo/foo.tga', tex),
    ]
    plan_by_key={x['canonical_path'].casefold():x for x in plan_rows}
    monkeypatch.setattr(gac, 'face_texture_references_model062', lambda *a, **k: {'status':'PASS', 'required_names':['foo.tga']})
    result=gac._assess_client_recovery_bundle(project, plan_rows[0], target_idx={}, donor_roots=[('D1', donor)], donor_index_cache={}, plan_by_key=plan_by_key)
    assert result['status']=='CLOSED'
    assert result['missing_count']==0
    assert result['review_count']==0
    assert {x['logical_path'].casefold() for x in result['members']} >= {'char/monster/foo/foo.inx','char/monster/foo/foo.smd','char/monster/foo/foo.tga'}
    states={x['logical_path'].casefold():x['state'] for x in result['members']}
    assert states['char/monster/foo/foo.smd']=='RECOVER_SAME_DONOR'
    assert states['char/monster/foo/foo.tga']=='RECOVER_SAME_DONOR'


def test_client_recovery_bundle_refuses_cross_donor_dependency(monkeypatch, tmp_path):
    project=tmp_path/'app'; project.mkdir()
    d1=tmp_path/'d1'; d1.mkdir()
    d2=tmp_path/'d2'; d2.mkdir()
    inx=d1/'char/monster/Foo/Foo.inx'; inx.parent.mkdir(parents=True); inx.write_bytes(b'char\\monster\\Foo\\Foo.smd\x00')
    smd=d1/'char/monster/Foo/Foo.smd'; smd.write_bytes(b'SMD Model data Ver 0.62')
    tex=d2/'char/monster/Foo/foo.tga'; tex.parent.mkdir(parents=True); tex.write_bytes(b'tex')
    root=_bundle_plan_row('char/monster/Foo/Foo.inx', inx)
    plan_by_key={root['canonical_path'].casefold():root,'char/monster/foo/foo.smd':_bundle_plan_row('char/monster/Foo/Foo.smd', smd),'char/monster/foo/foo.tga':_bundle_plan_row('char/monster/Foo/foo.tga', tex)}
    monkeypatch.setattr(gac, 'face_texture_references_model062', lambda *a, **k: {'status':'PASS', 'required_names':['foo.tga']})
    result=gac._assess_client_recovery_bundle(project, root, target_idx={}, donor_roots=[('D1', d1), ('D2', d2)], donor_index_cache={}, plan_by_key=plan_by_key)
    assert result['status']=='INCOMPLETE'
    assert result['missing_count']==1
    assert any(x['kind']=='MISSING_SAME_LINEAGE_DEPENDENCY' for x in result['issues'])


def test_inx_ase_alias_prefers_smd_over_smb(tmp_path):
    donor = tmp_path / "donor"; donor.mkdir()
    smd = donor / "char/monster/Foo/Foo.smd"; smd.parent.mkdir(parents=True); smd.write_bytes(b"smd")
    smb = donor / "char/monster/Foo/Foo.smb"; smb.write_bytes(b"smb")
    idx = {"char/monster/foo/foo.smd": smd, "char/monster/foo/foo.smb": smb}
    result = gac._resolve_bundle_reference(
        "char/monster/Foo/Foo.ASE", "char/monster/Foo/Foo.inx",
        parent_ext=".inx", target_idx={}, donor_idx=idx,
    )
    assert result["status"] == "RECOVER_SAME_DONOR"
    assert result["logical_path"].casefold() == "char/monster/foo/foo.smd"
    assert result["resolution_basis"] == "INX_ASE_TO_SMD_RUNTIME_ALIAS"


def test_inx_ase_alias_resolves_smb_when_smd_absent(tmp_path):
    donor = tmp_path / "donor"; donor.mkdir()
    smb = donor / "char/monster/Hina/mHina.smb"; smb.parent.mkdir(parents=True); smb.write_bytes(b"smb")
    idx = {"char/monster/hina/mhina.smb": smb}
    result = gac._resolve_bundle_reference(
        "mHina.ASE", "char/monster/Hina/Hina.inx",
        parent_ext=".inx", target_idx={}, donor_idx=idx,
    )
    assert result["status"] == "RECOVER_SAME_DONOR"
    assert result["logical_path"].casefold() == "char/monster/hina/mhina.smb"
    assert result["resolution_basis"] == "INX_ASE_TO_SMB_RUNTIME_ALIAS"


def test_inx_ase_alias_missing_stays_same_lineage_missing():
    result = gac._resolve_bundle_reference(
        "mMissing.ASE", "char/monster/Hina/Hina.inx",
        parent_ext=".inx", target_idx={}, donor_idx={},
    )
    assert result["status"] == "MISSING_SAME_LINEAGE"
    assert result["resolution_basis"] == "NO_EXACT_OR_SAME_DIRECTORY_MATCH"


def test_client_recovery_bundle_treats_smb_alias_as_leaf(tmp_path):
    project = tmp_path / "app"; project.mkdir()
    donor = tmp_path / "donor"; donor.mkdir()
    inx = donor / "char/monster/Hina/Hina.inx"; inx.parent.mkdir(parents=True); inx.write_bytes(b"mHina.ASE\x00")
    smb = donor / "char/monster/Hina/mHina.smb"; smb.write_bytes(b"not-a-parseable-container")
    rows = [
        _bundle_plan_row("char/monster/Hina/Hina.inx", inx),
        _bundle_plan_row("char/monster/Hina/mHina.smb", smb),
    ]
    result = gac._assess_client_recovery_bundle(
        project, rows[0], target_idx={}, donor_roots=[("D1", donor)], donor_index_cache={},
        plan_by_key={x["canonical_path"].casefold(): x for x in rows},
    )
    assert result["status"] == "CLOSED"
    member = next(x for x in result["members"] if x["logical_path"].casefold().endswith("mhina.smb"))
    assert member["resolution_basis"] == "INX_ASE_TO_SMB_RUNTIME_ALIAS"




def test_client_recovery_bundle_supports_stage072_face_texture_scope(monkeypatch, tmp_path):
    project = tmp_path / "app"; project.mkdir()
    donor = tmp_path / "d1"; donor.mkdir()
    smd = donor / "Field/HeartOfFire/HeartOfFire.smd"
    smd.parent.mkdir(parents=True)
    smd.write_bytes(b"SMD Stage data Ver 0.72" + b"\0" * 64)
    tex = donor / "Field/HeartOfFire/lava.tga"
    tex.write_bytes(b"tex")

    fake_module = SimpleNamespace(parse_stage072=lambda _path: {
        "full_parse": "PASS",
        "material_face_counts": {"0": 4, "1": 0},
        "materials": [
            {"id": 0, "textures": [{"Name": "lava.tga"}, {"Name": "w"}], "anim_textures": []},
            {"id": 1, "textures": [{"Name": "unused.tga"}], "anim_textures": []},
        ],
    })
    monkeypatch.setitem(sys.modules, "pt_asset_tool.stage072_corpus", fake_module)

    rows = [
        _bundle_plan_row("Field/HeartOfFire/HeartOfFire.smd", smd),
        _bundle_plan_row("Field/HeartOfFire/lava.tga", tex),
    ]
    idx = {
        "field/heartoffire/heartoffire.smd": smd,
        "field/heartoffire/lava.tga": tex,
    }
    result = gac._assess_client_recovery_bundle(
        project, rows[0], target_idx={}, donor_roots=[("D1", donor)],
        donor_index_cache={"D1": idx},
        plan_by_key={x["canonical_path"].casefold(): x for x in rows},
    )

    assert result["status"] == "CLOSED"
    assert result["missing_count"] == 0
    assert result["review_count"] == 0
    assert {x["logical_path"].casefold() for x in result["members"]} >= {
        "field/heartoffire/heartoffire.smd", "field/heartoffire/lava.tga",
    }
    assert not any("unused.tga" in x["logical_path"].casefold() for x in result["members"])
    assert not any(x["logical_path"].casefold().endswith("/w") for x in result["members"])


def test_stage072_face_scope_parse_failure_stays_review(monkeypatch, tmp_path):
    project = tmp_path / "app"; project.mkdir()
    smd = tmp_path / "Map.smd"
    smd.write_bytes(b"SMD Stage data Ver 0.72" + b"\0" * 64)
    fake_module = SimpleNamespace(parse_stage072=lambda _path: {
        "full_parse": "FAIL", "checks": {"area_payload": "FAIL"}, "errors": {"area": ["bad"]},
    })
    monkeypatch.setitem(sys.modules, "pt_asset_tool.stage072_corpus", fake_module)
    scope = gac._face_texture_references_smd(smd, project)
    assert scope["status"] == "REVIEW"
    assert scope["semantics"] == "STAGE072_FACE_SCOPE_UNPROVEN"
    assert scope["parser_checks"]["area_payload"] == "FAIL"

def test_server_zhoon_recovery_bundle_is_closed_leaf(tmp_path):
    donor=tmp_path/'server_donor'; donor.mkdir()
    z=donor/'GameServer/Monster/name/Test.zhoon'; z.parent.mkdir(parents=True); z.write_bytes('*J_NAME "Test"\n'.encode('cp1252'))
    row={'canonical_path':'GameServer/Monster/name/Test.zhoon','selected_path':str(z),'selected_source':'D1'}
    result=gac._assess_server_recovery_bundle(row, [('D1', donor)])
    assert result['status']=='CLOSED'
    assert result['member_count']==1
    assert result['missing_count']==0
