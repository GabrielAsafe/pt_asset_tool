from __future__ import annotations
import json, mmap, struct
from pathlib import Path

from pt_asset_tool.official_container_entry_recovery import _infer_model062_length, run

SH,SI,SO=556,40,2236
SV=24
O_PHYS,O_NV,O_NF,O_NT,O_NR,O_NP,O_NS=16,84,88,92,684,688,692


def _smd_bytes(bone='Bip01 Head', name='BodyNew'):
    off=SH+SI
    nv=1
    length=SO+SV+32
    b=bytearray(off+length)
    b[:23]=b'SMD Model data Ver 0.62'
    struct.pack_into('<iiii',b,24,1,0,off,off)  # obj_count, mat_count, mat_file, first_obj
    b[SH:SH+len(name)]=name.encode()
    struct.pack_into('<ii',b,SH+32,length,off)
    struct.pack_into('<I',b,off+O_PHYS,1)
    struct.pack_into('<iiiiii',b,off+O_NV,nv,0,0,0,0,0)
    b[off+172:off+172+len(name)]=name.encode()
    phys=off+SO+SV
    b[phys:phys+len(bone)]=bone.encode()
    return bytes(b)


def _copy_writers(project:Path):
    payload=Path(__file__).resolve().parents[1]/'payload'
    for rel in ('rare_rigid_edit.py','rare_rigid_multivertex.py','rare_rigid_multibone_bridge.py','rare_rigid_normal_bridge.py'):
        dst=project/'pt_asset_tool'/rel; dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_bytes((payload/'pt_asset_tool'/rel).read_bytes())


def _prior(project:Path):
    p=project/'pt_build/official_container_character_atlas_v0940.json'; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({
        'format':'PT_OFFICIAL_CONTAINER_CHARACTER_REFERENCE_ATLAS_V1','status':'PASS','release_version':'0.9.4',
        'client_and_donors_read_only':True,
        'summary':{'strong_character_reference_count':10,'strong_character_donor_only_count':4},
        'guards':{'certified_writer_hashes_valid':True,'writer_modules_modified':False,'production_policies_modified':False},
    }))


def test_infer_embedded_model_length(tmp_path):
    blob=_smd_bytes(); p=tmp_path/'x.bin'; prefix=b'INDEX\0'; p.write_bytes(prefix+blob+b'TAIL')
    with p.open('rb') as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try:
            n,err=_infer_model062_length(mm,len(prefix))
        finally: mm.close()
    assert err is None and n==len(blob)


def test_read_only_strict_recovery_from_cdata(tmp_path, monkeypatch):
    project=tmp_path/'project'; client=tmp_path/'summit'; donor=tmp_path/'donor'
    project.mkdir(); client.mkdir(); donor.mkdir(); _copy_writers(project); _prior(project)
    ref=b'char/tmABCD/TmbX99.smd\0'
    blob=_smd_bytes()
    c=donor/'cdata1'; c.write_bytes(b'HEAD'+ref+b'\0'*32+blob+b'END')
    monkeypatch.setenv('PT_CLIENT_ROOT',str(client))
    before=c.read_bytes()
    out=project/'pt_build/recovery.json'
    r=run(project,out,[f'official={donor}'])
    assert r['status']=='PASS'
    assert r['summary']['strict_raw_recovered_count']==1
    assert r['donors'][0]['strict_recovered_count']==1
    rr=r['donors'][0]['strict_recovered'][0]
    assert rr['ref']=='char/tmABCD/TmbX99.smd'
    recovered=Path(rr['recovered_path'])
    assert recovered.read_bytes()==blob
    assert c.read_bytes()==before
    assert r['decision']['transplant_write_authorized'] is False


def test_client_metadata_only_change_is_not_misclassified_as_content_write(tmp_path, monkeypatch):
    import os
    import pt_asset_tool.official_container_entry_recovery as mod
    project=tmp_path/'project'; client=tmp_path/'summit'; donor=tmp_path/'donor'
    project.mkdir(); client.mkdir(); donor.mkdir(); _copy_writers(project); _prior(project)
    client_file=client/'stable.bin'; client_file.write_bytes(b'UNCHANGED')
    ref=b'char/tmABCD/TmbX99.smd\0'; blob=_smd_bytes()
    (donor/'cdata1').write_bytes(b'HEAD'+ref+b'\0'*32+blob+b'END')
    monkeypatch.setenv('PT_CLIENT_ROOT',str(client))
    orig=mod._scan_donor
    def wrapped(*args, **kwargs):
        result=orig(*args, **kwargs)
        st=client_file.stat()
        os.utime(client_file, ns=(st.st_atime_ns, st.st_mtime_ns+1_000_000))
        return result
    monkeypatch.setattr(mod,'_scan_donor',wrapped)
    r=mod.run(project,project/'pt_build/recovery.json',[f'official={donor}'])
    assert r['status']=='PASS'
    assert 'stable.bin' in r['client_read_only_window']['metadata_only_changes']
    assert r['client_read_only_window']['content_changed_during_audit']==[]
    assert r['client_content_baseline']['file_count']==1


def test_client_same_size_content_change_still_fails_closed(tmp_path, monkeypatch):
    import pt_asset_tool.official_container_entry_recovery as mod
    project=tmp_path/'project'; client=tmp_path/'summit'; donor=tmp_path/'donor'
    project.mkdir(); client.mkdir(); donor.mkdir(); _copy_writers(project); _prior(project)
    client_file=client/'stable.bin'; client_file.write_bytes(b'AAAA')
    ref=b'char/tmABCD/TmbX99.smd\0'; blob=_smd_bytes()
    (donor/'cdata1').write_bytes(b'HEAD'+ref+b'\0'*32+blob+b'END')
    monkeypatch.setenv('PT_CLIENT_ROOT',str(client))
    orig=mod._scan_donor
    def wrapped(*args, **kwargs):
        result=orig(*args, **kwargs)
        client_file.write_bytes(b'BBBB')
        return result
    monkeypatch.setattr(mod,'_scan_donor',wrapped)
    try:
        mod.run(project,project/'pt_build/recovery.json',[f'official={donor}'])
    except RuntimeError as exc:
        assert 'SUMMIT_CLIENT_CONTENT_CHANGED_DURING_READ_ONLY_ENTRY_RECOVERY' in str(exc)
    else:
        raise AssertionError('same-size content change must fail closed')
