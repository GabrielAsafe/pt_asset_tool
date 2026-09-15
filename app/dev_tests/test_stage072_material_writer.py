from __future__ import annotations
import struct
from pathlib import Path
from pt_asset_tool.stage072_corpus import DFILE_HEADER_SIZE, STAGE_HEADER_SIZE, MAT_GROUP_SIZE, MATERIAL_SIZE
from pt_asset_tool.stage072_material_writer import locate_stage_materials,rebuild_stage_material_fields,verify_stage_material_candidate

def _stage(path:Path,two_side=0):
    blob=MAT_GROUP_SIZE+MATERIAL_SIZE
    total=DFILE_HEADER_SIZE+STAGE_HEADER_SIZE+blob
    b=bytearray(total); b[:23]=b'SMD Stage data Ver 0.72'
    struct.pack_into('<i',b,24,0); struct.pack_into('<i',b,28,1)
    # Legacy SaveFile offsets exclude the raw smSTAGE3D header; only the delta matters.
    struct.pack_into('<i',b,32,DFILE_HEADER_SIZE); struct.pack_into('<i',b,36,DFILE_HEADER_SIZE+blob)
    start=DFILE_HEADER_SIZE+STAGE_HEADER_SIZE
    struct.pack_into('<i',b,start+8,1)
    raw=start+MAT_GROUP_SIZE
    struct.pack_into('<i',b,raw+0,0); struct.pack_into('<i',b,raw+124,two_side)
    struct.pack_into('<f',b,raw+144,0.0); struct.pack_into('<f',b,raw+148,0.0)
    path.write_bytes(b); return path

def test_stage072_material_candidate_changes_only_allowlisted_bytes(tmp_path):
    src=_stage(tmp_path/'stage.smd')
    layout=locate_stage_materials(src.read_bytes()); assert layout['material_count']==1
    rebuilt,report=rebuild_stage_material_fields(src,material_index=0,edits={'two_side':1})
    assert report['status']=='PASS' and report['edit_observed'] is True
    verify=verify_stage_material_candidate(src.read_bytes(),rebuilt,material_index=0,edits={'two_side':1})
    assert verify['status']=='PASS'; assert verify['diff_outside_authorized_fields']==[]
