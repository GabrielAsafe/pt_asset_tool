from pathlib import Path
import zipfile

from pt_asset_tool.official_payload_source_locator import (
    _extract_ascii_candidates, _is_tff_name, _scan_binary_archive
)


def test_tff_name_classifier():
    assert _is_tff_name('TfbF01.smd')
    assert _is_tff_name('TfhF36.smd')
    assert _is_tff_name('CtfbF01.smd')
    assert not _is_tff_name('TmbA01.smd')


def test_zip_member_target_detection(tmp_path: Path):
    z = tmp_path / 'patch.upw'
    # ZIP bytes behind an .upw name are a realistic updater-artifact possibility.
    with zipfile.ZipFile(z, 'w', compression=zipfile.ZIP_DEFLATED) as f:
        f.writestr('char/tmABCD/TfbF01.smd', b'SMD Model data Ver 0.62' + b'X'*128)
    row = _scan_binary_archive(z, {'tfbf01.smd'})
    # Structural ZIP detection must work even when suffix is .upw.
    assert any(x['member'].lower().endswith('tfbf01.smd') for x in row['archive_member_hits'])
    assert row['model062_magic_count'] >= 0


def test_updater_string_extraction(tmp_path: Path):
    p = tmp_path / 'zupdate.exe'
    p.write_bytes(b'junk http://patch.priston.example/update/ patch\\00421.upw more')
    r = _extract_ascii_candidates(p)
    assert any('http://patch.priston.example/update/' in x for x in r['urls'])
    assert any(x.lower().endswith('.upw') for x in r['upw_refs'])


def test_overlay_version_and_route():
    root = Path(__file__).resolve().parents[1]
    text = (root/'payload/pt_asset.py').read_text()
    assert 'OVERLAY_VERSION = "0.12.0"' in text
    assert 'official-payload-source-locator' in text
