"""Focused regression tests for isolated, data-only tools moved from Summit."""
from __future__ import annotations

import json
from pathlib import Path

from pt_asset_tool import cli
from pt_asset_tool.data_type_tools import FORMAT_SPECS, _base


def _shop_source(tmp_path: Path) -> Path:
    source = tmp_path / 'shops.json'
    source.write_text(json.dumps({
        'schema': 'summit.coin-shop-catalog/v1',
        'shops': {
            'coin': [{'code': 'IT101', 'section': 1, 'price': 20}],
            'time': [{'code': 'IT102', 'section': 2, 'price': 30}],
        },
    }), encoding='utf-8')
    return source


def test_data_types_are_bundled_and_capabilities_are_explicit(capsys):
    assert all((_base() / 'content_port' / s.inspect_script).is_file() for s in FORMAT_SPECS.values() if s.inspect_script)
    assert cli.main(['data-types', 'list', '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) >= 11
    assert all(x['authority'] == 'legacy_summit_only_not_verified_in_etervale' for x in data)
    assert cli.main(['data-types', 'schemas']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 16


def test_coin_catalog_compiles_inspects_and_refuses_overwrite(tmp_path, capsys):
    src = _shop_source(tmp_path)
    args = ['--root', str(tmp_path), 'data-types', 'compile', 'scsp', str(src)]
    assert cli.main(args) == 0
    output = tmp_path / 'pt_build/data_types/compiled/shops.scsp'
    assert output.read_bytes()[:4] == b'SCSP'
    assert (tmp_path / 'pt_build/data_types/compiled/shops.scsp.report.json').is_file()
    original = output.read_bytes()
    assert cli.main(['data-types', 'inspect', str(output)]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    assert cli.main(args) == 2
    assert output.read_bytes() == original


def test_compilation_cannot_target_game_assets(tmp_path, capsys):
    source = _shop_source(tmp_path)
    assets = tmp_path / 'assets'
    assets.mkdir()
    forbidden = assets / 'coin_shop.scsp'
    assert cli.main(['--root', str(tmp_path), 'data-types', 'compile', 'scsp', str(source),
                     '--output', str(forbidden)]) == 2
    assert not forbidden.exists()
    assert 'OUTPUT_MUST_BE_UNDER_PT_BUILD_DATA_TYPES' in capsys.readouterr().err


def test_inspection_rejects_corrupt_pack(tmp_path, capsys):
    src = _shop_source(tmp_path)
    assert cli.main(['--root', str(tmp_path), 'data-types', 'compile', 'scsp', str(src)]) == 0
    pack = tmp_path / 'pt_build/data_types/compiled/shops.scsp'
    contents = bytearray(pack.read_bytes())
    contents[-1] ^= 1
    pack.write_bytes(contents)
    assert cli.main(['data-types', 'inspect', str(pack)]) != 0
    assert 'bad sha' in capsys.readouterr().err


def test_smap_inspection_hash_flag_is_fail_closed(tmp_path, capsys):
    import hashlib
    import struct
    # A structural header is sufficient to test the imported inspector's
    # previously non-fatal checksum reporting behavior.
    header = struct.Struct('<4sHH22I32s')
    body = b'test payload'
    pack = header.pack(b'SMAP', 1, 128, *([0] * 22), hashlib.sha256(body).digest()) + body
    path = tmp_path / 'test.smap'
    path.write_bytes(pack)
    assert cli.main(['data-types', 'inspect', str(path)]) == 0
    damaged = bytearray(pack)
    damaged[-1] ^= 1
    path.write_bytes(damaged)
    assert cli.main(['data-types', 'inspect', str(path)]) == 2
    assert 'SMAP_BODY_SHA256_MISMATCH' in capsys.readouterr().err


def test_ase_inspection_is_read_only_and_rejects_traversal(tmp_path, capsys):
    root = tmp_path / 'assets'
    root.mkdir()
    ase = root / 'mesh.ase'
    ase.write_text('*3DSMAX_ASCIIEXPORT 200\n*GEOMOBJECT {\n  *NODE_NAME "Sample"\n}\n', encoding='latin-1')
    original = ase.read_bytes()
    args = ['data-types', 'ase-inspect', '--asset-root', str(root), '--relative-path', 'mesh.ase']
    assert cli.main(args) == 0
    assert ase.read_bytes() == original
    capsys.readouterr()
    assert cli.main(['data-types', 'ase-inspect', '--asset-root', str(root),
                     '--relative-path', '../outside.ase']) != 0
    assert not any(p.suffix == '.report.json' for p in root.rglob('*'))


def test_schema_validation_rejects_invalid_document(tmp_path, capsys):
    data = tmp_path / 'invalid.json'
    data.write_text('{}', encoding='utf-8')
    assert cli.main(['data-types', 'validate-json', '--schema', 'map_catalog', str(data)]) == 2
    assert 'SchemaValidationError' in capsys.readouterr().err


def test_schema_validation_accepts_valid_minimal_document(tmp_path, capsys):
    data = tmp_path / 'equipment_sets.json'
    data.write_text(json.dumps({'schema': 'summit.equipment-sets/v1',
                                'schema_version': 1, 'sets': []}), encoding='utf-8')
    assert cli.main(['data-types', 'validate-json', '--schema', 'equipment_sets', str(data)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'PASS'


def test_etervale_project_tools_are_discovered_without_copying_csproj(tmp_path, capsys):
    root = tmp_path / 'Etervale-git'
    tool = root / 'tools/PristonTale.AssetDump'
    tool.mkdir(parents=True)
    (tool/'PristonTale.AssetDump.csproj').write_text('<Project />', encoding='utf-8')
    asset = root / 'assets/char/test.smd'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'example')
    assert cli.main(['data-types', 'etervale-tools', '--repo-root', str(root)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert next(r for r in data['tools'] if r['tool'] == 'PristonTale.AssetDump')['exists']
    assert cli.main(['data-types', 'etervale-inspect', '--repo-root', str(root), '--asset', 'char/test.smd']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert not plan['execute']
    assert '--no-build' in plan['command']


def test_etervale_inspector_rejects_asset_escape(tmp_path, capsys):
    root = tmp_path / 'Etervale-git'
    tool = root / 'tools/PristonTale.AssetDump'
    tool.mkdir(parents=True)
    (tool/'PristonTale.AssetDump.csproj').write_text('<Project />', encoding='utf-8')
    (root/'assets').mkdir()
    outside = root / 'private.smd'
    outside.write_bytes(b'private')
    assert cli.main(['data-types', 'etervale-inspect', '--repo-root', str(root), '--asset', '../private.smd']) == 2
    assert 'ASSET_MUST_BE_FILE_UNDER_ETERVALE_ASSETS' in capsys.readouterr().err
