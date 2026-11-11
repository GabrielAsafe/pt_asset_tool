# ETERVALE V19 — Stage 0.72: precisão do proxy Blender

**Aplicar depois da V18.** Este patch corrige `proxy_vertices_wrong_coordinate_basis`
no mapa `Field/Boss/dark_boss.smd` ao centrar os vértices do *proxy privado*
antes de aplicar a escala da viewport. Não aumenta a tolerância do auditor,
não modifica o cliente Etervale nem toca no SMD/UVs originais.

## Instalação

```sh
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V19_STAGE072_VIEW_PRECISAO_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v19_stage072.py --project-root "$PWD" --dry-run
```

Se não houver `SOURCE_FILE_CONFLICT`, aplicar:

```sh
python3 patches/aplicar_etervale_v19_stage072.py --project-root "$PWD"
python3 -m pytest -q \
  app/dev_tests/test_etervale_stage072_view_rebase_f32_v19.py \
  app/dev_tests/test_etervale_stage072_view_paint_v12.py
```

## Validação de produção

Depois de qualquer outro Blender job terminar:

```sh
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

**Não usar `--fresh`.** Os 57 PASS anteriores devem permanecer em checkpoint
`[cached]`, enquanto `dark_boss` repete o worker. Confirmar a linha `[4/58]`
e o campo `blender_counts.PASS_BLENDER_TRANSPORT_AND_VIEW` do resumo.

Um PASS de 58/58 prova apenas transporte + construção/verificação do proxy.
`dark_boss` conserva a textura ausente `field/boss/a_flag01.TGA`, e o seu
material 0 com `hTexture=0` continua em revisão. O status global pode ficar
`FAIL_OR_REVIEW_REQUIRES_ACTION` pelos problemas de material já inventariados.

## Conteúdo e limites

- `MODIFICAR app/pt_asset_tool/blender/open_stage072_preview.py`
- `MODIFICAR app/dev_tests/test_etervale_stage072_view_paint_v12.py`
- `CRIAR app/dev_tests/test_etervale_stage072_view_rebase_f32_v19.py`
- `CRIAR docs/etervale/V19_STAGE072_STABLE_FLOATING_ORIGIN_VIEW.md`

O instalador verifica SHA-256 do ficheiro-base e do conteúdo novo, mostra
dry-run, guarda backup e não sobrescreve ficheiros locais inesperados.

**Validação local neste pacote:** 32 testes Python V12–V19. O Blender 5.2
real não estava disponível aqui; o último PASS deve ser confirmado na máquina
de produção. Regressões visuais no Blender devem ser reportadas sem salvar
por cima de previews anteriormente certificados.
