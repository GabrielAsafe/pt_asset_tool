from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import pytest

from pt_asset_tool import etervale_entity_names as names
from pt_asset_tool.smd_preview import SmdPreviewManager, INDEX_FORMAT
from pt_asset_tool.entity_catalog import query_built_entities


def _db(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
        conn.executescript('''
        CREATE TABLE npcs (id INTEGER PRIMARY KEY, key TEXT, model TEXT);
        CREATE TABLE npc_texts (npc_id INTEGER, language TEXT, name TEXT);
        CREATE TABLE monsters (id INTEGER PRIMARY KEY, key TEXT, model TEXT);
        CREATE TABLE monster_texts (monster_id INTEGER, language TEXT, name TEXT);
        INSERT INTO npcs VALUES (1,'hob_goblin','char/npc/TN-008/tn-008.inx');
        INSERT INTO npcs VALUES (2,'fraud','char/npc/TN-008/tn-008.inx');
        INSERT INTO npc_texts VALUES (1,'en','Mr. HobGoblin');
        INSERT INTO npc_texts VALUES (1,'pt-BR','Sr. HobGoblin');
        INSERT INTO npc_texts VALUES (2,'en','Fraud');
        INSERT INTO monsters VALUES (3,'acero','char/monster/Acero/Acero.inx');
        INSERT INTO monster_texts VALUES (3,'en','Acero');
        ''')
    return path


def test_game_names_model_can_have_multiple_in_game_names(tmp_path):
    db = _db(tmp_path / 'world.db')
    found = names.read_names(db)
    assert found[('NPC','tn-008')] == ['Fraud','Mr. HobGoblin']
    assert found[('MONSTER','acero')] == ['Acero']
    rows = [{'entity_key':'NPC|char/npc/tn-008','semantic_group':'NPC','display_name':'TN-008',
             'folder_root':'char/npc/TN-008','_search_text':'tn-008'},
            {'entity_key':'MAP_FIELD|field/ancientw','semantic_group':'MAP_FIELD','display_name':'AncientW',
             'folder_root':'Field/AncientW'}]
    out = names.annotate(rows, found)
    assert out[0]['display_name'] == 'TN-008'  # identity never replaced
    assert out[0]['in_game_names'] == ['Fraud','Mr. HobGoblin']
    assert 'hobgoblin' in out[0]['_search_text']
    assert query_built_entities(out, group='NPC', q='TN-008')['matched_entity_count'] == 1
    assert query_built_entities(out, group='NPC', q='HobGoblin')['matched_entity_count'] == 1
    assert out[1] is rows[1]


def test_game_name_db_validation_and_read_only(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    db = _db(tmp_path / 'world.sqlite')
    before = db.read_bytes()
    status = names.save_path(project, str(db))
    assert status['status'] == 'READY_READ_ONLY_SQLITE'
    assert status['source'] == 'EXPLICIT_SQLITE'
    assert names.read_names(db)
    assert db.read_bytes() == before
    assert names.configured_path(project) == db.resolve()
    assert names.save_path(project, '')['status'] == 'NOT_CONFIGURED'


def test_invalid_db_does_not_replace_configuration(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    db = _db(tmp_path / 'world.db')
    names.save_path(project, str(db))
    with pytest.raises(ValueError, match='SCHEMA_OR_PATH'):
        names.save_path(project, str(tmp_path / 'missing.db'))
    assert names.configured_path(project) == db.resolve()


def test_only_valid_world_catalog_is_auto_discovered(tmp_path):
    game = tmp_path / 'Etervale-git'
    server = game / 'assets' / 'GameServer'
    server.mkdir(parents=True)
    with sqlite3.connect(server / 'wrong.sqlite') as conn:
        conn.execute('CREATE TABLE misc(id INT)')
    right = _db(game / 'world.sqlite')
    assert names.discover_path(server) == right.resolve()
    assert names.source_status(tmp_path / 'app', server)['source'] == 'AUTO_DISCOVERED_SQLITE'


def test_external_batch_changes_are_loaded_without_restart(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    client = tmp_path / 'assets'; client.mkdir()
    ui_manager = SmdPreviewManager(project, client)
    batch_manager = SmdPreviewManager(project, client)
    try:
        assert not ui_manager.status_index()
        batch_manager._index_update('char/npc/TN-008/actor.smd', status='READY')
        assert ui_manager.status_index()['char/npc/tn-008/actor.smd']['status'] == 'READY'
        ui_manager._index_update('other.smd',status='FAILED')
        # UI updates must not drop ready rows written by the other process.
        assert batch_manager.status_index()['other.smd']['status'] == 'FAILED'
        assert batch_manager.status_index()['char/npc/tn-008/actor.smd']['status'] == 'READY'
    finally:
        ui_manager._stop.set()
        batch_manager._stop.set()


def test_web_integrations_and_layout_are_present():
    base = Path(__file__).parents[1] / 'pt_asset_tool'
    html = (base / 'ui_static' / 'index.html').read_text()
    js = (base / 'ui_static' / 'app.js').read_text()
    code = (base / 'ui_app.py').read_text()
    preview = (base / 'smd_preview_batch.py').read_text()
    assert html.count('id="doctorBtn"') == 1 and html.count('id="reindexBtn"') == 1
    assert html.find('id="doctorBtn"') > html.find('id="tab-settings"')
    assert 'id="tab-validation"' not in html and 'data-support-tab="validation"' not in html
    assert 'id="entityNameDbPath"' in html and 'id="etervaleEvidenceSummary"' in html
    assert 'planning_processed' in preview and 'phase' in preview
    assert 'batch.get("status") == "RUNNING"' in code and '"job": job' in code
    assert 'loadEntityNameSource()' in js and 'in_game_names' in js
    assert 'mark_all_stale("REGISTRY_REINDEXED")' not in code


def test_smd_batch_skips_already_ready_and_persists_planning(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pt_asset_tool.smd_preview_batch as batch
    project = tmp_path / 'app';project.mkdir()
    client=tmp_path / 'assets';client.mkdir()
    inventory=project / 'inventory.json';inventory.write_text('{}')
    pairing=project / 'pairing.json';pairing.write_text('{}')
    monkeypatch.setattr(batch.Settings, 'discover', lambda *a, **k:SimpleNamespace(client_root=client,inventory=inventory,pairing=pairing))
    monkeypatch.setattr(batch, 'blender_runtime_info', lambda *a, **k: {'ready':True,'source':'fixture','version':'fixture','command':['fake']})
    class R:
        def prime_from_inventory(self, *args):pass
    monkeypatch.setattr(batch, 'ClientResolver', lambda *a, **k:R())
    assets=[SimpleNamespace(family='SMD_MODEL_062_STATIC',primary_path=path) for path in ['ready.smd','new.smd']]
    monkeypatch.setattr(batch, 'AssetRegistry', lambda *a, **k:SimpleNamespace(assets=assets))
    monkeypatch.setattr(batch, 'build_smd_preview_plan', lambda *a, **k:{'logical':a[-1], 'dependency_paths':[]})
    monkeypatch.setattr(batch.SmdPreviewManager,'classify', lambda self,plan: {'status':'READY' if plan['logical']=='ready.smd' else 'MISSING'})
    renders=[]
    def render(self, plan, **kwargs):
        renders.append(plan['logical'])
        self._index_update(plan['logical'],status='READY')
        return {'status':'READY'}
    monkeypatch.setattr(batch.SmdPreviewManager,'render_now',render)
    result=batch.run_batch(project,client,mode='warmup')
    assert result['status']=='COMPLETE'
    assert result['phase']=='RENDERING'
    assert result['planning_processed']==2
    assert result['selected_for_render']==1
    assert result['completed']==1
    assert renders==['new.smd']
    assert batch.read_batch_state(project)['completed']==1


def test_ambiguous_sqlite_sources_are_not_guessed(tmp_path):
    game = tmp_path / 'Etervale-git'
    server = game / 'assets' / 'GameServer'
    server.mkdir(parents=True)
    _db(game / 'world.sqlite')
    _db(server / 'world.db')
    assert names.discover_path(server) is None
    status=names.source_status(tmp_path / 'app', server)
    assert status['status'] == 'AMBIGUOUS_WORLD_SQLITE_SELECT_EXPLICIT'
    assert status['candidate_count'] == 2
