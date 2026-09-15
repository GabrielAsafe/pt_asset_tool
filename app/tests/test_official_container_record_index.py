from __future__ import annotations

import json
import struct
from pathlib import Path

from pt_asset_tool.official_container_record_index import run


def _copy_writers(project: Path):
    payload = Path(__file__).resolve().parents[1] / 'payload'
    for rel in ('rare_rigid_edit.py','rare_rigid_multivertex.py','rare_rigid_multibone_bridge.py','rare_rigid_normal_bridge.py'):
        dst = project / 'pt_asset_tool' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((payload / 'pt_asset_tool' / rel).read_bytes())


def _prior(project: Path):
    pb = project / 'pt_build'
    pb.mkdir(parents=True, exist_ok=True)
    (pb / 'official_container_entry_recovery_v0960.json').write_text(json.dumps({
        'format':'PT_OFFICIAL_CONTAINER_ENTRY_RECOVERY_V2',
        'status':'PASS','release_version':'0.9.6',
        'client_and_donors_read_only':True,
        'client_corpus_rebaselined_to_current_state':True,
        'summary':{'tmabcd_unique_donor_only_smd_name_count':327,'strict_raw_recovered_count':0},
        'guards':{'certified_writer_hashes_valid':True,'writer_modules_modified':False,'production_policies_modified':False},
        'client_content_baseline':{'content_tree_sha256':'synthetic'},
    }))
    (pb / 'summit_client_content_baseline_v0960.json').write_text(json.dumps({
        'format':'PT_SUMMIT_CLIENT_CONTENT_BASELINE_V1',
        'status':'PASS_READ_ONLY_WINDOW','release_version':'0.9.6',
        'files':{},'file_count':0,'total_bytes':0,'content_tree_sha256':'synthetic',
    }))


def _lha0(name: str, payload: bytes) -> bytes:
    nb = name.encode('latin-1')
    body = bytearray()
    body += b'-lh0-'
    body += struct.pack('<I', len(payload))
    body += struct.pack('<I', len(payload))
    body += struct.pack('<I', 0)  # timestamp
    body += b'\x20'               # attr
    body += b'\x00'               # level 0
    body += bytes([len(nb)])
    body += nb
    body += b'\x00\x00'          # CRC (not interpreted by this audit)
    assert len(body) < 256
    return bytes([len(body), sum(body) & 0xFF]) + bytes(body) + payload


def test_lha_record_mapping_and_body_head_family(tmp_path, monkeypatch):
    project = tmp_path / 'project'; client = tmp_path / 'summit'; donor = tmp_path / 'donor'
    project.mkdir(); client.mkdir(); donor.mkdir(); _copy_writers(project); _prior(project)
    c = donor / 'cdata1'
    c.write_bytes(
        _lha0('char/tmABCD/TfbF01.smd', b'COMPRESSED-BODY') +
        _lha0('char/tmABCD/TfhF01.smd', b'COMPRESSED-HEAD') +
        _lha0('char/tmABCD/TfbA01.smd', b'OLD-BODY')
    )
    monkeypatch.setenv('PT_CLIENT_ROOT', str(client))
    before = c.read_bytes()
    r = run(project, project/'pt_build/record.json', [f'official={donor}'])
    assert r['status'] == 'PASS'
    assert r['summary']['strict_lha_target_mapping_count'] >= 3
    assert r['summary']['complete_body_head_donor_only_family_count'] >= 1
    fams = r['summary']['complete_body_head_donor_only_families']
    f = next(x for x in fams if x['class'] == 'F')
    assert f['body_count'] >= 1 and f['head_count'] >= 1
    assert c.read_bytes() == before
    assert r['decision']['transplant_write_authorized'] is False


def test_overlay_version_and_cli_route_present():
    root = Path(__file__).resolve().parents[1]
    text = (root/'payload/pt_asset.py').read_text()
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'official-container-record-index' in text
