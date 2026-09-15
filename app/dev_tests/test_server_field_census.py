from pathlib import Path
from pt_asset_tool.server_field_census import audit_server_field_bundles


def _w(root: Path, rel: str, size: int = 1):
    p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x" * size)


def test_server_field_bundle_census_resolves_canonical_companions(tmp_path):
    project=tmp_path/'app'; project.mkdir()
    server=tmp_path/'server'; server.mkdir()
    _w(server,'GameServer/Field/forest.spm')
    _w(server,'GameServer/Field/forest.spp',2400)
    _w(server,'GameServer/Field/forest.spc',50400)
    _w(server,'Field/forest/forest.smd')
    r=audit_server_field_bundles(project,server)
    assert r['field_bundle_count']==1
    assert r['resolved_count']==1
    row=r['rows'][0]
    assert row['spp_layout']=='SUMMIT_200x12'
    assert row['spc_layout']=='SUMMIT_100x504'


def test_server_field_bundle_census_marks_legacy_layout_and_ambiguity(tmp_path):
    project=tmp_path/'app'; project.mkdir()
    server=tmp_path/'server'; server.mkdir()
    _w(server,'GameServer/Field/a.spm')
    _w(server,'GameServer/Field/a.spp',600)
    _w(server,'GameServer/Field/a.spc',100)
    _w(server,'Field/x/a.smd')
    _w(server,'Field/y/a.ase')
    r=audit_server_field_bundles(project,server)
    row=r['rows'][0]
    assert row['status']=='REVIEW_LAYOUT_OR_STAGE_AMBIGUITY'
    assert 'SPP_NON_SUMMIT_2400_LAYOUT' in row['reasons']
    assert row['stage_selection_basis']=='UNIQUE_SMD_RUNTIME_PREFERENCE'


def test_server_field_bundle_normalizes_ase_companion_and_prefers_smd(tmp_path):
    project=tmp_path/'app'; project.mkdir()
    server=tmp_path/'server'; server.mkdir()
    _w(server,'gameserver/FIELD/AncientW.ase.spm')
    _w(server,'gameserver/FIELD/AncientW.ase.spp',2400)
    _w(server,'gameserver/FIELD/AncientW.ase.spc',50400)
    _w(server,'FIELD/x/AncientW.ase')
    _w(server,'FIELD/x/AncientW.smd')
    r=audit_server_field_bundles(project,server)
    assert r['field_bundle_count']==1
    assert r['resolved_count']==1
    row=r['rows'][0]
    assert row['basename']=='ancientw'
    assert row['selected_stage'].lower().endswith('ancientw.smd')
    assert row['stage_selection_basis']=='UNIQUE_SMD_RUNTIME_PREFERENCE'
