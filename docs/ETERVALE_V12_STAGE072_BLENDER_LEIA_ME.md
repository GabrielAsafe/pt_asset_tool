# Etervale V12 — Correção Blender Stage0.72 (orientação + paint parcial)

Patch incremental compatível com a source e scripts originais de Stage072 do PT Asset Tool. Não modifica assets do Etervale, texturas nem a BD. **Não precisa parar o SMD preview batch**: esta atualização incide sobre os scripts de visualização/pintura Stage072, não o worker de geração SMD em lote. Feche qualquer sessão *Stage Paint* antiga antes de reabrir para carregar os novos scripts.

## Aplicar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V12_STAGE072_BLENDER_ORIENTACAO_PAINT_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v12_stage072.py --project-root "$PWD" --dry-run
# Aplicar apenas se não houver SOURCE_FILE_CONFLICT:
python3 patches/aplicar_etervale_v12_stage072.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_view_paint_v12.py
```

Se o instalador recusar devido a SHA-256 diferente, NÃO force nem substitua scripts locais; envia o dry-run para adequarmos o patch.

## Provar Ricarten no Blender

```bash
python3 app/pt_asset.py view stage072 Field/Ricarten/village-2.smd
python3 app/pt_asset.py paint stage072 Field/Ricarten/village-2.smd --stage 0
```

No View, o chão e edifícios devem ser visíveis do **mesmo lado**, com Y do jogo convertido em Z vertical no Blender. No Paint, o comando deve imprimir `PT_STAGE072_PAINT=PASS_WITH_KNOWN_MISSING_UNPAINTABLE` e guardar `paint_manifest.json`, sem falhar por `tem_wall04.bmp`. A face que usa essa textura permanece **não pintável**; não foi gerado qualquer substituto.

Ainda é necessário confirmar a vista e Paint no Blender da tua instalação; os testes offline não são uma certificação de runtime. O teu `validate stage072-geometry-roundtrip` anterior pode ser repetido para demonstrar que source/writers continuam intactos.
