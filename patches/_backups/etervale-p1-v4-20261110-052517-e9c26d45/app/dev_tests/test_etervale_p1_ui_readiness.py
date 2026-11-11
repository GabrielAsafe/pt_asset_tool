import json
from pt_asset_tool.etervale_ui_readiness import board, DOMAINS

def test_ui_status_reports_no_evidence(tmp_path):
    result=board(tmp_path)
    assert len(result['items'])==len(DOMAINS)==7
    assert all(r['evidence'] is None for r in result['items'])

def test_ui_status_reads_private_reports_only(tmp_path):
    path=tmp_path/'etervale'/'writer_probes';path.mkdir(parents=True)
    (path/'a.json').write_text(json.dumps({'status':'READER_ACCEPTED_NOT_RUNTIME_CERTIFIED',
                                          'format':'test'}))
    result=board(tmp_path)
    assert result['items'][0]['evidence']['status']=='READER_ACCEPTED_NOT_RUNTIME_CERTIFIED'
    assert result['items'][0]['evidence']['evidence_file']=='etervale/writer_probes/a.json'

def test_ui_only_read_only_reports():
    from pathlib import Path
    p=Path(__file__).resolve().parents[1]/'pt_asset_tool/ui_static/etervale-readiness.html'
    html=p.read_text()
    assert "textContent=value" in html
    assert 'fetch(\'/api/etervale/readiness\'' in html
