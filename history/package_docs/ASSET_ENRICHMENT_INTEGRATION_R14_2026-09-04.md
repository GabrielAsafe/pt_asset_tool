# R14 — integração Asset Enrichment 1.0

Data: 2026-09-04

## Integrado

- `server_root` como raiz de primeira classe, separada de `client_root`.
- descoberta/persistência de server root via `PT_SERVER_ROOT`, config e layouts Summit usuais.
- classificação server-side por path/ciclo de vida.
- exclusão hard de persistência, logs, segurança e integridade runtime da superfície de autoria.
- censo server inventory e layouts SPP/SPC/INX.
- bundles Monster/NPC, Field e OpenItem.
- gate agregado `validate server-design-auto` agora inclui inventory físico.
- aba UI `Servidor / Enrichment`, configuração de root, métricas, política, bundles e execução assíncrona dos gates.
- documentação do jogo em `docs/SUMMIT_GAME_ASSET_ENRICHMENT.md` e referência DOCX final preservada em `docs/reference/`.

## Segurança

A integração é read-only em `client_root` e `server_root`. Nenhum writer server está autorizado. Outputs e relatórios ficam em `pt_build`.

## Rigid watchdog

O gate `physical-regression-auto` agora imprime progresso por asset/etapa de `rigid_regressions`, aplica timeout por operação Blender/writer (default 180 s), mata o process group em timeout, continua o batch fail-closed e reaproveita PASS anterior com SHA do source idêntico.
