# Texture Upscale Pipeline

Texture enhancement works on staged candidates and preserves source safety.

## Workspace

Canonical runtime workspace:

```text
app/pt_build/texture_upscale/
```

## Safety

- Enhancement generation does not overwrite the source client.
- Alpha and protected legacy headers are preserved where required.
- Publication validates that the candidate matches the current source/hash contract.
- Publication creates backup and verifies post-write state.
- Restore refuses unknown drift.

## Global vs individual

Use **Client / Enrichment** for the global batch. Use **Catalog** for enhancement of a specific asset.


## Phase 2 — opt-in pre-cleaning and game-texture NCNN models

- `--denoise off|light|medium` (default `off`) is a conservative RGB median-blend **before** upscaling. It preserves source alpha but does **not** undo DXT/BCn blocks as a trained restoration network would. `medium` may erase useful material grain.
- `--model NAME --model-dir PATH` selects a custom **NCNN-converted** model with both `NAME.param` and `NAME.bin` in PATH. PyTorch `.pth` files such as OpenModelDB DEDXT cannot be used directly with `realesrgan-ncnn-vulkan`; use a separate compatible restoration workflow or validated conversion.
- Filename hints such as `_normal`, `_n`, `_nrm`, `_height`, `_parallax` are skipped as `skipped_technical_map_review` by default. Use `--include-technical-maps` only for an explicitly reviewed test. Filename detection is not shader/material proof.

```bash
cd app
python3 pt_asset.py texture-upscale run \
  --include-exact 'Image/Field/stone.tga' --scale 4 \
  --backend realesrgan --profile detail --denoise light

python3 pt_asset.py texture-upscale run \
  --include-exact 'Image/Field/stone.tga' --scale 4 \
  --backend realesrgan --profile faithful \
  --model GameTexture4x --model-dir /models/ncnn --denoise off
```

The manifest records denoise/model directory/technical-map policy and per-texture role/model/denoise; `resume` restores these settings. The single-texture GUI exposes pre-cleaning and custom model selection; the global batch asks for pre-cleaning (default off).

**Engine boundary:** this is a Priston Tale/Summit TGA/BMP/PNG/JPEG pipeline, not a Skyrim DDS/BCn pipeline. Normal/height map generation, parallax, and mesh fixes are **not implemented**. They require proof of renderer/shader/texture-slot support, UV and alpha-channel conventions, and in-game validation before they can be safely added.


**Fases 3–6 (outubro de 2026):** foi acrescentado o `texture-material` para processamento **1× pós-upscale**, geração offline de normal/height/parallax-demo, auditoria SMD e aprovação de candidatos por hash. Consulte `docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md`. A publicação de mapas não é suportada sem shaders/mesh fixes certificados para o cliente; a geração offline não implica efeito em jogo.
