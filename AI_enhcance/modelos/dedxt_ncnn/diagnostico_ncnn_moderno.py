import os
from pathlib import Path

import numpy as np
from PIL import Image
import ncnn

base = Path.home() / "Transferências/modelos/dedxt_ncnn"
modo = os.environ["NCNN_MODE"]
assert modo in ("cpu", "vulkan")

with Image.open(base / "teste_64_original.png") as img:
    rgb = np.ascontiguousarray(
        np.asarray(img.convert("RGB"), dtype=np.uint8)
    )

altura, largura = rgb.shape[:2]

net = ncnn.Net()

if modo == "vulkan":
    net.opt.use_vulkan_compute = True
    net.set_vulkan_device(0)
else:
    net.opt.use_vulkan_compute = False

assert net.load_param(str(base / "DEDXT_1x.ncnn.param")) == 0
assert net.load_model(str(base / "DEDXT_1x.ncnn.bin")) == 0

entrada = ncnn.Mat.from_pixels(
    rgb,
    ncnn.Mat.PixelType.PIXEL_RGB,
    largura,
    altura
)
entrada.substract_mean_normalize(
    [],
    [1.0 / 255, 1.0 / 255, 1.0 / 255]
)

print(f"{modo}: inferência iniciada", flush=True)

ex = net.create_extractor()
assert ex.input("in0", entrada) == 0

codigo, saida = ex.extract("out0")
assert codigo == 0

resultado = np.array(saida, copy=True)

assert resultado.shape == (3, altura, largura)
assert np.isfinite(resultado).all()

print(f"{modo}: inferência OK", flush=True)

del saida
del entrada

print(f"{modo}: a libertar extractor", flush=True)
ex.clear()
del ex

print(f"{modo}: a libertar modelo", flush=True)
net.clear()
del net

print(f"{modo}: LIMPEZA_OK", flush=True)
