from __future__ import annotations

import struct
from pathlib import Path

import pytest

from pt_asset_tool.object_local import (
    SMD_HEADER, SMD_HEADER_SIZE, SMD_INFO_SIZE, SMD_OBJECT_SIZE,
    O_NPOS, O_NSCALE, O_NODE_NAME, O_POS, O_SCALE, O_Q, O_NROT, O_TM_FRAME_CNT,
    O_TM_ROTATE, O_TM_POS_FRAME,
)
from pt_asset_tool.object_local_writer import patch_existing_object_local_key


def _fixture(path: Path):
    obj_off = SMD_HEADER_SIZE + SMD_INFO_SIZE
    obj_len = SMD_OBJECT_SIZE + 16 + 16  # one POS + one SCALE key
    data = bytearray(obj_off + obj_len)
    data[:len(SMD_HEADER)] = SMD_HEADER
    struct.pack_into('<i', data, 24, 1)
    data[SMD_HEADER_SIZE:SMD_HEADER_SIZE+4] = b'Box\0'
    struct.pack_into('<2i', data, SMD_HEADER_SIZE+32, obj_len, obj_off)
    data[obj_off+O_NODE_NAME:obj_off+O_NODE_NAME+4] = b'Box\0'
    struct.pack_into('<i', data, obj_off+O_NROT, 0)
    struct.pack_into('<i', data, obj_off+O_NPOS, 1)
    struct.pack_into('<i', data, obj_off+O_NSCALE, 1)
    struct.pack_into('<i', data, obj_off+O_TM_FRAME_CNT, 0)
    struct.pack_into('<4f', data, obj_off+O_Q, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into('<3i', data, obj_off+O_SCALE, 256, 256, 256)
    struct.pack_into('<3i', data, obj_off+O_POS, 0, 0, 0)
    arr = obj_off + SMD_OBJECT_SIZE
    struct.pack_into('<i3f', data, arr, 160, 1.0, 2.0, 3.0)
    struct.pack_into('<4i', data, arr+16, 160, 256, 256, 256)
    path.write_bytes(data)


def test_object_local_candidate_patches_existing_position_key_only(tmp_path):
    src=tmp_path/'source.smd'; out=tmp_path/'pt_build'/'out.smd'; _fixture(src)
    before=src.read_bytes()
    result=patch_existing_object_local_key(src,out,object_index=0,channel='pos',key_index=0,values=[4.0,5.0,6.0])
    assert result['status']=='PASS'
    assert result['authorization']=='CANDIDATE_PT_BUILD_ONLY'
    assert result['semantic_after']==pytest.approx([4.0,5.0,6.0])
    assert result['all_non_authorized_bytes_byte_identical'] is True
    assert result['file_size_preserved'] is True
    assert result['production_authorized'] is False
    assert src.read_bytes()==before


def test_object_local_scale_candidate_requires_fixed_grid(tmp_path):
    src=tmp_path/'source.smd'; out=tmp_path/'out.smd'; _fixture(src)
    ok=patch_existing_object_local_key(src,out,object_index=0,channel='scale',key_index=0,values=[1.5,1.0,0.5])
    assert ok['status']=='PASS'
    assert ok['semantic_after']==pytest.approx([1.5,1.0,0.5])
    with pytest.raises(ValueError, match='1/256'):
        patch_existing_object_local_key(src,out,object_index=0,channel='scale',key_index=0,values=[1.0001,1.0,1.0])


def test_object_local_candidate_refuses_unknown_channel(tmp_path):
    src=tmp_path/'source.smd'; out=tmp_path/'out.smd'; _fixture(src)
    with pytest.raises(ValueError, match='ROT, POS or SCALE'):
        patch_existing_object_local_key(src,out,object_index=0,channel='shear',key_index=0,values=[0,0,0])


def test_object_local_writer_corpus_is_explicit_when_fixture_has_no_editable_sample(tmp_path):
    from pt_asset_tool.config import Settings
    from pt_asset_tool.registry import AssetRegistry
    from pt_asset_tool.resolver import ClientResolver
    from pt_asset_tool.object_local_writer import audit_object_local_writer_corpus
    root=Path(__file__).resolve().parents[1]
    client=root.parent/'fixture_client'
    settings=Settings.discover(root,client)
    resolver=ClientResolver(client)
    registry=AssetRegistry(settings.inventory,settings.pairing,resolver=resolver)
    report=audit_object_local_writer_corpus(root,registry,resolver,sample_limit=5)
    assert report['status'] in {'EMPTY','PASS'}
    assert report['client_modified'] is False
    assert report['production_authorized'] is False
    assert report['source_drift_count']==0


def _rotation_fixture(path: Path, *, legacy_affine: bool = False):
    from pt_asset_tool.object_local import quat_to_matrix4_raw, matrix4_mul
    obj_off = SMD_HEADER_SIZE + SMD_INFO_SIZE
    nr = 2
    obj_len = SMD_OBJECT_SIZE + nr * 20 + nr * 64
    data = bytearray(obj_off + obj_len)
    data[:len(SMD_HEADER)] = SMD_HEADER
    struct.pack_into('<i', data, 24, 1)
    data[SMD_HEADER_SIZE:SMD_HEADER_SIZE+4] = b'Rot\0'
    struct.pack_into('<2i', data, SMD_HEADER_SIZE+32, obj_len, obj_off)
    data[obj_off+O_NODE_NAME:obj_off+O_NODE_NAME+4] = b'Rot\0'
    struct.pack_into('<i', data, obj_off+O_NROT, nr)
    struct.pack_into('<i', data, obj_off+O_NPOS, 0)
    struct.pack_into('<i', data, obj_off+O_NSCALE, 0)
    struct.pack_into('<i', data, obj_off+O_TM_FRAME_CNT, 0)
    struct.pack_into('<4f', data, obj_off+O_Q, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into('<3i', data, obj_off+O_SCALE, 256, 256, 256)
    struct.pack_into('<3i', data, obj_off+O_POS, 0, 0, 0)
    q0 = (0.0, 0.0, 0.0, 1.1 if legacy_affine else 1.0)
    q1 = (0.0, 0.0, 0.2588190451, 0.9659258263)
    arr = obj_off + SMD_OBJECT_SIZE
    struct.pack_into('<i4f', data, arr, 0, *q0)
    struct.pack_into('<i4f', data, arr+20, 160, *q1)
    m0 = quat_to_matrix4_raw(q0)
    m1 = matrix4_mul(m0, quat_to_matrix4_raw(q1))
    prev = arr + nr * 20
    for idx, matrix in enumerate((m0, m1)):
        flat = [float(matrix[r][c]) for r in range(4) for c in range(4)]
        struct.pack_into('<16f', data, prev + idx*64, *flat)
    path.write_bytes(data)


def test_object_local_rotation_candidate_rebuilds_tm_prev_rot_suffix(tmp_path):
    from pt_asset_tool.object_local import parse_object_local_smd
    src=tmp_path/'rot.smd'; out=tmp_path/'rot_out.smd'; _rotation_fixture(src)
    before=src.read_bytes()
    result=patch_existing_object_local_key(
        src,out,object_index=0,channel='rot',key_index=1,
        values=[0.0, 0.0, 0.3826834324, 0.9238795325],
    )
    assert result['status']=='PASS'
    assert result['rotation_candidate_writer_authorized'] is True
    assert result['tm_prev_rot_rebuilt_from_key']==1
    assert result['all_non_authorized_bytes_byte_identical'] is True
    parsed=parse_object_local_smd(out, strict_v1=True)
    assert parsed['objects'][0]['rotation_semantics_check']=='PASS'
    assert parsed['objects'][0]['rot_keys'][1]['q_incremental_xyzw'] == pytest.approx([0.0,0.0,0.3826834324,0.9238795325])
    assert src.read_bytes()==before


def test_object_local_rotation_candidate_supports_legacy_affine_raw_chain(tmp_path):
    from pt_asset_tool.object_local import parse_object_local_smd
    src=tmp_path/'legacy.smd'; out=tmp_path/'legacy_out.smd'; _rotation_fixture(src, legacy_affine=True)
    before=parse_object_local_smd(src, strict_v1=True)
    assert before['objects'][0]['legacy_affine_rotation'] is True
    result=patch_existing_object_local_key(
        src,out,object_index=0,channel='ROT',key_index=0,
        values=[0.0, 0.0, 0.0, 1.05],
    )
    assert result['status']=='PASS'
    after=parse_object_local_smd(out, strict_v1=True)
    assert after['objects'][0]['legacy_affine_rotation'] is True
    assert after['objects'][0]['rotation_semantics_check']=='PASS'
    assert result['all_non_authorized_bytes_byte_identical'] is True


def _segmented_position_fixture(path: Path):
    obj_off = SMD_HEADER_SIZE + SMD_INFO_SIZE
    np = 3
    obj_len = SMD_OBJECT_SIZE + np * 16
    data = bytearray(obj_off + obj_len)
    data[:len(SMD_HEADER)] = SMD_HEADER
    struct.pack_into('<i', data, 24, 1)
    data[SMD_HEADER_SIZE:SMD_HEADER_SIZE+4] = b'Seg\0'
    struct.pack_into('<2i', data, SMD_HEADER_SIZE+32, obj_len, obj_off)
    data[obj_off+O_NODE_NAME:obj_off+O_NODE_NAME+4] = b'Seg\0'
    struct.pack_into('<i', data, obj_off+O_NROT, 0)
    struct.pack_into('<i', data, obj_off+O_NPOS, np)
    struct.pack_into('<i', data, obj_off+O_NSCALE, 0)
    struct.pack_into('<i', data, obj_off+O_TM_FRAME_CNT, 1)
    struct.pack_into('<4f', data, obj_off+O_Q, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into('<3i', data, obj_off+O_SCALE, 256, 256, 256)
    struct.pack_into('<3i', data, obj_off+O_POS, 0, 0, 0)
    ident=[256 if r==c else 0 for r in range(4) for c in range(4)]
    struct.pack_into('<16i', data, obj_off+O_TM_ROTATE, *ident)
    # One active position segment [0, 320), starting at key index 0.
    struct.pack_into('<4i', data, obj_off+O_TM_POS_FRAME, 0, 320, 0, 2)
    arr = obj_off + SMD_OBJECT_SIZE
    struct.pack_into('<i3f', data, arr, 0, 0.0, 0.0, 0.0)
    struct.pack_into('<i3f', data, arr+16, 160, 2.0, 0.0, 0.0)
    # Sentinel/following key used by the runtime interval search.
    struct.pack_into('<i3f', data, arr+32, 320, 4.0, 0.0, 0.0)
    path.write_bytes(data)


def test_segmented_object_local_parser_evaluator_and_writer_are_supported(tmp_path):
    from pt_asset_tool.object_local import parse_object_local_smd, absolute_sample
    src=tmp_path/'segmented.smd'; out=tmp_path/'segmented_out.smd'; _segmented_position_fixture(src)
    parsed=parse_object_local_smd(src, strict_v1=True)
    obj=parsed['objects'][0]
    assert obj['segmented_tmframe'] is True
    assert obj['pos_frames']==[{'slot':0,'start':0,'end':320,'pos_num':0,'pos_cnt':2}]
    assert absolute_sample(obj,80)['location'][0] == pytest.approx(1.0)
    assert absolute_sample(obj,400)['location'][0] == pytest.approx(0.0)
    before=src.read_bytes()
    result=patch_existing_object_local_key(src,out,object_index=0,channel='POS',key_index=1,values=[3.0,0.0,0.0])
    assert result['status']=='PASS'
    assert result['segmented_tmframe_preserved'] is True
    after=parse_object_local_smd(out, strict_v1=True)
    assert after['objects'][0]['pos_frames']==obj['pos_frames']
    assert after['objects'][0]['pos_keys'][1]['xyz'][0] == pytest.approx(3.0)
    assert src.read_bytes()==before
