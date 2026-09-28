# Validation — Asset Retention + Cooked DDS metadata revision 3 — 2026-09-27

## Mudança

- `cooked_texture_evidence` importa `skip_class`, decode mode, integrity state e metadata de outlier.
- `asset_retention` combina essa evidência com reachability em `integrity_action`, sem mudar o state de retenção.
- failures nunca autorizam delete.
- skipped após decode válido não é failure.
- metadata conhecida é preservada quando o DDS já está up-to-date.

## Evidência do rollout real

O fluxo incremental observado no client Summit reduziu o conjunto original de
145 failures para 6 sem decoder permissivo:

- 105 assets `TGA_KEEP_00_16` reconhecidos;
- 25 assets `TGA_DIMENSIONS_12_15` reconhecidos;
- 9 assets `BMP_SHIP_DIB40` reconhecidos;
- 6 residuals permanecem explicitamente como failure/review;
- 2 assets adicionais (`Field/Iron/i05.TGA` e `game/maps/chrselect/ship_rope.bmp`)
  foram decodificados corretamente e ficaram `skipped` por estarem abaixo do
  threshold DXT, portanto não são failures.

## Gates desta revisão

- cooker V2.3 unit/synthetic: 7 passed;
- PT Asset Tool targeted retention/cooked/general census: 28 passed;
- Python compile: PASS;
- UI JavaScript syntax: PASS.

O gate de distribuição limpa (`VERIFY_PACKAGE.sh`) não deve ser usado como gate
fatal em uma instalação de trabalho contendo `.pt_asset_patch_backups/`,
archives locais ou runtime data. Ele continua válido para certificar release
packages limpos.

## Regressão e package gate

- `RUN_REGRESSION_FOCUSED.sh`: 40 passed, 1 skipped, `REGRESSION_FOCUSED=PASS`.
- `VERIFY_PACKAGE.sh` em árvore limpa da revisão: PASS, snapshot estático regenerado com 706 arquivos.
- O aplicador incremental foi exercitado contra a baseline integrada anterior: patch PT Asset Tool + patch cooker aplicaram limpo e 28 testes focados passaram após aplicação.
