"""Pipeline configuration and subprocess dispatch tests (stubs for other modules)."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]/'app/pt_asset_tool'


def load_pipeline(monkeypatch):
    # Only the six requested PT Asset Tool source files were supplied. Stub
    # unrelated imports so this test cannot claim wider project compatibility.
    pkg = types.ModuleType('pt_asset_tool')
    pkg.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, 'pt_asset_tool', pkg)
    runtime = types.ModuleType('pt_asset_tool.runtime_paths')
    runtime.external_process_env = lambda: dict(os.environ)
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    for name in ('texture_upscale', 'texture_material_maps', 'texture_material_quality', 'texture_material_profiles'):
        m = types.ModuleType('pt_asset_tool.'+name)
        monkeypatch.setitem(sys.modules, m.__name__, m)
        setattr(pkg, name, m)
    tex = sys.modules['pt_asset_tool.texture_upscale']
    tex.sha256_file = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    tex._is_within = lambda root, p: Path(p).is_relative_to(Path(root))
    maps = sys.modules['pt_asset_tool.texture_material_maps']
    for name in ('height_from_diffuse','normals_from_height','renormalize_normals','parallax_demo'):
        setattr(maps, name, lambda *a,**k: None)
    quality = sys.modules['pt_asset_tool.texture_material_quality']
    quality.assess = lambda *a: {}
    quality.difference_preview = lambda *a: None
    profiles = sys.modules['pt_asset_tool.texture_material_profiles']
    profiles.PROFILE = 'safe-game-v1'
    spec = importlib.util.spec_from_file_location('pt_asset_tool.texture_material_pipeline', ROOT/'texture_material_pipeline.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_ncnn_config_parsing_and_binary_pin(tmp_path, monkeypatch):
    pipeline=load_pipeline(monkeypatch)
    (tmp_path/'model.param').write_bytes(b'param')
    (tmp_path/'model.bin').write_bytes(b'binary')
    (tmp_path/'runtime').mkdir()
    model={'engine':'ncnn_vulkan','model_param':'model.param','model_bin':'model.bin',
           'sha256':hashlib.sha256(b'param').hexdigest(),
           'sha256_bin':hashlib.sha256(b'binary').hexdigest(),
           'python':sys.executable,'runtime_root':'runtime','tile':256,'halo':24, 'gpu_id':0}
    config=tmp_path/'gpu.json'
    config.write_text(json.dumps({'models':{'default':model}}))
    loaded=pipeline.load_config(config)
    assert pipeline.validate_model(loaded['models']['default'],config)==(tmp_path/'model.param').resolve()
    (tmp_path/'model.bin').write_bytes(b'changed')
    try:
        pipeline.validate_model(model, config)
    except ValueError as exc:
        assert 'NCNN_BIN_SHA256_MISMATCH' in str(exc)
    else:
        raise AssertionError('Modified binary model was accepted')


def test_config_rejects_bad_gpu_tile(tmp_path, monkeypatch):
    pipeline=load_pipeline(monkeypatch)
    model={'engine':'ncnn_vulkan','model_param':'a','model_bin':'b','sha256':'a'*64,
           'sha256_bin':'b'*64,'python':'p','runtime_root':'r','tile':16}
    config=tmp_path/'gpu.json'
    config.write_text(json.dumps({'models':{'default':model}}))
    try:
        pipeline.load_config(config)
    except ValueError as exc:
        assert 'NCNN_INVALID_TILE_HALO_OR_GPU' in str(exc)
    else:
        raise AssertionError('Invalid tile size accepted')


def test_tile_cache_inside_input_client_is_rejected(tmp_path, monkeypatch):
    pipeline = load_pipeline(monkeypatch)
    client = tmp_path/'cliente'
    client.mkdir()
    outside = tmp_path/'resultados'
    cfg = tmp_path/'gpu.json'
    row = {'engine':'ncnn_vulkan', 'model_param':'a', 'model_bin':'b',
           'sha256':'a'*64, 'sha256_bin':'b'*64,
           'python':sys.executable, 'runtime_root':'runtime',
           'tile_cache_root':str(client/'cache')}
    cfg.write_text(json.dumps({'models':{'default':row}}))
    try:
        pipeline.prepare(client, outside, include=[], exact=['Field/Boss/stone_01.bmp'],
                         all_=False, config_path=cfg)
    except ValueError as exc:
        assert 'NCNN_TILE_CACHE_INSIDE_CLIENT_BLOCKED' in str(exc)
    else:
        raise AssertionError('Cache destination inside client was accepted')
    assert not (client/'cache').exists()


def test_restore_rgb_dispatch_uses_isolated_python_and_preserves_alpha(tmp_path, monkeypatch):
    pipeline = load_pipeline(monkeypatch)
    # Reuse the mock module used to test the NCNN runner, not the real GPU.
    from test_texture_ncnn_runner import FAKE_NCNN
    runtime = tmp_path/'runtime'
    (runtime/'ncnn').mkdir(parents=True)
    (runtime/'ncnn/__init__.py').write_text(FAKE_NCNN, encoding='utf-8')
    param, binary = tmp_path/'model.param', tmp_path/'model.bin'
    param.write_bytes(b'param')
    binary.write_bytes(b'bin')
    config = tmp_path/'gpu.json'
    model = {'engine':'ncnn_vulkan', 'model_param':str(param), 'model_bin':str(binary),
             'sha256':hashlib.sha256(param.read_bytes()).hexdigest(),
             'sha256_bin':hashlib.sha256(binary.read_bytes()).hexdigest(),
             'python':sys.executable,'runtime_root':str(runtime),
             'gpu_id':0,'tile':32,'halo':8}
    config.write_text(json.dumps({'models':{'default':model}}))
    rgba = Image.new('RGBA', (65, 65), (120, 60, 200, 123))
    output, metadata = pipeline.restore_rgb(rgba, model, config)
    assert output.mode == 'RGBA'
    assert output.size == rgba.size
    assert output.getchannel('A').getextrema() == (123,123)
    assert output.getpixel((0, 0))[:3] == (120, 60, 200)
    assert metadata['engine'] == 'ncnn_vulkan'
    assert metadata['model_bin_sha256'] == model['sha256_bin']
