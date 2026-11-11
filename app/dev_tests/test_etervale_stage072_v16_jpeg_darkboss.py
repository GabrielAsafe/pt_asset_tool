"""V16: JFIF-misnamed BMP tooling copy + exact-source hTexture review.

All fixtures are artificial; actual pilai/dark_boss remain for user Blender QA.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest
from PIL import Image

from pt_asset_tool.stage072_preview_jpeg import convert_jfif_bmp_preview, is_jfif_in_bmp
from pt_asset_tool.texture_overlay import prepare_texture_overlay, classify_stage072_texture_transport_failures
from pt_asset_tool.stage072_corpus import parse_stage072, DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, STAGE_VERTEX_SIZE, STAGE_FACE_SIZE
from pt_asset_tool.stage072_compiler import compile_stage072
from pt_asset_tool import stage072_source_exceptions as ex


def jpeg_fixture(tmp_path: Path):
    path = tmp_path / 'assets/Field/forever-fall/mo_g_012_01.bmp'
    path.parent.mkdir(parents=True)
    image = Image.new('RGB', (12, 7))
    image.putdata([(i * 5 % 256, i * 12 % 256, i * 19 % 256) for i in range(84)])
    image.save(path, format='JPEG', quality=90)
    assert is_jfif_in_bmp(path.read_bytes())
    return path


def test_jfif_bmp_extension_converts_to_true_bmp_only_in_overlay(tmp_path):
    src = jpeg_fixture(tmp_path)
    before = src.read_bytes()
    out = tmp_path/'staging/Field/forever-fall/mo_g_012_01.bmp'
    result = convert_jfif_bmp_preview(src, out)
    assert src.read_bytes() == before
    assert out.read_bytes().startswith(b'BM')
    assert result['source_format'] == 'JPEG_JFIF_MISNAMED_BMP'
    assert result['pixel_roundtrip_exact'] is True
    with Image.open(src) as original, Image.open(out) as copy:
        assert original.convert('RGB').tobytes() == copy.convert('RGB').tobytes()


def test_jfif_overlay_is_ready_and_not_wrongly_decrypted_as_protected_bmp(tmp_path):
    src=jpeg_fixture(tmp_path)
    before=src.read_bytes()
    class Resolver:
        def resolve(self, logical):
            if logical.replace('\\', '/').casefold() != 'field/forever-fall/mo_g_012_01.bmp':
                raise FileNotFoundError(logical)
            return src
    asset=SimpleNamespace(asset_id='SAMPLE', primary_path='Field/forever-fall/pilai.smd',
                          kind='SMD_STAGE_072',textures=['field/forever-fall/mo_g_012_01.bmp'],runtime_path_aliases={})
    overlay, report=prepare_texture_overlay(asset=asset,resolver=Resolver(),root=tmp_path,work=tmp_path/'work')
    row=report['entries'][0]
    assert row['status']=='JPEG_IN_BMP_PREVIEW_CONVERTED'
    assert row['source_sha256']==hashlib.sha256(before).hexdigest()
    assert row['preview_only'] is True
    assert classify_stage072_texture_transport_failures(report)['hard_preparation_failures']==[]
    assert (overlay/'field/forever-fall/mo_g_012_01.bmp').read_bytes()[:2]==b'BM'
    assert src.read_bytes()==before


def test_corrupt_jpeg_fails_closed_and_does_not_create_preview(tmp_path):
    src=jpeg_fixture(tmp_path)
    original=src.read_bytes()
    src.write_bytes(original[:150])
    dst=tmp_path/'converted.bmp'
    with pytest.raises(Exception):
        convert_jfif_bmp_preview(src,dst)
    assert not dst.exists()
    assert src.read_bytes()==original[:150]


def test_non_jfif_or_fake_bmp_does_not_use_jpeg_exception(tmp_path):
    src=tmp_path/'input.bmp';dst=tmp_path/'out.bmp'
    for content in (b'BM'+b'\0'*100,b'\xff\xd8not_jfif',b'\x89PNG\r\n\x1a\n'):
        src.write_bytes(content)
        with pytest.raises(ValueError,match='NOT_JPEG_JFIF'):
            convert_jfif_bmp_preview(src,dst)
        assert not dst.exists()


def fixture_stage(tmp_path):
    stage={
        'materials':[{'textures':['field/boss/a_gi01.BMP']}],
        'vertices':[[0,0,0],[64,0,0],[0,0,64]],
        'faces':[{'vertices':[0,2,1],'material':0,'uv_layers':[[[0,0],[0,0],[0,0]]]}],
        'lights':[],
    }
    binary,meta=compile_stage072(stage)
    file=tmp_path/'Field/Boss/dark_boss.smd';file.parent.mkdir(parents=True)
    file.write_bytes(binary)
    initial=parse_stage072(file,include_payload=True)
    assert initial['full_parse']=='PASS'
    assert initial['payload']['texlinks'][0]['hTexture']!=0
    head=initial['file_header']
    materials_size=head['First_ObjInfoPoint']-head['MatFilePoint']
    offset=(DFILE_HEADER_SIZE+STAGE_HEADER_SIZE+materials_size+
            initial['counts']['vertices']*STAGE_VERTEX_SIZE+initial['counts']['faces']*STAGE_FACE_SIZE)
    return file,offset


def test_exact_sha_zero_handle_zero_uv_can_be_previewed_but_review_required(tmp_path,monkeypatch):
    file,offset=fixture_stage(tmp_path)
    binary=bytearray(file.read_bytes());struct.pack_into('<I',binary,offset+24,0)
    file.write_bytes(binary)
    assert parse_stage072(file)['full_parse']=='FAIL'
    monkeypatch.setattr(ex,'DARK_BOSS_SOURCE_SHA256',hashlib.sha256(binary).hexdigest())
    result=parse_stage072(file,include_payload=True)
    assert result['full_parse']=='PASS'
    assert result['source_exact_null_handle_review_count']==1
    assert result['checks']['htexture_stage_mapping']=='PASS_WITH_SOURCE_EXACT_REVIEW'
    assert result['payload']['texlinks'][0]['hTexture']==0
    assert result['source_exact_null_handle_review_sample'][0]['rule']==ex.RULE_ID
    from pt_asset_tool.stage072_batch_audit import audit_map
    class FakeResolver:
        def resolve(self,logical):return tmp_path/'texture-placeholder.bmp'
    row=audit_map(tmp_path,'Field/Boss/dark_boss.smd',FakeResolver())
    assert row['parse']=='PASS'
    assert row['source_exact_null_handle_review_count']==1
    assert row['status']=='REVIEW_REQUIRED'  # Never a false visual/runtime PASS


def test_source_exception_rejects_nonzero_uv_and_other_hash(tmp_path,monkeypatch):
    file,offset=fixture_stage(tmp_path)
    b=bytearray(file.read_bytes());struct.pack_into('<I',b,offset+24,0)
    file.write_bytes(b)
    assert parse_stage072(file)['full_parse']=='FAIL'
    monkeypatch.setattr(ex,'DARK_BOSS_SOURCE_SHA256',hashlib.sha256(b).hexdigest())
    assert parse_stage072(file)['full_parse']=='PASS'
    struct.pack_into('<f',b,offset,0.25)
    file.write_bytes(b)
    monkeypatch.setattr(ex,'DARK_BOSS_SOURCE_SHA256',hashlib.sha256(b).hexdigest())
    assert parse_stage072(file)['full_parse']=='FAIL'
    assert parse_stage072(file)['errors']['htexture_mapping']


def test_exception_is_bound_to_material_depth_and_zero_uv():
    b=dict(source_sha256=ex.DARK_BOSS_SOURCE_SHA256,material_id=0,
           texture_count=1,animation_count=0,chain_length=1,stage_index=0,
           htexture=0,u=(0.0,0.0,0.0),v=(0.0,0.0,0.0))
    assert ex.is_proven_null_zero_uv_preview(**b)
    for changes in (dict(material_id=1),dict(texture_count=2),dict(chain_length=2),
                    dict(animation_count=1),dict(htexture=1),dict(u=(0.25,0.0,0.0)),
                    dict(source_sha256='0'*64)):
        assert not ex.is_proven_null_zero_uv_preview(**{**b,**changes})
