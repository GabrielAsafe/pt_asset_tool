"""Regression: real texture resolution rules and truthful P1 closure evidence."""
from __future__ import annotations
import json
import pathlib
import struct
import pytest

from pt_asset_tool.etervale_p1_full import (
    resolve_texture, field_report, build_index, RUNTIME_FALLBACK_EXTENSIONS,
    IMG_SUFFIXES, DEFAULT_MODELS, DEFAULT_FIELDS, FORMAT,
)
from pt_asset_tool.etervale_p1_closure import inspect
from pt_asset_tool.etervale_ui_readiness import board


@pytest.fixture
def small_assets(tmp_path):
    assets=tmp_path/'assets'
    stage=assets/'Field'/'Ricarten'/'village-2.smd'
    stage.parent.mkdir(parents=True)
    stage.write_bytes(b'smd')
    (stage.parent/'Map.TGA').write_bytes(b'TGA')
    (assets/'Elsewhere').mkdir()
    (assets/'Elsewhere'/'unrelated.bmp').write_bytes(b'BMP')
    return assets,stage


def test_same_dir_exact(small_assets):
    assets,stage=small_assets
    assert resolve_texture(stage,'Map.TGA',assets,{})['state']=='PRESENT_ADJACENT'


def test_windows_casefold(small_assets):
    assets,stage=small_assets
    result=resolve_texture(stage,r'map.tga',assets,{})
    assert result['state']=='PRESENT_ADJACENT'
    assert result['case']=='CASEFOLD_UNIQUE'


def test_serialized_game_relative_reference_is_basename_in_csharp(small_assets):
    assets,stage=small_assets
    # PristonSmdReader BaseName() erases legacy field\ricarten prefixes.
    result=resolve_texture(stage,r'field\ricarten\map.tga',assets,{})
    assert result['state']=='PRESENT_ADJACENT'
    assert result['resolution']=='CSHARP_BASENAME'


def test_runtime_fallback(small_assets):
    assets,stage=small_assets
    result=resolve_texture(stage,'MAP.bmp',assets,{})
    assert result['state']=='PRESENT_RUNTIME_EXTENSION_FALLBACK'
    assert result['resolved_extension']=='.tga'


def test_fallback_is_not_global(small_assets):
    assets,stage=small_assets
    index=build_index(assets)
    result=resolve_texture(stage,'unrelated.bmp',assets,index)
    assert result['state']=='MISSING_ADJACENT'
    assert result['global_candidate_count']==1


@pytest.mark.parametrize('bad',[r'..\hello.bmp','../hello.bmp','/etc/passwd','C:/temp/map.bmp',
                                'mask.txt','',r'.././attack.tga'])
def test_unsafe_references_not_resolved(small_assets,bad):
    assets,stage=small_assets
    assert resolve_texture(stage,bad,assets,{})['state'] not in ('PRESENT_ADJACENT','PRESENT_RUNTIME_EXTENSION_FALLBACK')


def test_fallback_matches_csharp_loader_contract():
    assert RUNTIME_FALLBACK_EXTENSIONS==('.bmp','.tga','.jpg','.jpeg')
    assert '.tga' in IMG_SUFFIXES


def test_field_shape_spc(small_assets):
    assets,_=small_assets
    f=assets/'GameServer'/'Field'/'sample.spc'
    f.parent.mkdir(parents=True)
    raw=bytearray(50400)
    struct.pack_into('<i',raw,4,1)
    f.write_bytes(raw)
    result=field_report(f,assets)
    assert result['status']=='PASS'
    assert result['active_csharp_rows']==1


def test_field_outside_gameserver(small_assets):
    assets,stage=small_assets
    with pytest.raises(ValueError,match='OUTSIDE_GAMESERVER'):
        field_report(stage,assets)


def sample_evidence(tmp_path,*,missing=0,acknowledged=0,readers=True,import_ok=True):
    work=tmp_path/'pt_build'/'etervale'
    folder=work/'p1_full'
    folder.mkdir(parents=True)
    # No files are forged here: a fixture tests only the *classification logic*.
    assets=[]
    for kind,ext,relative in [('STAGE_072','.smd','Field/Ricarten/stage.smd'),
                               ('MODEL_062','.smd','char/a/model.smd'),
                               (None,'.smb','char/a/bone.smb'),
                               (None,'.inx','char/a/model.inx'),
                               (None,'.tga','char/a/skin.tga')]:
        is_image=ext=='.tga'
        assets.append({'path':relative,'kind':kind,
                       'native_reader':{'status':'READER_ACCEPTED' if readers else 'READER_FAILED',
                                        'image_pixels_decoded': True if is_image else None}})
    rows=[{'path':x,'status':'PASS'} for x in DEFAULT_FIELDS]
    obj={'format':FORMAT,'status':'P1_AUTOMATED_GATES_PASSED_RUNTIME_PENDING',
         'game_assets_modified':False,'assets':assets,
         'fields':rows,'field_structural_failures':[],
         'effects':[{'path':'effects/sample.part','status':'STATIC_PART_NONEMPTY_NOT_RENDER_CERTIFIED'}],
         'texture_references':[{'reference':'ok.tga'}],
         'missing_unacknowledged':[{'reference':'missing.bmp'}]*missing,
         'acknowledged_unresolved':[{'reference':'known.bmp'}]*acknowledged,
         'field_native_import':({'status':'NATIVE_WORLDIMPORT_DISPOSABLE_SQLITE','field_rows_in_catalog':55}
                                if import_ok else {'status':'NOT_RUN'})}
    (folder/'evidence.json').write_text(json.dumps(obj),encoding='utf-8')
    return work


def test_closure_all_offline_gates_pass_but_runtime_pending(tmp_path):
    work=sample_evidence(tmp_path)
    result=inspect(work)
    assert result['status']=='P1_AUTOMATED_GATES_PASSED_RUNTIME_REVIEW_PENDING'
    assert result['runtime_visual']=='NOT_CERTIFIED'
    assert all(g['status'].startswith('PASS') for g in result['gates'].values())


@pytest.mark.parametrize('change',[(1,0,True,True),(0,1,True,True),(0,0,False,True),(0,0,True,False)])
def test_closure_refuses_missing_runtime_data(tmp_path,change):
    work=sample_evidence(tmp_path,missing=change[0],acknowledged=change[1],
                         readers=change[2],import_ok=change[3])
    result=inspect(work)
    assert result['status']=='P1_EVIDENCE_INCOMPLETE'


def test_closure_requires_report(tmp_path):
    assert inspect(tmp_path/'empty')['status']=='P1_EVIDENCE_INCOMPLETE'


def test_ui_shows_p1_as_evidence_not_execution(tmp_path):
    work=sample_evidence(tmp_path)
    data=board(work.parent)
    ids={i['id'] for i in data['items']}
    assert 'p1_closure' in ids
    assert data['status']=='READ_ONLY'
    assert data['game_assets_modified'] is False


def test_user_corpus_defaults_have_stage_model_smb_inx_and_fields():
    assert len(DEFAULT_MODELS)>=5
    assert any(p.endswith('village-2.smd') for p in DEFAULT_MODELS)
    assert any(p.endswith('.smb') for p in DEFAULT_MODELS)
    assert any(p.endswith('.inx') for p in DEFAULT_MODELS)
    assert {pathlib.PurePosixPath(p).suffix for p in DEFAULT_FIELDS}=={'.spm','.spp','.spc'}


def test_closure_requires_part_evidence(tmp_path):
    work=sample_evidence(tmp_path)
    p=work/'p1_full'/'evidence.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    data['effects']=[]
    p.write_text(json.dumps(data),encoding='utf-8')
    assert inspect(work)['status']=='P1_EVIDENCE_INCOMPLETE'
