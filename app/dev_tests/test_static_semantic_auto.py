from __future__ import annotations

from pathlib import Path

from pt_asset_tool.static_semantic_devtest import validate_static_stress_output


def _obj(name: str, *, nv: int = 3, nf: int = 1, block: bytes = b'A'):
    return {
        'name': name,
        'nv': nv,
        'nf': nf,
        'nt': nf,
        'nr': 0,
        'np': 0,
        'ns': 0,
        'phys': False,
        'block': block,
        'faces': [
            {'verts': (0, 1, 2), 'material': 0, 'uv_layers': [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]}
            for _ in range(nf)
        ],
    }


def test_static_stress_validator_accepts_topology_edit_and_preserves_non_targets(tmp_path, monkeypatch):
    src = tmp_path / 'source.smd'; out = tmp_path / 'out.smd'
    src.write_bytes(b'source'); out.write_bytes(b'output')
    source_parsed = {
        'n': 2, 'mat_count': 1, 'mat_region': b'MAT',
        'objects': {'target': _obj('target', block=b'T0'), 'other': _obj('other', block=b'O')},
    }
    output_parsed = {
        'n': 2, 'mat_count': 1, 'mat_region': b'MAT',
        'objects': {'target': _obj('target', nv=4, nf=2, block=b'T1'), 'other': _obj('other', block=b'O')},
    }

    def fake_parse(data: bytes):
        return source_parsed if data == b'source' else output_parsed

    monkeypatch.setattr('pt_asset_tool.static_semantic_devtest.parse_model062_bytes', fake_parse)
    result = validate_static_stress_output(src, out, ['target'])
    assert result['status'] == 'PASS'
    assert result['all_target_edits_observed'] is True
    assert result['topology_change_observed'] is True
    assert result['non_target_changed'] == []
    assert result['production_authorized'] is False
    assert result['client_write_authorized'] is False


def test_static_stress_validator_rejects_non_target_drift(tmp_path, monkeypatch):
    src = tmp_path / 'source.smd'; out = tmp_path / 'out.smd'
    src.write_bytes(b'source'); out.write_bytes(b'output')
    source_parsed = {
        'n': 2, 'mat_count': 1, 'mat_region': b'MAT',
        'objects': {'target': _obj('target', block=b'T0'), 'other': _obj('other', block=b'O0')},
    }
    output_parsed = {
        'n': 2, 'mat_count': 1, 'mat_region': b'MAT',
        'objects': {'target': _obj('target', nv=4, nf=2, block=b'T1'), 'other': _obj('other', block=b'O1')},
    }
    monkeypatch.setattr(
        'pt_asset_tool.static_semantic_devtest.parse_model062_bytes',
        lambda data: source_parsed if data == b'source' else output_parsed,
    )
    result = validate_static_stress_output(src, out, ['target'])
    assert result['status'] == 'FAIL'
    assert result['non_target_changed'] == ['other']
    assert 'NON_TARGET_BLOCK_CHANGED' in result['errors']


def test_static_physical_corpus_requires_every_asset_to_parse_and_match_inventory(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pt_asset_tool.static_semantic_devtest import audit_model062_static_physical_corpus

    good = SimpleNamespace(
        asset_id='A1', primary_path='Items/good.smd', family='SMD_MODEL_062_STATIC', category='WEAPON_ITEM',
        object_count=1, total_vertices=3, total_faces=1, material_count=1,
        source_record={'total_texlinks': 1},
    )
    bad = SimpleNamespace(
        asset_id='A2', primary_path='Effect/bad.smd', family='SMD_MODEL_062_STATIC', category='EFFECT',
        object_count=1, total_vertices=3, total_faces=1, material_count=1,
        source_record={'total_texlinks': 1},
    )
    registry = SimpleNamespace(assets=[good, bad])
    paths = {}
    for asset in (good, bad):
        p = tmp_path / (asset.asset_id + '.smd'); p.write_bytes(asset.asset_id.encode()); paths[asset.primary_path] = p
    resolver = SimpleNamespace(resolve=lambda logical, required=True: paths[logical])

    parsed_good = {
        'n': 1, 'mat_count': 1,
        'objects': {'obj': {'name':'obj','nv':3,'nf':1,'nt':1,'nr':0,'np':0,'ns':0,'phys':False}},
    }
    parsed_bad = {
        'n': 1, 'mat_count': 1,
        'objects': {'obj': {'name':'obj','nv':4,'nf':1,'nt':1,'nr':0,'np':0,'ns':0,'phys':False}},
    }
    monkeypatch.setattr(
        'pt_asset_tool.static_semantic_devtest.parse_model062_bytes',
        lambda data: parsed_good if data == b'A1' else parsed_bad,
    )
    result = audit_model062_static_physical_corpus(registry, resolver)
    assert result['status'] == 'FAIL'
    assert result['asset_count'] == 2
    assert result['failure_count'] == 1
    assert result['by_domain']['WEAPON_ITEM']['status'] == 'PASS'
    assert result['by_domain']['EFFECT']['status'] == 'FAIL'
    assert result['pass_domains'] == ['WEAPON_ITEM']
