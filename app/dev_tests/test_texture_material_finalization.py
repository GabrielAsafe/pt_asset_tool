"""Offline stage certification (not engine certification) and quality witnesses."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from pt_asset_tool import texture_material_pipeline as m
from pt_asset_tool.texture_material_quality import assess, difference_preview


def _input(root: Path, name='Image/Field/stone.png'):
    p=root/name
    p.parent.mkdir(parents=True, exist_ok=True)
    image=Image.new('RGBA',(16,12),(120,50,30,200))
    image.putpixel((4,4),(254,0,0,200))
    image.save(p)
    return p


def _start(tmp_path, maps='from-diffuse'):
    root=tmp_path/'source'
    source=_input(root)
    run=tmp_path/'stage'
    d=m.prepare(root,run,include=[],exact=[],all_=True,denoise='light',maps=maps)
    rec=d['records'][0]
    assert rec['status']=='staged',rec.get('reason')
    decisions=tmp_path/'approval.json'
    decisions.write_text(json.dumps({'format':'PT_MATERIAL_REVIEWS_V1', 'entries':[
        {'source':rec['source'],'output_sha256':rec['output_sha256'],'decision':'approve'}]}))
    return source,run,rec,decisions


def test_quality_inspection_and_no_resize(tmp_path):
    source,run,rec,_=_start(tmp_path)
    q=rec['quality']
    assert 0 <= q['pixel_change_percent'] <= 100
    assert q['alpha_identical']
    assert 0 <= q['rgb_max_absolute_error_255'] <= 255
    assert (run / rec['preview_difference']).exists()
    im=Image.new('RGB',(2,2),(15,15,15))
    assert assess(im,im)['pixel_change_percent']==0
    assert difference_preview(im,im).size==im.size
    with pytest.raises(ValueError):
        assess(im,Image.new('RGB',(3,2)))


def test_export_requires_review_and_is_outside_app(tmp_path):
    source,run,rec,decision=_start(tmp_path)
    review=run/'manifest.json'
    with pytest.raises(ValueError,match='AUDIT_BLOCKED'):
        m.export_approved(review,tmp_path/'blocked')
    assert not (tmp_path/'blocked').exists()
    assert m.import_reviews(review,decision)['offline_candidate_ready']
    exported=m.export_approved(review,tmp_path/'export')
    assert exported['candidate_count']==1
    assert not exported['may_publish_to_client']
    assert not exported['in_game_tested']
    assert (tmp_path/'export'/'candidates'/rec['source']).read_bytes()==(run/rec['output']).read_bytes()
    for entry in exported['files'][0]['maps'].values():
        result=tmp_path/'export'/entry['path']
        assert hashlib.sha256(result.read_bytes()).hexdigest()==entry['sha256']
    assert source.read_bytes()==(tmp_path/'source'/rec['source']).read_bytes()
    with pytest.raises(FileExistsError):
        m.export_approved(review,tmp_path/'export')


def test_changed_source_invalidates_audit_and_approval(tmp_path):
    source,run,rec,decision=_start(tmp_path)
    m.import_reviews(run/'manifest.json',decision)
    source.write_bytes(b'changed')
    issues=m.audit(run/'manifest.json')['issues']
    assert 'SOURCE_CHANGED_SINCE_RUN' in [x['reason'] for x in issues]
    with pytest.raises(ValueError,match='SOURCE_DRIFT'):
        m.import_reviews(run/'manifest.json',decision)
    with pytest.raises(ValueError,match='AUDIT_BLOCKED'):
        m.export_approved(run/'manifest.json',tmp_path/'export')
    assert not (tmp_path/'export').exists()


def test_map_drift_and_failed_run_block_export(tmp_path):
    source,run,rec,decision=_start(tmp_path)
    m.import_reviews(run/'manifest.json',decision)
    mapinfo=next(iter(rec['maps'].values()))
    (run/mapinfo['path']).write_bytes(b'changed')
    result=m.audit(run/'manifest.json')
    assert not result['offline_candidate_ready']
    assert 'MATERIAL_MAP_DRIFT' in [x['reason'] for x in result['issues']]
    with pytest.raises(ValueError, match='AUDIT_BLOCKED'):
        m.export_approved(run/'manifest.json',tmp_path/'export')


def test_failed_stage_cannot_be_treated_complete(tmp_path):
    root=tmp_path/'src'
    _input(root)
    d=m.prepare(root,tmp_path/'stage',include=[],exact=[],all_=True,denoise='ai',maps='off')
    assert d['state']=='COMPLETE_WITH_ERRORS'
    result=m.audit(tmp_path/'stage'/'manifest.json')
    assert not result['offline_candidate_ready']
    assert 'RUN_NOT_SUCCESSFULLY_COMPLETED' in [i['reason'] for i in result['issues']]


def test_cannot_export_inside_source_or_project(tmp_path):
    source,run,rec,decision=_start(tmp_path)
    m.import_reviews(run/'manifest.json',decision)
    with pytest.raises(ValueError,match='DISJOINT'):
        m.export_approved(run/'manifest.json',source.parent/'export')
    with pytest.raises(ValueError,match='DISJOINT'):
        m.export_approved(run/'manifest.json',m.tex.PROJECT_ROOT/'unsafe')
