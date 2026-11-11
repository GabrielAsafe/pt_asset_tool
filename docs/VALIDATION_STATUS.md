# Validation Status — V2.10 English Localization — 2026-09-28

## Overall

**PT Asset Tool 1.0.0 / V2.10 localization layer: TARGETED PASS / REGRESSION PASS**

V2.10 changes the first-party web UI and default operational/developer documentation to English. It does not expand authoring, client/server write, quarantine, or delete authority.

## Localization boundary

English-localized:

- first-party web UI labels, help text, workflow descriptions, prompts, toasts, and selected API-facing operator messages;
- root README and documentation index;
- authoritative operator/developer documentation under `docs/en/`.

Intentionally not translated:

- semantic catalog game `display_name` values used for matching;
- `canonical_id`, runtime codes, file paths, hashes, evidence tokens, and raw source excerpts;
- historical Portuguese documentation retained for provenance/path compatibility.

## Current validation

- English localization validator: `EN_LOCALIZATION=PASS`.
- English localization tests: 3 passed.
- V2.9 semantic-authoring + V2.10 localization focused suite: 42 passed.
- Focused regression: 40 passed, 1 skipped; `REGRESSION_FOCUSED=PASS`.
- Documentation audit: 76 files, 0 errors.
- JavaScript syntax (`node --check`): PASS.
- Package snapshot: 757 files; PASS.
- `VERIFY_PACKAGE=PASS`.

## Safety state

- production authorization: false by default;
- client write authorization: false by default;
- server write authorization: false by default;
- Q0/Q1 quarantine remains reversible;
- Q1 review score remains prioritization only;
- delete authority remains false;
- V2.8 exact-component manual quarantine gates remain unchanged;
- V2.9 semantic authoring identity/provenance gates remain unchanged.

## Current quarantine state known from operator evidence

The operator has previously quarantined four Q0 documented-invalid zero-linkage assets and the exact Q1 component `URC-02537` (`m_fury.smd` + `m_fury.tga`) transactionally with restore available. V2.10 does not modify quarantine state or transaction storage.

## References

- `docs/en/README.md`
- `docs/en/validation/LOCALIZATION_EN_V210.md`
- `docs/en/topics/SEMANTIC_AUTHORING_CATALOG.md`
- `docs/en/topics/ASSET_QUARANTINE_WORKFLOW.md`

## V2.11 — Summit Canonical Source Integration (2026-10-01)

Focused automated validation: `38 passed` across `test_summit_canonical_v211.py`, `test_legacy_authoring_pipeline.py`, and `test_legacy_name_catalog.py`. Coverage includes fail-closed authority schemas, Semantic Catalog V2 alias-overlay behavior, missing-display-name fallback, atomic fields+directives editing, CP1252/capacity guards, presence-only boolean directives, complete-tree staging with per-file source/stage hashes, legacy writer disablement, CLIENT/SERVER map separation, `legacy_field_code`/dynamic field 53 handling, gameplay/localization browsers, Quest/Mix reference boundaries, and canonical ContractGraph/profile edges.

`Content(5).zip` was audited directly against the V2.11 provider. The observed canonical census is:

- 1,924 Item definitions;
- 383 Monster definitions;
- 175 NPC definitions;
- 53 CLIENT + 53 SERVER static map entries, kept as separate profiles;
- 31 Item canonical IDs without a sufficiently friendly display alias;
- 5,604 canonical text resources across the resource families, plus 10 canonical text metadata documents;
- 10 authoritative gameplay-config documents with 578 semantic entries;
- 56 spawn stages;
- Quest Codex reference content: 88 quests, 14 bindings total, 13 supported;
- Mix Guide reference content: 127 recipes.

All nine pack files in the supplied `Content(5)` match the SHA-256 values declared by its current `BUILD.json`; current pack freshness therefore validates as `FRESH` for that supplied snapshot.

The localization production-publish gate remains **BLOCKED**. The supplied project evidence records `validate_legacy_localization_bridge.py` as `RESULT=FAIL`, with the expected runtime contracts `MultiByteToWideChar(CP_UTF8`, `WideCharToMultiByte`, and `return 1252u` missing. Editing and preview/validation remain available; production publish fails closed.

The supplied `Content(5)` archive contains the canonical content tree and packs but not `tools/content_port`. Consequently this environment can validate the live provider/catalog/census/current pack hashes and construct full-tree stages, but it cannot independently rerun the source validators/compilers after a mutation. Recompile/inspect of a modified stage remains a runtime gate against a configured Summit root that includes the canonical toolchain.

Release packaging gates after the V2.11 integration: `EN_LOCALIZATION=PASS`, JavaScript syntax `PASS`, `SNAPSHOT_MANIFEST_CHECK=PASS` (770 static files), and `PACKAGE_VERIFY=PASS`.


## Material Lab Fases 3–6 — 2026-10-20 (offline, pós-upscale)

- `texture-material` criado como pipeline 1× **sem novo upscale**; staging exclusivo, SHA-256, formatos TGA/BMP protegidos e preservação de alpha/cor-chave.
- Adaptador de modelos ESRGAN/DEDXT 1× por material preparado; necessita pesos `.pth`, runtime `torch>=2.6`/Spandrel ou CLI externa com hashes, ainda não exercitado com pesos reais.
- Mapas de height/normal DX/GL e demonstrador parallax são **offline**; não existe shader novo, integração de material ou autorização de parallax runtime.
- Auditoria SMD 0.62 é read-only; correções de normais/smooth-shading em `.blend` separado necessitam Blender e validação do exportador/corpo de prova. Nenhuma mesh foi modificada no cliente.
- Galeria HTML + importação de decisões human-in-the-loop com SHA-256. A aprovação não autoriza o deploy até serem certificados renderer e geometria.
- Testes: **70 PASS** focados em upscale + Material Lab + ações UI, integração e dependências; `node --check`: PASS; `VERIFY_PACKAGE.sh`: PASS após atualização do snapshot.
- Não foi executado nenhum lote de produção; não foram disponibilizadas as texturas já ampliadas nem as fontes do renderer do cliente nesta entrega.

Guia: `docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md`.


## Material Lab finalização offline e patch cumulativo — 2026-10-20

- Candidatos continuam a 1×, sem executar Real-ESRGAN 4× e sem escrita na origem ou cliente.
- Relatório de diferenças RGB/alpha, bordos (heurístico) e imagem de diferenças por candidato.
- Auditoria revalida input + output + mapas + revisão humana; alteração da origem invalida aprovação e exportação.
- Nova ação `export-approved`: copia candidatos aprovados e mapas com hashes para pasta disjunta **somente para teste offline**, `may_publish_to_client=false`.
- 75 testes selecionados de texture upscaling/restauro/Material Lab/interface interativa (inclui 6 testes finais) passaram. Testes de cliente em jogo, Blender e DEDXT com pesos reais **NÃO EXECUTADOS**.
- Patch cumulativo gerado contra a base original (`pt_asset_tool-main1(2).zip`), com instalador de verificações SHA-256, backups e rollback.
- Não se afirma parallax em tempo real, suporte de normais, exportação certificada de meshes ou publicação no cliente; os gates continuam bloqueados.
- Instruções: `docs/tematicos/MATERIAL_LAB_GUIA_FINAL_PATCH_CUMULATIVO.md`.

- Corrigida regressão preexistente na Fase 2: importação local de `re` em `ui_actions.build_command` interferia com validação de comandos de animação. Testes UI incluídos na bateria de 75.
