"""V5: real-file evidence precedence, isolated release audit and legacy census."""
from __future__ import annotations
import json
import os
from pathlib import Path

from pt_asset_tool import etervale_ui_readiness as ui
from pt_asset_tool import etervale_p0_release_selftest as selftest
from pt_asset_tool import etervale_migration_audit as mig
from pt_asset_tool.app_config import save_etervale_root


def put(folder,name,record,when):
    folder.mkdir(parents=True,exist_ok=True)
    p=folder/name
    p.write_text(json.dumps(record),encoding='utf8')
    os.utime(p,ns=(when,when))
    return p


def make_proofs(tmp_path):
    w=tmp_path/'etervale'
    pass_rec={'status':ui.CONTENT_PASS,'format':ui.CONTENT_FORMAT,
              'game_assets_modified':False,'verification':{
                'semantic_catalog_changes':{'OpenItem':['item_definitions'],
                                            'Monster':['monsters'],'NPC':['npcs'],'Field':['fields']}}}
    proof=put(w/'content_compat','passed.json',pass_rec,1_000_000_000)
    bad=put(w/'content_compat','failed.json',{'format':ui.CONTENT_FORMAT,
                 'status':'FAILED_NATIVE_SEMANTICS'},2_000_000_000)
    closure=put(w/'p0_closure','approved.json',{
        'format':'PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1',
        'status':ui.CLOSURE_PASS,'remaining_gates':[],
        'native_four_domain_import_proof':str(proof)},3_000_000_000)
    return w,proof,bad,closure


def get_item(result,key):
    return next(item for item in result['items'] if item['id']==key)


def test_board_prefers_four_domain_closure_over_old_failed_probe(tmp_path):
    w,proof,bad,_=make_proofs(tmp_path)
    result=ui.board(tmp_path)
    content=get_item(result,'content')
    assert content['state']=='CERTIFIED_BY_P0_CLOSURE_NOT_RUNTIME'
    assert content['evidence']['status']==ui.CONTENT_PASS
    assert content['evidence']['evidence_file'].endswith('passed.json')
    assert content['evidence']['selected_by'].startswith('FOUR_DOMAIN_PROOF')
    assert len(result['items'])==len(ui.DOMAINS)==8
    assert result['game_assets_modified'] is False


def test_newer_failed_probe_is_not_hidden(tmp_path):
    w,proof,bad,closure=make_proofs(tmp_path)
    os.utime(bad,ns=(4_000_000_000,4_000_000_000))
    c=get_item(ui.board(tmp_path),'content')
    assert c['state']=='REVIEW_NEWER_FAILURE'
    assert c['evidence']['status']=='FAILED_NATIVE_SEMANTICS'
    assert c['previous_certified_evidence']['status']==ui.CONTENT_PASS


def test_closure_reference_escape_and_corrupt_proof_not_trusted(tmp_path):
    w,proof,bad,closure=make_proofs(tmp_path)
    evil=tmp_path/'outside.json'
    evil.write_text(proof.read_text())
    closure.write_text(json.dumps({'format':'PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1',
        'status':ui.CLOSURE_PASS,'remaining_gates':[],
        'native_four_domain_import_proof':str(evil)}))
    c=get_item(ui.board(tmp_path),'content')
    assert c['state']=='EVIDENCE_AVAILABLE'
    assert c['evidence']['status']=='FAILED_NATIVE_SEMANTICS'


def test_release_selftest_real_apply_and_guarded_rollback(tmp_path):
    outcome=selftest.exercise(tmp_path/'lab')
    assert outcome['status']==selftest.PASS
    assert outcome['check_count']==6
    assert all(outcome['checks'].values())
    assert outcome['production_assets_modified'] is False
    assert not list((tmp_path/'lab').iterdir())  # private lab cleaned


def test_release_selftest_board_does_not_claim_production(tmp_path):
    put(tmp_path/'etervale'/'p0_release_selftest','test.json',{
        'format':selftest.FORMAT,'status':selftest.PASS,
        'selftest_only':True,'production_assets_modified':False,
        'proof_level':'ISOLATED_SHA_APPLY_ROLLBACK_MECHANICS_ONLY'},3_000_000_000)
    release=get_item(ui.board(tmp_path),'release')
    assert release['state']=='ISOLATED_SELFTEST_ONLY'
    assert release['evidence']['source_kind']=='ISOLATED_SELFTEST'


def project(tmp_path):
    repo=tmp_path/'Etervale-git'
    for rel in ['assets/GameServer','Client','Server','Shared','tools/PristonTale.AssetDump']:
        (repo/rel).mkdir(parents=True)
    (repo/'PristonTale.sln').write_text('')
    (repo/'tools/PristonTale.AssetDump/PristonTale.AssetDump.csproj').write_text('<Project/>')
    return repo


def test_legacy_audit_scans_every_module_and_validates_unified_root(tmp_path, monkeypatch):
    monkeypatch.delenv('PT_ETERVALE_ROOT',raising=False)
    monkeypatch.delenv('PT_CLIENT_ROOT',raising=False)
    monkeypatch.delenv('PT_SERVER_ROOT',raising=False)
    code=tmp_path/'app/pt_asset_tool'
    (code/'legacy_data_tools/content_port').mkdir(parents=True)
    (code/'legacy_data_tools/content_port/old.py').write_text('PATH="Summit Tale Client Full"\n')
    (code/'etervale_x.py').write_text('print("etervale")\n')
    (code/'canonical_authoring.py').write_text('from pathlib import Path\nPath("x").write_text("ok")\n')
    game=project(tmp_path)
    app=tmp_path/'app'
    save_etervale_root(app,game)
    audit=mig.audit(code,app,game)
    assert audit['scanned_python_files']==3
    assert audit['root_routing']['status']=='PASS_UNIFIED_ASSET_ROOT_ROUTING'
    assert audit['classification_counts']['HISTORICAL_ISOLATED_NOT_NATIVE']==1
    assert audit['classification_counts']['ACTIVE_LEGACY_WORKFLOW_REVIEW_REQUIRED']==1
    assert 'canonical_authoring.py' in audit['active_legacy_review_required']
    assert audit['legacy_runtime_pack_policy'].startswith('DO_NOT_PUBLISH')
    assert audit['all_ui_commands_tested'] is False


def test_legacy_audit_does_not_claim_config_match_from_explicit_root_only(tmp_path,monkeypatch):
    monkeypatch.delenv('PT_ETERVALE_ROOT',raising=False)
    code=tmp_path/'app/pt_asset_tool';code.mkdir(parents=True)
    (code/'x.py').write_text('x=1')
    game=project(tmp_path)
    result=mig.audit(code,tmp_path/'app',game)
    assert result['root_routing']['status']=='ETERVALE_ROOT_NOT_CONFIGURED'


def test_ui_template_displays_source_and_selftest_disclaimer():
    path=Path(__file__).resolve().parents[1]/'pt_asset_tool/ui_static/etervale-readiness.html'
    template=path.read_text()
    assert 'item.note' in template
    assert 'ISOLATED_SELFTEST' in template
    assert 'textContent=value' in template


def test_newer_failed_p0_closure_never_reuses_old_pass(tmp_path):
    w,proof,bad,closure=make_proofs(tmp_path)
    put(w/'p0_closure','failed_after.json',{
        'format':'PT_ASSET_ETERVALE_P0_CLOSURE_GATES_V1',
        'status':'P0_AUTHORING_GATES_INCOMPLETE',
        'remaining_gates':['GAME_SERVER_FOUR_DOMAIN_IMPORT']},4_000_000_000)
    content=get_item(ui.board(tmp_path),'content')
    assert content['state']=='EVIDENCE_AVAILABLE'
    assert content['evidence']['status']=='FAILED_NATIVE_SEMANTICS'
