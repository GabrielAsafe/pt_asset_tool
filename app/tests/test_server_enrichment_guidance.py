from __future__ import annotations

import json
import pathlib
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from pt_asset_tool.ui_app import UIContext, UIHandler


def request(url: str, token: str | None = None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if token:
        headers['X-PT-UI-Token'] = token
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def make(tmp_path: pathlib.Path):
    project = tmp_path / 'project'
    client = tmp_path / 'client'
    tool = project / 'pt_asset_tool'
    tool.mkdir(parents=True)
    client.mkdir()
    (project / 'pt_asset.py').write_text(
        '#!/usr/bin/env python3\nimport json,sys\n'
        'if sys.argv[1:]==["--version"]: print("9.9-test")\n'
        'else: print(json.dumps({"status":"PASS","argv":sys.argv[1:]}))\n'
    )
    ctx = UIContext(project, client)
    server = ThreadingHTTPServer(('127.0.0.1', 0), UIHandler)
    server.ctx = ctx
    ctx.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return project, client, ctx, server, thread, f'http://127.0.0.1:{server.server_address[1]}'


def test_general_census_readiness_explains_required_roots_and_cli_scope(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    try:
        _, b = request(url + '/api/bootstrap')
        _, summary = request(url + '/api/contracts')
        ready = summary['general_census_readiness']
        assert ready['state'] == 'BLOCKED'
        codes = {x['code'] for x in ready['blockers']}
        assert {'SERVER_ROOT_REQUIRED', 'SOURCE_ROOT_REQUIRED', 'REFERENCE_SOURCE_ROOT_REQUIRED'} <= codes
        warning_codes = {x['code'] for x in ready['warnings']}
        assert {'NO_DONOR_CLIENTS_CONFIGURED', 'NO_DONOR_SERVERS_CONFIGURED'} <= warning_codes
        note_codes = {x['code'] for x in ready['notes']}
        assert {'CLI_ARGUMENTS_ARE_ONE_RUN_ONLY', 'EXTERNAL_JOB_NOT_TRACKED'} <= note_codes
        assert ready['command'] is None
        assert '<CONFIGURE_SERVER_ROOT>' in ready['command_preview']
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_general_census_readiness_builds_saved_command_and_detects_donor_drift(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    server_root = tmp_path / 'server'
    source = tmp_path / 'source'
    reference = tmp_path / 'reference'
    donor_client = tmp_path / 'donor client'
    donor_server = tmp_path / 'donor server'
    for p in (server_root, source, reference, donor_client, donor_server):
        p.mkdir()
    try:
        _, b = request(url + '/api/bootstrap')
        token = b['token']
        request(url + '/api/server/config', token, {'server_root': str(server_root)})
        _, c = request(url + '/api/contracts/config', token, {
            'source_root': str(source),
            'reference_source_root': str(reference),
            'donor_clients': [f'OFFICIAL={donor_client}'],
            'donor_servers': [f'OFFICIAL_SERVER={donor_server}'],
        })
        ready = c['general_census_readiness']
        assert ready['state'] == 'READY_TO_RUN' and ready['can_run'] is True
        cmd = ready['command']
        assert cmd[cmd.index('--client-root') + 1] == str(client.resolve())
        assert cmd[cmd.index('--server-root') + 1] == str(server_root.resolve())
        assert f'OFFICIAL={donor_client.resolve()}' in cmd
        assert f'OFFICIAL_SERVER={donor_server.resolve()}' in cmd
        assert "'" in ready['command_preview']

        census = project / 'pt_build/general_asset_census'
        census.mkdir(parents=True)
        (census / 'result.json').write_text(json.dumps({
            'status': 'PASS', 'census_state': 'PLAN_READY', 'generated_at': 1,
            'client_root': str(client.resolve()), 'server_root': str(server_root.resolve()),
            'source_root': str(source.resolve()), 'reference_source_root': str(reference.resolve()),
            'donor_client_roots': [{'label': 'OFFICIAL', 'root': str(donor_client.resolve())}],
            'donor_server_roots': [{'label': 'OFFICIAL_SERVER', 'root': str(donor_server.resolve())}],
            'candidate_count': 12, 'recoverable_reachable_candidate_count': 2,
            'missing_reachable_no_donor_count': 0,
        }))
        (census / 'candidates.tsv').write_text('path\tdecision\n')
        _, summary = request(url + '/api/contracts')
        assert summary['general_census_readiness']['state'] == 'REPORT_FRESH'
        assert summary['general_census_readiness']['freshness'] == 'FRESH_CONFIG'

        _, changed = request(url + '/api/contracts/config', token, {
            'source_root': str(source), 'reference_source_root': str(reference),
            'donor_clients': [], 'donor_servers': [],
        })
        stale = changed['general_census_readiness']
        assert stale['state'] == 'REPORT_STALE'
        assert stale['freshness'] == 'STALE_CONFIG'
        assert {'DONOR_CLIENTS_CHANGED', 'DONOR_SERVERS_CHANGED'} <= set(stale['freshness_reasons'])
        _, rows = request(url + '/api/general-census')
        assert rows['freshness'] == 'STALE_CONFIG'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_server_review_rows_include_explanation_and_safe_actions(tmp_path: pathlib.Path):
    project, client, ctx, server, thread, url = make(tmp_path)
    report_dir = project / 'pt_build/devtest/server_bundle_census'
    report_dir.mkdir(parents=True)
    (report_dir / 'result.json').write_text(json.dumps({
        'status': 'PASS', 'status_counts': {'VISUAL_ENTRY_RESOLVED': 1},
        'reason_counts': {'ZHOON_SHARED_DEFAULT_REVIEW': 1},
        'rows': [{
            'kind': 'MONSTER', 'status': 'VISUAL_ENTRY_RESOLVED',
            'definition': 'GameServer/Monster/100_Test.inf',
            'model_reference': 'char/monster/test/test.ini',
            'logical_inx': 'char/monster/test/test.inx',
            'server_inx_exists': True, 'client_inx_exists': True,
            'zhoon': [{'reference': 'Name/Name.zhoon', 'exists_server': False}],
            'reasons': ['ZHOON_SHARED_DEFAULT_REVIEW'],
        }],
    }))
    try:
        _, d = request(url + '/api/server/report?kind=entities')
        row = d['rows'][0]
        assert row['review_required'] is True
        assert 'visual principal' in row['review_summary'].lower()
        assert row['review_reasons'][0]['code'] == 'ZHOON_SHARED_DEFAULT_REVIEW'
        kinds = {x['kind'] for x in row['review_actions']}
        assert {'catalog', 'general_census'} <= kinds
        assert not any(x['kind'] in {'write', 'publish', 'deploy'} for x in row['review_actions'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_server_enrichment_guidance_is_exposed_in_static_ui():
    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / 'pt_asset_tool/ui_static/index.html').read_text(encoding='utf-8')
    js = (root / 'pt_asset_tool/ui_static/app.js').read_text(encoding='utf-8')
    server_ui = (root / 'pt_asset_tool/server_ui.py').read_text(encoding='utf-8')
    for token in [
        'generalCensusGuide', 'generalCensusReadinessState', 'generalCensusChecklist',
        'generalCensusNotices', 'generalCensusCommand', 'copyGeneralCensusCommandBtn',
    ]:
        assert token in html
    for token in ['renderGeneralCensusReadiness', 'handleServerReviewAction', 'Próximas ações seguras', 'Sem relatório final']:
        assert token in js
    for token in ['review_summary', 'review_reasons', 'review_actions', 'ZHOON_SHARED_DEFAULT_REVIEW']:
        assert token in server_ui
