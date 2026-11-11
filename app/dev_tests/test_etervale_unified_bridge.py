"""Regression tests for the additive Etervale C# bridge (no real game/dotnet needed)."""
from __future__ import annotations

import json
import pathlib
import struct

import pytest

from pt_asset_tool import cli, etervale_integration as bridge
from pt_asset_tool.app_config import (
    configured_etervale_root, save_etervale_root, clear_etervale_root,
    save_client_root, save_server_root, resolve_client_root, resolve_server_root,
)


def _project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / 'Etervale-git'
    (root / 'assets/GameServer').mkdir(parents=True)
    for name in ('Client', 'Server', 'Shared', 'Persistence', 'tools/PristonTale.GltfExport',
                 'tools/PristonTale.AssetDump'):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / 'PristonTale.sln').write_text('', encoding='utf-8')
    for name in ('AssetDump', 'GltfExport'):
        tool = root / 'tools' / ('PristonTale.' + name) / ('PristonTale.' + name + '.csproj')
        tool.write_text('<Project></Project>', encoding='utf-8')
    (root / 'Client/example.cs').write_text(
        'var reader = new PristonSmdReader(); // .smd\n', encoding='utf-8')
    (root / 'Shared/shared.cs').write_text('var index = new PristonInxReader();\n', encoding='utf-8')
    (root / 'assets/char').mkdir()
    (root / 'assets/char/test.smd').write_bytes(b'SMD Model data Ver 0.62\x00')
    return root


def test_unified_config_resolves_physical_roots_but_retains_previous_values(tmp_path, monkeypatch):
    monkeypatch.delenv('PT_CLIENT_ROOT', raising=False)
    monkeypatch.delenv('PT_SERVER_ROOT', raising=False)
    monkeypatch.delenv('PT_ETERVALE_ROOT', raising=False)
    game = _project(tmp_path)
    app = tmp_path / 'assetTool/app'
    app.mkdir(parents=True)
    old_client = tmp_path / 'old-client'; old_server = tmp_path / 'old-server'
    old_client.mkdir(); old_server.mkdir()
    save_client_root(app, old_client)
    save_server_root(app, old_server)
    save_etervale_root(app, game)
    assert configured_etervale_root(app) == game
    assert resolve_client_root(app) == (game / 'assets', 'ETERVALE_UNIFIED_ASSETS')
    assert resolve_server_root(app) == (game / 'assets/GameServer', 'ETERVALE_UNIFIED_GAMESERVER')
    clear_etervale_root(app)
    assert resolve_client_root(app)[0] == old_client
    assert resolve_server_root(app)[0] == old_server


def test_unified_config_rejects_non_project(tmp_path):
    app = tmp_path / 'app'; app.mkdir()
    not_game = tmp_path / 'not-game'; not_game.mkdir()
    with pytest.raises(ValueError, match='NOT_ETERVALE_CHECKOUT'):
        save_etervale_root(app, not_game)
    assert not (app / 'pt_build/state/pt_asset_app_config.json').exists()


def test_etervale_status_declares_tool_separation(tmp_path, capsys):
    game = _project(tmp_path)
    assert cli.main(['etervale', 'status', '--repo-root', str(game)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'READY_TO_VALIDATE'
    assert report['roles']['assets']['path'] == str(game / 'assets')
    assert report['roles']['server_data']['path'] == str(game / 'assets/GameServer')
    assert 'NOT_ESTABLISHED' in report['glb_runtime_loading']


def test_csharp_source_audit_does_not_rely_on_cpp_scanner(tmp_path, capsys):
    game = _project(tmp_path)
    assert cli.main(['etervale', 'source-audit', '--repo-root', str(game)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['files_by_tree']['Client'] == 1
    assert report['files_by_tree']['Shared'] == 1
    assert report['textual_markers']['PristonSmdReader']['occurrences'] == 1
    assert report['textual_markers']['PristonInxReader']['occurrences'] == 1
    assert report['legacy_contract_scanner'] == 'UNMODIFIED_C_CPP_ONLY'
    assert 'TEXTUAL_CENSUS' in report['proof_level']


def test_validation_plan_does_not_write_game_assets(tmp_path, capsys):
    game = _project(tmp_path)
    before = (game / 'assets/char/test.smd').read_bytes()
    assert cli.main(['etervale', 'validate', '--repo-root', str(game),
                     '--asset', 'char/test.smd']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'PLANNED_NOT_EXECUTED'
    assert output['command'][-1] == str(game / 'assets/char/test.smd')
    assert before == (game / 'assets/char/test.smd').read_bytes()


def test_validation_rejects_traversal_and_symlink_escape(tmp_path, capsys):
    game = _project(tmp_path)
    secret = game / 'private.smd'
    secret.write_bytes(b'private')
    assert cli.main(['etervale', 'validate', '--repo-root', str(game),
                     '--asset', '../private.smd']) == 2
    capsys.readouterr()
    (game / 'assets/char/evil.smd').symlink_to(secret)
    assert cli.main(['etervale', 'validate', '--repo-root', str(game),
                     '--asset', 'char/evil.smd']) == 2
    assert 'ASSET_OUTSIDE_ETERVALE_ASSETS' in capsys.readouterr().err


def test_glb_plan_stages_only_under_asset_tool(tmp_path, capsys):
    game = _project(tmp_path)
    assert cli.main(['etervale', 'export-glb', '--repo-root', str(game),
                     '--asset', 'char/test.smd', '--output', 'glb/example.glb']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'PLANNED_NOT_EXECUTED'
    assert report['output'].endswith('/pt_build/etervale/glb/example.glb')
    assert cli.main(['etervale', 'export-glb', '--repo-root', str(game),
                     '--asset', 'char/test.smd', '--output', '../out.glb']) == 2
    assert 'OUTPUT_MUST_BE_RELATIVE' in capsys.readouterr().err


def test_candidate_input_requires_private_pt_build(tmp_path, capsys):
    game = _project(tmp_path)
    assert cli.main(['etervale', 'validate', '--repo-root', str(game),
                     '--candidate', str(game / 'assets/char/test.smd')]) == 2
    assert 'CANDIDATE_MUST_BE_UNDER_ASSET_TOOL_PT_BUILD' in capsys.readouterr().err


def test_execute_mock_csharp_inspector_and_glb_export(tmp_path, capsys, monkeypatch):
    game = _project(tmp_path)
    private = tmp_path / 'app/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    dotnet = bin_dir / 'dotnet'
    dotnet.write_text('''#!/usr/bin/env python3
import pathlib, struct, sys
args = sys.argv[1:]
if 'GltfExport' in ' '.join(args):
    dest = pathlib.Path(args[args.index('--') + 2])
    payload = b'\\x20' * 8
    dest.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(payload)) + payload)
else:
    print('mock C# reader accepted the source')
''', encoding='utf-8')
    dotnet.chmod(0o755)
    import os
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    args = ['--repo-root', str(game), '--asset', 'char/test.smd', '--execute']
    assert cli.main(['etervale', 'validate', *args]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info['status'] == 'READER_ACCEPTED'
    assert pathlib.Path(info['report_file']).is_file()
    assert cli.main(['etervale', 'export-glb', *args, '--output', 'glb/proof.glb']) == 0
    info = json.loads(capsys.readouterr().out)
    assert info['status'] == 'EXPORTED_NOT_RUNTIME_CERTIFIED'
    assert info['valid_glb_v2_container']
    assert pathlib.Path(info['output']).is_file()
    assert pathlib.Path(info['report_file']).is_file()


def test_glb_rejects_unsupported_input(tmp_path, capsys):
    game = _project(tmp_path)
    (game / 'assets/char/example.bmp').write_bytes(b'ex')
    assert cli.main(['etervale', 'export-glb', '--repo-root', str(game),
                     '--asset', 'char/example.bmp']) == 2
    assert 'ASSET_UNSUPPORTED_EXTENSION' in capsys.readouterr().err


def test_batch_plans_only_manifested_private_candidates(tmp_path, capsys, monkeypatch):
    game = _project(tmp_path)
    private = tmp_path / 'app/pt_build'; private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    (private / 'outputs').mkdir()
    (private / 'outputs/new.smd').write_bytes(b'SMD Model data Ver 0.62')
    manifest = private / 'inputs.json'
    manifest.write_text(json.dumps({'format': 'PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1',
                                    'candidates': ['outputs/new.smd']}), encoding='utf-8')
    assert cli.main(['etervale', 'validate-batch', '--repo-root', str(game),
                     '--manifest', str(manifest)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'PLANNED_NOT_EXECUTED'
    assert result['count'] == 1
    assert not (private / 'etervale').exists()
    manifest.write_text(json.dumps({'format': 'PT_ASSET_ETERVALE_CANDIDATE_BATCH_V1',
                                    'candidates': ['../../Etervale-git/private.smd']}), encoding='utf-8')
    assert cli.main(['etervale', 'validate-batch', '--repo-root', str(game),
                     '--manifest', str(manifest)]) == 2


def test_top_level_config_command_stores_one_root(tmp_path, capsys, monkeypatch):
    from pathlib import Path
    import pt_asset
    game = _project(tmp_path)
    app = tmp_path / 'asset-tool-app'; app.mkdir()
    monkeypatch.setattr(pt_asset, 'ROOT', app)
    monkeypatch.delenv('PT_ETERVALE_ROOT', raising=False)
    assert pt_asset._command_app_config(['set-etervale-root', str(game)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['asset_root'] == str(game / 'assets')
    assert configured_etervale_root(app) == game
    assert pt_asset._command_app_config(['clear-etervale-root']) == 0
    capsys.readouterr()
    assert configured_etervale_root(app) is None


def test_candidate_accepts_historical_project_staging(tmp_path, capsys, monkeypatch):
    game = _project(tmp_path)
    app = tmp_path / 'app'; app.mkdir()
    root_pt_build = tmp_path / 'pt_build'
    root_pt_build.mkdir()
    candidate = root_pt_build / 'new.smd'
    candidate.write_bytes(b'SMD Model data Ver 0.62')
    monkeypatch.setattr(bridge, 'bundle_root', lambda: app)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: app / 'pt_build')
    monkeypatch.setattr(bridge, 'is_frozen', lambda: False)
    assert cli.main(['etervale', 'validate', '--repo-root', str(game),
                     '--candidate', str(candidate)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'PLANNED_NOT_EXECUTED'


def test_old_cpp_source_config_not_silently_used_for_etervale(tmp_path, monkeypatch):
    from pt_asset_tool.app_config import save_source_root
    from pt_asset_tool.source_catalog import configured_source_roots
    monkeypatch.delenv('PT_ETERVALE_ROOT', raising=False)
    monkeypatch.delenv('PT_SOURCE_ROOT', raising=False)
    monkeypatch.delenv('PT_REFERENCE_SOURCE_ROOT', raising=False)
    app = tmp_path / 'app'; app.mkdir()
    old_source = tmp_path / 'old-cpp-src'; old_source.mkdir()
    save_source_root(app, old_source)
    assert configured_source_roots(app)[0].root == old_source
    save_etervale_root(app, _project(tmp_path))
    assert configured_source_roots(app) == []
    # A deliberately explicit legacy audit can still ask for an old tree.
    assert configured_source_roots(app, source_root=old_source)[0].root == old_source
