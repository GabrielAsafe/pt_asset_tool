# Patch 2026-09-16 — Package/runtime alignment

Este patch alinha os contratos automáticos com a árvore 1.0 reorganizada e com as dependências realmente suportadas.

## Generic Blender import smoke

O comando `import_blender` passou a acrescentar opções default (`--load-actions`, `--motion`, `--open-mode`) depois de `import <asset>`. O smoke/teste antigo verificava incorretamente os dois últimos argumentos. O contrato agora confirma `import <asset>` na posição estrutural correta e também exige as três opções default.

## Blender como capability opcional

`validate environment-auto` continua a validar client, inventário, hashes, isolamento e segurança sem exigir Blender para todos os usos. Quando Blender não está instalado, `blender_headless_filesystem_bridge` é `SKIP`, `blender_ready=false` e o ambiente geral pode ser `PASS`. Workflows que dependem de Blender permanecem indisponíveis; em particular `release-1-auto` não inicia quando `policy.release_1_auto_may_run=false`.

## Vendor ativo

A distribuição ativa suporta apenas `vendor/summit_asset_enrichment_v9/` (`v9-fix136`). O fallback para v6 foi removido do adapter, da UI e da verificação de pacote. Menções a v6 podem continuar existindo apenas em material histórico.

## Documentação e package verification

`VERIFY_PACKAGE.sh` usa os caminhos atuais (`docs/comece_aqui`, `docs/release`, `docs/tematicos`, `docs/engenharia`, etc.). O snapshot deve ser regenerado apenas depois de mudanças autorizadas com `python3 app/update_snapshot_manifest.py --current-root .`.
