"""Fast offline integration tests with a mock NCNN Vulkan runtime.

No actual GPU is required; real RX 6600 validation still needs to be run on the
user's Fedora computer using the real model and Vulkan wheel.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image


RUNNER = Path(__file__).resolve().parents[1] / 'app/pt_asset_tool/texture_ncnn_runner.py'

FAKE_NCNN = '''
import numpy as np
class _Device:
    def device_name(self): return 'Mock AMD Radeon RX 6600'
def get_gpu_count(): return 1
def get_gpu_info(i): return _Device()
class Mat:
    class PixelType:
        PIXEL_RGB = 0
    def __init__(self, value):
        self.array = np.asarray(value, dtype=np.float32)
    @staticmethod
    def from_pixels(image, pixel_type, width, height):
        assert image.shape == (height, width, 3)
        return Mat(image.transpose(2,0,1))
    def substract_mean_normalize(self, mean, norm):
        self.array *= np.asarray(norm, dtype=np.float32)[:,None,None]
    def __array__(self, dtype=None, copy=None):
        result = np.asarray(self.array, dtype=dtype)
        return result.copy() if copy else result
class _Options:
    use_vulkan_compute = False
class _Extractor:
    def input(self, name, mat):
        assert name == 'in0'
        self.array = mat.array.copy()
        return 0
    def extract(self, name):
        assert name == 'out0'
        return 0, Mat(self.array.copy())
    def clear(self): pass
class Net:
    def __init__(self): self.opt = _Options()
    def set_vulkan_device(self, i): assert i == 0
    def load_param(self, filename): return 0
    def load_model(self, filename): return 0
    def create_extractor(self): return _Extractor()
    def clear(self): pass
'''


def invoke(tmp_path, *, bad_bin=False, pixel_change=False, cache=True):
    runtime = tmp_path / 'runtime'
    (runtime/'ncnn').mkdir(parents=True, exist_ok=True)
    (runtime/'ncnn/__init__.py').write_text(FAKE_NCNN, encoding='utf-8')
    param, binary = tmp_path/'model.param', tmp_path/'model.bin'
    param.write_bytes(b'model-param')
    binary.write_bytes(b'model-bin')
    input_file, output_file = tmp_path/'input.png', tmp_path/'output.png'
    rng = np.random.default_rng(43 if not pixel_change else 44)
    Image.fromarray(rng.integers(0,256,(70,80,3), dtype=np.uint8)).save(input_file)
    command = [sys.executable, str(RUNNER), '--input', str(input_file), '--output', str(output_file),
        '--model-param', str(param), '--model-bin', str(binary),
        '--sha256', hashlib.sha256(param.read_bytes()).hexdigest(),
        '--sha256-bin', ('0'*64 if bad_bin else hashlib.sha256(binary.read_bytes()).hexdigest()),
        '--runtime-root', str(runtime), '--gpu-id', '0', '--tile', '32', '--halo', '8']
    if cache:
        command += ['--cache-root', str(tmp_path/'cache')]
    return subprocess.run(command, capture_output=True, text=True), input_file, output_file, command


def test_gpu_runner_cache_and_identical_pixels(tmp_path):
    cp, inp, output, command = invoke(tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert '"tiles": 9' in cp.stdout
    assert '"tiles_reused": 0' in cp.stdout
    np.testing.assert_array_equal(np.asarray(Image.open(inp)), np.asarray(Image.open(output)))
    output.unlink()
    cp2 = subprocess.run(command, capture_output=True, text=True)
    assert cp2.returncode == 0, cp2.stderr
    assert '"tiles_reused": 9' in cp2.stdout
    assert output.is_file()


def test_wrong_binary_hash_fails_before_inference(tmp_path):
    cp, _, output, _ = invoke(tmp_path, bad_bin=True)
    assert cp.returncode != 0
    assert 'MODEL_SHA256_MISMATCH' in cp.stderr
    assert not output.exists()


def test_cache_invalidated_when_source_changes(tmp_path):
    cp, _, _, _ = invoke(tmp_path)
    assert cp.returncode == 0, cp.stderr
    cp2, _, _, _ = invoke(tmp_path, pixel_change=True)
    assert cp2.returncode == 0, cp2.stderr
    assert '"tiles_reused": 0' in cp2.stdout
