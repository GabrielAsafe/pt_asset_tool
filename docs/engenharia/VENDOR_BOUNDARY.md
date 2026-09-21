# Boundary de `vendor/`

`vendor/` não significa “qualquer ferramenta que possa rodar separadamente”. Ele é reservado a componentes **externos/upstream**, importados como um pacote com versão/manifesto próprios e adaptados pelo PT Asset Tool.

## O que pertence a `vendor/`

Atualmente: `vendor/summit_asset_enrichment_v9/` (`v9-fix136`). Esse pacote tem origem/ciclo de versão próprios e é consumido através de `pt_asset_tool/enrichment_vendor_adapter.py`.

## O que não pertence a `vendor/`

Funcionalidades desenvolvidas como parte do PT Asset Tool continuam first-party, mesmo quando possuem um launcher histórico separado. Exemplos:

- partículas: `pt_asset_tool/particle_service.py`, `pt_part_*`, `pt_effect_*`;
- enhancement/upscale: `pt_asset_tool/texture_upscale.py`;
- GUI, Asset Compiler, Field Editor, deploy e validators.

A existência de um executável/script separado é uma decisão de UX/compatibilidade, não um critério de vendorização.

## Regra de integração

Quando uma funcionalidade first-party ganha UI principal, a lógica de domínio deve ficar num módulo reutilizável do core. Launchers antigos podem permanecer como wrappers de compatibilidade, mas não devem manter uma segunda implementação divergente.
