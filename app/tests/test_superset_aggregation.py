import json
from pathlib import Path

from pt_asset_tool.superset_aggregation import (
    build_client_superset,
    build_server_superset,
    normalize_server_relative,
)


def test_client_superset_stages_missing_and_preserves_variants(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    target = tmp_path / 'target'; target.mkdir()
    official = tmp_path / 'official'; official.mkdir()
    pt = tmp_path / 'pt'; pt.mkdir()

    (target / 'image').mkdir(); (target / 'image' / 'keep.tga').write_bytes(b'target')
    for root, payload in ((official, b'off'), (pt, b'pt')):
        (root / 'image').mkdir()
        (root / 'image' / 'new.tga').write_bytes(payload)
    (official / 'image' / 'keep.tga').write_bytes(b'donor-different')
    (official / 'tool.exe').write_bytes(b'exe')
    (official / 'source.ase').write_bytes(b'ase')

    result = build_client_superset(
        project, target,
        [f'OFFICIAL={official}', f'PT_EU={pt}'],
        materialize=True,
    )
    assert result['status'] == 'PASS'
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['action_counts']['KEEP_TARGET'] == 1
    assert manifest['action_counts']['RECOVER_PREFERRED_VARIANT'] == 1
    assert manifest['action_counts']['EXCLUDE_NON_DEPLOYABLE'] == 1
    assert manifest['action_counts']['ARCHIVE_REFERENCE_ONLY'] == 1
    staged = Path(result['overlay_root']) / 'image' / 'new.tga'
    assert staged.read_bytes() == b'off'
    assert (target / 'image' / 'keep.tga').read_bytes() == b'target'
    assert manifest['target_modified'] is False
    assert Path(result['reports_bundle']).is_file()


def test_server_superset_normalizes_and_excludes_runtime_state(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    target = tmp_path / 'server'; target.mkdir()
    donor = tmp_path / 'donor'; donor.mkdir()

    (donor / 'game-server' / 'GameServer' / 'Field').mkdir(parents=True)
    (donor / 'game-server' / 'GameServer' / 'Field' / 'x.spc').write_bytes(b'spc')
    (donor / 'game-server' / 'LogItemData').mkdir(parents=True)
    (donor / 'game-server' / 'LogItemData' / 'runtime.itm').write_bytes(b'x')
    (donor / 'login-server').mkdir()
    (donor / 'login-server' / 'login.ini').write_bytes(b'login')

    result = build_server_superset(project, target, [f'PT={donor}'], materialize=True)
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['action_counts'].get('RECOVER', 0) == 0
    assert manifest['action_counts']['EXCLUDE_NON_DEPLOYABLE'] == 1
    assert manifest['action_counts']['ARCHIVE_REFERENCE_ONLY'] == 2
    assert not (Path(result['overlay_root']) / 'GameServer' / 'Field' / 'x.spc').exists()
    assert not (Path(result['overlay_root']) / 'LogItemData' / 'runtime.itm').exists()
    assert normalize_server_relative('game-server/A/B.txt')[0] == 'A/B.txt'
    assert normalize_server_relative('login-server/A.txt')[0] is None


def test_client_superset_same_hash_dedupes(tmp_path):
    project = tmp_path / 'app'; project.mkdir()
    target = tmp_path / 'target'; target.mkdir()
    a = tmp_path / 'a'; a.mkdir()
    b = tmp_path / 'b'; b.mkdir()
    for root in (a, b):
        (root / 'sound').mkdir()
        (root / 'sound' / 'same.wav').write_bytes(b'identical')
    result = build_client_superset(project, target, [f'A={a}', f'B={b}'], materialize=True)
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['action_counts']['RECOVER_DEDUPED'] == 1
    assert (Path(result['overlay_root']) / 'sound' / 'same.wav').read_bytes() == b'identical'


def test_combined_summit_superset_emits_small_report_bundle(tmp_path, monkeypatch):
    import zipfile
    import pt_asset_tool.superset_aggregation as sup

    project = tmp_path / 'app'; project.mkdir()
    client = tmp_path / 'client'; client.mkdir()
    server = tmp_path / 'server'; server.mkdir()
    donor_client = tmp_path / 'donor_client'; donor_client.mkdir()
    donor_server = tmp_path / 'donor_server'; donor_server.mkdir()

    (donor_client / 'sound').mkdir()
    (donor_client / 'sound' / 'new.wav').write_bytes(b'wav')
    (donor_server / 'game-server' / 'GameServer' / 'Field').mkdir(parents=True)
    (donor_server / 'game-server' / 'GameServer' / 'Field' / 'new.spc').write_bytes(b'spc')

    def fake_classes(project_root, client_root, **kwargs):
        out = Path(project_root) / 'pt_build' / 'aggregate' / 'player_classes' / 'all'
        out.mkdir(parents=True, exist_ok=True)
        manifest = out / 'manifest.json'
        validation = out / 'validation.json'
        manifest.write_text(json.dumps({
            'format': 'PT_ASSET_AGGREGATION_PLAN_V2',
            'status': 'PASS',
            'rows': [
                {'action': 'RECOVER', 'target_relative_path': 'sound/new.wav', 'logical_path': 'sound/new.wav'}
            ],
        }), encoding='utf-8')
        validation.write_text(json.dumps({'status': 'PASS'}), encoding='utf-8')
        for name in ('provenance.tsv','recover.tsv','variants.tsv','optional_gaps.tsv','conflicts.tsv','missing.tsv'):
            (out / name).write_text('action\tlogical_path\n', encoding='utf-8')
        return {
            'status': 'PASS', 'manifest': str(manifest), 'validation': str(validation),
            'runtime_ready': False, 'core_unresolved_count': 0, 'optional_review_count': 0,
        }

    monkeypatch.setattr(sup, 'build_player_class_aggregation', fake_classes)
    result = sup.build_summit_superset(
        project, client, server,
        source_root=None, reference_source_root=None,
        donor_clients=[f'OFFICIAL={donor_client}'],
        donor_servers=[f'PT_EU_SERVER={donor_server}'],
        materialize=True,
    )
    assert result['status'] == 'PASS'
    assert result['asset_superset_ready'] is True
    assert result['runtime_ready'] is False
    assert result['aggregate_state'] == 'ASSET_SUPERSET_READY_RUNTIME_BLOCKED'
    assert result['class_recovery_coverage']['check'] == 'PASS'
    assert (Path(result['client_overlay_root']) / 'sound' / 'new.wav').is_file()
    assert not (Path(result['server_overlay_root']) / 'GameServer' / 'Field' / 'new.spc').exists()
    bundle = Path(result['reports_bundle'])
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as z:
        names = set(z.namelist())
    assert 'summit/manifest.json' in names
    assert 'summit/validation.json' in names
    assert 'player_classes/manifest.json' in names
    assert 'client_superset/recover.tsv' in names
    assert 'server_superset/recover.tsv' in names
