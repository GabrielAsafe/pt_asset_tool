# PT Asset Tool R14 1.0.0 — Estado Atual Final

Data: 2026-09-14

## Decisão

**Release 1.0.0 certificada / safety-locked.**

- `automatic_gate_status=PASS`;
- automatic blockers: `0`;
- package verify: PASS;
- RC6/12 verify: PASS;
- clean-extract verify: PASS;
- `runtime_game_acceptance_pending=false`;
- `production_authorized=false`;
- `client_write_authorized=false`;
- `server_write_authorized=false`.

O status físico do gate pode aparecer como `BLOCKED_EXTERNAL` porque `WRITER_PROMOTION_AND_PUBLISH_RESTORE` permanece uma operação externa/manual. Isso **não** representa falha automática da ferramenta.

## Capability certificada

A release cobre catálogo/registry, Model0.62 static/rigid, materiais, object-local e TexLinks, Stage0.72, INX/SMB/animação, codecs BMP/TGA legacy, census/recovery, source/T5 diagnostics, GUI, server/enrichment read-only, aggregation, build candidates, deployment planning/simulation, regressions e package verification.

A matriz completa está em `FEATURE_MATRIX_1_0.md`.

## Conteúdo target separado da capability

O target Summit ainda possui gaps/invalid payloads de textura. O auditor e o codec permanecem capability PASS; target-content readiness permanece explicitamente FAIL/documentado. Nenhum path é whitelisted para esconder conteúdo inválido e nenhum donor é copiado automaticamente para “fechar” o relatório.

Detalhes: `KNOWN_LIMITATIONS_1_0.md`.

## UI de classe

Mechanician canónico: `image/Sinimage/skill/Mechanician`. `image/Sinimage/skill/Mecha` é legacy ignorado e não é fonte de write/recovery automático.

## Escopo runtime

Gameplay/runtime Tier 1–4 é externo ao gate PT Asset Tool 1.0. Observações históricas desse runtime são preservadas nos documentos de regressão, mas não devem ser interpretadas como blocker da release da ferramenta.

## Próxima fronteira operacional

Publish/restore real só deve ser tratado como operação separada, com autorização explícita. A instalação da 1.0 não altera os flags de produção.
