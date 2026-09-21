# Vendor packages

`vendor/` é reservado a componentes **externos/upstream versionados separadamente**, não a toda ferramenta que possua um launcher próprio.

## summit_asset_enrichment_v9

Vendor ativo do Design Tool. Manifesto: `v9-fix136`. O adapter integrado usa esta árvore para migration plan e dependency graph. Comandos `apply`/`install-apply` do vendor não são expostos automaticamente pela UI.

Funcionalidades first-party como partículas (`pt_asset_tool/particle_service.py`, `pt_part_*`, `pt_effect_*`) e texture enhancement (`pt_asset_tool/texture_upscale.py`) pertencem ao core da aplicação e **não** devem ser movidas para `vendor/` apenas por possuírem launchers/bridges separados.
