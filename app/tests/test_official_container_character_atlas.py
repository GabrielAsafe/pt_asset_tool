import pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
PAYLOAD=ROOT/'payload'
sys.path.insert(0,str(PAYLOAD))
from pt_asset_tool.official_container_character_atlas import _scan_refs, _ref_record, _build_summit_index, _strong_character_ref

def test_ascii_utf16_and_noise_filter(tmp_path):
    p=tmp_path/'cdata1'
    p.write_bytes(b'xx char/TmbB01.smd yy image/Sinimage/Items/DropItem/itBC101.smd zz '+ 'char/TmbB02.smd'.encode('utf-16le'))
    refs=_scan_refs(p)
    names={r['ref'] for r in refs}
    assert 'char/TmbB01.smd' in names
    assert 'char/TmbB02.smd' in names
    assert not any(x.startswith('dchar/') for x in names)
    assert _strong_character_ref('char/TmbB01.smd')
    assert not _strong_character_ref('image/Sinimage/Items/DropItem/itBC101.smd')

def test_summit_overlap(tmp_path):
    summit=tmp_path/'client'; (summit/'char').mkdir(parents=True); (summit/'char'/'TmbB01.smd').write_bytes(b'x')
    idx=_build_summit_index(summit)
    r=_ref_record({'ref':'char/TmbB01.smd','encoding':'ASCII','first_offset':3},idx)
    assert r['summit_overlap']=='SUMMIT_EXACT_PATH_REFERENCE'
    r2=_ref_record({'ref':'char/TmbB99.smd','encoding':'ASCII','first_offset':7},idx)
    assert r2['summit_overlap']=='DONOR_REFERENCE_ONLY'
