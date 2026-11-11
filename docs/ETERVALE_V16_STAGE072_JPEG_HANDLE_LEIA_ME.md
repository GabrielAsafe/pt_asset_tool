# Etervale V16 — JPEG em BMP e preview restrito de dark_boss

**Requer V14 aplicada.** V15 era um script de diagnóstico, não um patch de instalação.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V16_STAGE072_JPEG_HANDLE_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v16_stage072.py --project-root "$PWD" --dry-run
```

Se não houver `SOURCE_FILE_CONFLICT`:

```bash
python3 patches/aplicar_etervale_v16_stage072.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_v16_jpeg_darkboss.py
```

Depois execute o checkpoint já existente:

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

**Não use `--fresh`**: os 56 mapas anteriores devem permanecer em cache. Se o lote SMD de milhares de modelos ainda estiver ativo, execute o Blender Stage apenas quando ele terminar.

## Significado esperado

- `pilai`: tentativa de converter o ficheiro físico JPEG/JFIF com nome `.bmp` para **BMP apenas no overlay**. Um JPEG inválido continua bloqueado.
- `dark_boss`: uma anomalia exata de `hTexture=0` e UV nulas é admitida para construir o preview, mas **permanece como `REVIEW_REQUIRED`** na auditoria por não provar o comportamento visual in-game.
- 56 resultados headless existentes reutilizados. Não inventa texturas nem substitui os assets originais.

Documentação técnica completa: `docs/etervale/V16_STAGE072_JPEG_SOURCE_LOCKED_HANDLE.md`.
