#!/usr/bin/env bash
# Generate a SHA-pinned, explicit GPU config for the already converted DEDXT 1x.
# Does not install software, run inference, or touch the game client.
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import hashlib, json, os

home=Path.home()
base=home/'Transferências/modelos/dedxt_ncnn'
param=base/'DEDXT_1x.ncnn.param'
binary=base/'DEDXT_1x.ncnn.bin'
python=home/'.config/chaiNNer/python/python/bin/python3.11'
runtime=base/'runtime_ncnn_20261020'
config=base/'dedxt_gpu_material_lab.json'
for file in (param, binary, python):
    if not file.is_file():
        raise SystemExit(f'Ficheiro em falta: {file}')
if not runtime.is_dir():
    raise SystemExit(f'Runtime NCNN em falta: {runtime}')
if config.exists():
    raise SystemExit(f'Config já existe; não vou substituir: {config}')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''): h.update(data)
    return h.hexdigest()
contents={'material_overrides':{}, 'models':{'default':{
    'engine':'ncnn_vulkan',
    'model_param':str(param), 'model_bin':str(binary),
    'sha256':sha(param), 'sha256_bin':sha(binary),
    'python':str(python), 'runtime_root':str(runtime),
    'tile_cache_root':str(home/'Transferências/material_lab_gpu_tile_cache'),
    'gpu_id':0, 'tile':256, 'halo':24, 'timeout':1800,
}}}
with config.open('x',encoding='utf-8') as f:
    json.dump(contents,f,indent=2,ensure_ascii=False)
    f.write('\n')
print('CONFIG_GPU:',config)
print('BACKEND: NCNN Vulkan GPU 0, DEDXT 1x; cliente intacto.')
PY
