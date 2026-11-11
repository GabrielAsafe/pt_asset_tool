"""Integration checks for Etervale export texture evidence and GLB container structure.

No live .NET or Etervale assets needed; the external exporter is simulated.
"""
from __future__ import annotations

import json
import os
import pathlib
import struct

from pt_asset_tool import cli, etervale_integration as bridge


def _game(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / 'Etervale-git'
    (repo / 'assets/Field').mkdir(parents=True)
    (repo / 'Client').mkdir()
    (repo / 'Server').mkdir()
    (repo / 'Shared').mkdir()
    (repo / 'tools/PristonTale.GltfExport').mkdir(parents=True)
    (repo / 'tools/PristonTale.AssetDump').mkdir(parents=True)
    (repo / 'PristonTale.sln').write_text('', encoding='utf-8')
    (repo / 'tools/PristonTale.GltfExport/PristonTale.GltfExport.csproj').write_text('<Project/>')
    (repo / 'tools/PristonTale.AssetDump/PristonTale.AssetDump.csproj').write_text('<Project/>')
    (repo / 'assets/Field/test.smd').write_bytes(b'SMD Stage data v0.72')
    return repo


def _make_glb(path: pathlib.Path, *, corrupt: bool = False) -> None:
    doc = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 1, 'type': 'VEC3'}],
        'bufferViews': [{'buffer': 0, 'byteLength': 12}],
        'buffers': [{'byteLength': 12}],
    }
    if corrupt:
        doc['nodes'][0]['mesh'] = 12
    payload = json.dumps(doc).encode('utf-8')
    payload += b' ' * (-len(payload) % 4)
    body = struct.pack('<II', len(payload), 0x4e4f534a) + payload
    body += struct.pack('<II', 12, 0x004e4942) + bytes(12)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(body)) + body)


def _mock_dotnet(tmp_path: pathlib.Path, monkeypatch, *, missing: bool) -> None:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    path = bin_dir / 'dotnet'
    script = r'''#!/usr/bin/env python3
import os, pathlib, struct, sys
args = sys.argv[1:]
if args and args[0] == 'build':
    print('Build succeeded.')
else:
    assert os.environ.get('PTGLTF_DEBUG') == '1', 'debug not propagated'
    dest = pathlib.Path(args[args.index('--') + 2])
    payload = b' ' * 8
    dest.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(payload)) + payload)
    missing = ('EMIT_MISSING' in os.environ)
    print('wrote', dest)
    print('  stage: 10 verts, 20 faces, 8 textures (' + str(int(missing)) + ' missing or invalid)')
    if missing:
        print("  texture fallback: 'bad-wall.tga' (file not found)", file=sys.stderr)
'''
    path.write_text(script, encoding='utf-8')
    path.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    if missing:
        monkeypatch.setenv('EMIT_MISSING', '1')
    else:
        monkeypatch.delenv('EMIT_MISSING', raising=False)


def test_capture_native_fallback_in_manifest(tmp_path, monkeypatch, capsys):
    repo = _game(tmp_path)
    private = tmp_path / 'asset-tool/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    _mock_dotnet(tmp_path, monkeypatch, missing=True)
    result = cli.main(['etervale', 'export-glb', '--repo-root', str(repo),
                       '--asset', 'Field/test.smd', '--execute', '--output', 'glb/test.glb'])
    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'EXPORTED_NOT_RUNTIME_CERTIFIED'
    assert report['missing_or_invalid_texture_count'] == 1
    assert report['texture_trace_complete']
    assert report['texture_diagnostic_status'] == 'FALLBACKS_IDENTIFIED'
    assert report['texture_fallbacks'] == [{'name': 'bad-wall.tga', 'reason': 'file not found'}]
    stored = json.loads(pathlib.Path(report['report_file']).read_text())
    assert stored['texture_fallbacks'] == report['texture_fallbacks']
    assert report['source_unchanged']


def test_strict_export_flags_fallback_but_keeps_staged_glb(tmp_path, monkeypatch, capsys):
    repo = _game(tmp_path)
    private = tmp_path / 'asset-tool/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    _mock_dotnet(tmp_path, monkeypatch, missing=True)
    assert cli.main(['etervale', 'export-glb', '--repo-root', str(repo), '--asset', 'Field/test.smd',
                     '--strict-textures', '--execute', '--output', 'glb/strict.glb']) == 3
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'FAILED_TEXTURE_FALLBACKS'
    assert pathlib.Path(report['output']).exists()
    assert report['game_assets_modified'] is False


def test_strict_export_approves_zero_missing_without_claiming_runtime(tmp_path, monkeypatch, capsys):
    repo = _game(tmp_path)
    private = tmp_path / 'asset-tool/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    _mock_dotnet(tmp_path, monkeypatch, missing=False)
    assert cli.main(['etervale', 'export-glb', '--repo-root', str(repo), '--asset', 'Field/test.smd',
                     '--strict-textures', '--execute', '--output', 'glb/clean.glb']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'EXPORTED_NOT_RUNTIME_CERTIFIED'
    assert report['missing_or_invalid_texture_count'] == 0
    assert report['texture_diagnostic_status'] == 'COMPLETE'


def test_inspect_glb_structure(tmp_path, monkeypatch, capsys):
    private = tmp_path / 'asset-tool/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    good = private / 'etervale/glb/complete.glb'
    good.parent.mkdir(parents=True)
    _make_glb(good)
    assert cli.main(['etervale', 'inspect-glb', '--file', str(good)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc['status'] == 'GLB_VALID_STRUCTURAL_ONLY'
    assert doc['counts']['meshes'] == 1
    assert doc['chunks'][1]['type'] == 'BIN'
    bad = private / 'etervale/glb/invalid.glb'
    _make_glb(bad, corrupt=True)
    assert cli.main(['etervale', 'inspect-glb', '--file', str(bad)]) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc['status'] == 'GLB_INVALID_STRUCTURE'
    assert any('invalid_meshes_index' in s for s in doc['errors'])


def test_inspector_refuses_game_files(tmp_path, monkeypatch, capsys):
    repo = _game(tmp_path)
    private = tmp_path / 'asset-tool/pt_build'
    private.mkdir(parents=True)
    monkeypatch.setattr(bridge, 'persistent_pt_build', lambda: private)
    outside = repo / 'assets/Field/file.glb'
    _make_glb(outside)
    assert cli.main(['etervale', 'inspect-glb', '--file', str(outside)]) == 2
    assert 'GLB_MUST_BE_UNDER_ASSET_TOOL_PT_BUILD' in capsys.readouterr().err
