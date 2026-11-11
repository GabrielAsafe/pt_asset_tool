import hashlib
import json
from pathlib import Path
from time import perf_counter

import ncnn
import numpy as np
from PIL import Image

home = Path.home()
base = home / "Transferências/modelos/dedxt_ncnn"
origem = home / "Área de Trabalho/summit/cliente/Field/Boss/stone_01.bmp"

saida = home / "Transferências/material_lab_paredes_chao/stone_01_gpu_piloto"
tiles_dir = saida / "tiles"
tiles_dir.mkdir(parents=True, exist_ok=True)

param = base / "DEDXT_1x.ncnn.param"
binario = base / "DEDXT_1x.ncnn.bin"

TILE = 256
HALO = 24

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()

for p in (origem, param, binario):
    assert p.is_file(), f"Ficheiro não encontrado: {p}"

with Image.open(origem) as im:
    if "A" in im.getbands() or "transparency" in im.info:
        raise RuntimeError("Textura com transparência: requer tratamento específico.")
    antes = im.convert("RGB")

largura, altura = antes.size
assert (largura, altura) == (2048, 2048), (
    f"Dimensões inesperadas: {largura}x{altura}"
)

assinatura = {
    "source": "Field/Boss/stone_01.bmp",
    "source_sha256": sha256(origem),
    "model_param_sha256": sha256(param),
    "model_bin_sha256": sha256(binario),
    "engine": "ncnn",
    "runtime": "1.0.20261020",
    "device": "AMD Radeon RX 6600 Vulkan GPU 0",
    "tile": TILE,
    "halo": HALO,
    "scale": 1,
    "border_mode": "reflect",
}

identificacao = saida / "identificacao.json"

if identificacao.exists():
    anterior = json.loads(identificacao.read_text(encoding="utf-8"))
    assert anterior == assinatura, "Origem ou configuração mudou. Não reutilizar tiles!"
else:
    assert not list(tiles_dir.glob("*.png")), "Tiles existentes sem identificação."
    identificacao.write_text(
        json.dumps(assinatura, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

print("TEXTURA:", origem)
print("DIMENSÕES:", largura, "x", altura)
print("SAÍDA:", saida)
print("GPU:", ncnn.get_gpu_info(0).device_name(), flush=True)

assert "AMD Radeon RX 6600" in ncnn.get_gpu_info(0).device_name()

rgb = np.asarray(antes, dtype=np.uint8)
padded = np.pad(
    rgb,
    ((HALO, HALO), (HALO, HALO), (0, 0)),
    mode="reflect"
)

net = ncnn.Net()
net.opt.use_vulkan_compute = True
net.set_vulkan_device(0)

assert net.load_param(str(param)) == 0
assert net.load_model(str(binario)) == 0

total = (
    ((largura + TILE - 1) // TILE)
    * ((altura + TILE - 1) // TILE)
)
concluidos = 0
inicio_total = perf_counter()

for y in range(0, altura, TILE):
    for x in range(0, largura, TILE):
        w = min(TILE, largura - x)
        h = min(TILE, altura - y)

        ficheiro = tiles_dir / f"tile_y{y:04d}_x{x:04d}.png"

        if ficheiro.exists():
            with Image.open(ficheiro) as guardado:
                guardado.load()
                assert guardado.size == (w, h)
                assert guardado.mode == "RGB"
            concluidos += 1
            print(f"[{concluidos}/{total}] Reutilizado: {ficheiro.name}", flush=True)
            continue

        # Acrescentar contexto de 24 píxeis a cada lado.
        patch = np.ascontiguousarray(
            padded[y:y+h+2*HALO, x:x+w+2*HALO],
            dtype=np.uint8
        )

        ph, pw = patch.shape[:2]

        mat = ncnn.Mat.from_pixels(
            patch,
            ncnn.Mat.PixelType.PIXEL_RGB,
            pw,
            ph
        )
        mat.substract_mean_normalize(
            [], [1/255, 1/255, 1/255]
        )

        inicio = perf_counter()
        ex = net.create_extractor()

        assert ex.input("in0", mat) == 0

        codigo, resultado_mat = ex.extract("out0")
        assert codigo == 0, f"Falha NCNN no tile {x},{y}: {codigo}"

        resultado = np.array(resultado_mat, copy=True)
        assert resultado.shape == (3, ph, pw)
        assert np.isfinite(resultado).all()

        del resultado_mat
        del mat
        ex.clear()
        del ex

        # Retirar as margens: só o centro entra na textura final.
        centro = resultado[
            :, HALO:HALO+h, HALO:HALO+w
        ]

        pixels = (
            np.clip(centro.transpose(1, 2, 0), 0, 1) * 255
        ).round().astype(np.uint8)

        temporario = ficheiro.with_name(ficheiro.name + ".tmp")
        Image.fromarray(pixels).save(temporario, format="PNG")
        temporario.replace(ficheiro)

        concluidos += 1
        print(
            f"[{concluidos}/{total}] GPU: {ficheiro.name} "
            f"{perf_counter()-inicio:.2f}s",
            flush=True
        )

net.clear()
del net

print("A montar a textura completa...", flush=True)

final = Image.new("RGB", (largura, altura))

for y in range(0, altura, TILE):
    for x in range(0, largura, TILE):
        ficheiro = tiles_dir / f"tile_y{y:04d}_x{x:04d}.png"
        with Image.open(ficheiro) as tile:
            final.paste(tile, (x, y))

imagem_final = saida / "stone_01_DEDXT_GPU_2048.png"
final.save(imagem_final)

# Comparação visual reduzida, sem modificar o original.
prev_antes = antes.resize((768, 768), Image.Resampling.LANCZOS)
prev_depois = final.resize((768, 768), Image.Resampling.LANCZOS)

comparacao = Image.new("RGB", (1536, 768))
comparacao.paste(prev_antes, (0, 0))
comparacao.paste(prev_depois, (768, 0))
comparacao.save(saida / "comparacao_antes_depois.png")

assert final.size == antes.size
assert sha256(origem) == assinatura["source_sha256"]

relatorio = {
    **assinatura,
    "status": "staged_for_review",
    "tiles_completed": concluidos,
    "tiles_total": total,
    "image_output": str(imagem_final),
    "output_sha256": sha256(imagem_final),
    "elapsed_seconds": round(perf_counter() - inicio_total, 2),
    "upscale_performed": False,
    "client_modified": False,
    "approved_for_deployment": False,
}

(saida / "resultado_gpu.json").write_text(
    json.dumps(relatorio, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("\nGPU_STONE_2048=PASS")
print("TILES:", concluidos, "/", total)
print("RESOLUÇÃO:", final.size)
print("ORIGINAL_INTACTO=PASS")
print("NOVO_UPSCALE=False")
print("IMAGEM:", imagem_final)
print("COMPARAÇÃO:", saida / "comparacao_antes_depois.png")
print("DURAÇÃO:", relatorio["elapsed_seconds"], "segundos")
