# Documentação Autoritativa — PT Asset Tool R14 1.0.0

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

## Comece aqui

1. `comece_aqui/INSTALLATION_QUICKSTART_1_0.md`
2. `comece_aqui/MANUAL_UTILIZADOR.md`
3. `comece_aqui/GUI_MANUAL_1_0.md`
4. `comece_aqui/CLI_REFERENCE_1_0.md`

## Cobertura funcional completa

- `cobertura_funcional/FEATURE_MATRIX_1_0.md` — matriz de capability/estado/segurança;
- `cobertura_funcional/FORMATS_WRITERS_1_0.md` — Model0.62, Stage0.72, INX, SMB, textures, part, SPM/SPP/SPC;
- `cobertura_funcional/SERVER_ENRICHMENT_1_0.md` — server e Asset Enrichment;
- `cobertura_funcional/RECOVERY_AGGREGATION_DEPLOYMENT_1_0.md` — superset, recovery, build/deploy;
- `cobertura_funcional/REPORTS_OUTPUTS_1_0.md` — pt_build/evidence;
- `cobertura_funcional/SECURITY_SAFETY_1_0.md` — fail-closed e write authority;
- `cobertura_funcional/TROUBLESHOOTING_1_0.md` — problemas frequentes.

## Engenharia

- `engenharia/MANUAL_DESENVOLVEDOR.md` — engenharia + reverse engineering acumulado;
- `engenharia/ARCHITECTURE_1_0.md` — arquitetura atual;
- `engenharia/MODULE_REFERENCE_1_0.md` — inventário de módulos;
- `engenharia/MAPA_MODULOS_SCRIPTS.md` — mapa conceitual histórico/detalhado;
- `engenharia/REVERSE_ENGINEERING_FORMATOS.md` — formatos e descobertas históricas;
- `engenharia/SNAPSHOT_MANIFEST_POLICY.md` — integridade do pacote.
- `engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md` — runbook canónico de pytest, sintaxe, package verification e READY_TO_DEPLOY.
- `engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md` — arquitetura server-aware e bundles client/server.

## Release 1.0

- `release/RELEASE_NOTES_1_0.md`;
- `release/RELEASE_1_CERTIFICATION.md`;
- `release/RELEASE_1_READINESS.md`;
- `release/KNOWN_LIMITATIONS_1_0.md`;
- `release/FINAL_CERTIFICATION_EVIDENCE.md`;
- `release/RELEASE_1_AUTO_FINAL_RESULT.json`.

## Guias temáticos preservados

- `tematicos/GUIA_DESIGN_TOOL.md`;
- `tematicos/GUIA_ASSET_ENRICHMENT.md`;
- `tematicos/GUIA_WORKFLOW_CLIENT_SERVER.md`;
- `tematicos/FIELD_METADATA_EDITOR.md`;
- `tematicos/EFFECTS_PARTICLES.md`;
- `tematicos/SUPERSET_AGGREGATOR.md`;
- `tematicos/ASSET_CONTRACT_GRAPH.md`;
- `tematicos/ASSET_RETENTION_AND_COOKED_DDS.md` — retenção fail-closed, Monster/NPC bundle/catalog guards e integração do manifest DDS cooked/failures;
- `tematicos/TEXTURE_UPSCALE_PIPELINE.md` — upscale seguro BMP/TGA/PNG/JPG com staging em `pt_build`;
- `tematicos/LEGACY_MANAGEMENT_AUTHORING.md` — Management Legacy, World Closure e pipeline Python de ITEM/MONSTER/NPC/SPM/SPP/SPC com publish/restore transacional.
- `tematicos/SEMANTIC_AUTHORING_CATALOG.md` — catálogo nome visível → canonical_id/path para ITEM/MONSTER/NPC/MAP e relações SPM/SPC;

## Evidência e histórico

- `validation/INTEGRATION_ASSET_RETENTION_COOKED_DDS_2026-09-27.md` — evidência dos gates da integração retention + DDS failure metadata.
- `validation/INTEGRATION_ASSET_RETENTION_COOKED_DDS_V23_2026-09-27.md` — revisão 3 de metadata: skips válidos, integrity_action e residual failures sem override de reachability.

O pacote distribui apenas documentação atual, os patch notes de validação desta revisão e a evidência final necessária da Release 1. Backups, handoffs intermediários e relatórios RC substituídos ficam no histórico Git, não na instalação operacional.

A atualização 2026-09-21 de `MANUAL_UTILIZADOR.md`, `GUI_MANUAL_1_0.md` e `LEGACY_MANAGEMENT_AUTHORING.md` documenta a camada Legacy Authoring.

Os documentos `*_1_0.md`, `CURRENT_READINESS.json`, `VALIDATION_STATUS.md` e `release/RELEASE_1_CERTIFICATION.md` são as referências autoritativas do estado atual.


## Validação da própria documentação

```bash
python3 docs/validation/validate_documentation.py
```

A gate verifica o runbook canónico, newlines escapados acidentalmente e o runtime root atual do Texture Upscale.

- `validation/INTEGRATION_ASSET_RETENTION_ROOT_REACHABILITY_V24_2026-09-27.md` — separação entre ContractGraph linkage e strong-root reachability, com consulta CLI curta por asset.

- `validation/INTEGRATION_EFFECT_RUNTIME_COMPONENTS_V25_2026-09-27.md` — cobertura de roots de efeitos via loaders legacy e agrupamento de componentes graph-linked sem strong root.

- `tematicos/ASSET_QUARANTINE_WORKFLOW.md` — plano Q0/Q1, apply reversível, hash preflight e restore sem delete.
- `validation/INTEGRATION_ASSET_QUARANTINE_V26_2026-09-27.md` — gates do workflow de quarantine V2.6.
- `validation/INTEGRATION_ASSET_QUARANTINE_Q1_RANK_V27_2026-09-27.md` — ranking read-only dos componentes Q1.
- `validation/INTEGRATION_ASSET_QUARANTINE_Q1_MANUAL_V28_2026-09-27.md` — quarantine manual, explícita e reversível de um único Q1 estritamente elegível.

- `validation/INTEGRATION_ASSET_QUARANTINE_Q1_RANK_V27_2026-09-27.md` — ranking read-only da fila Q1 por componente; sem move/delete de Q1.

- `validation/INTEGRATION_LEGACY_AUTHORING_NAME_CATALOG_V29_2026-09-28.md` — gates do catálogo semântico integrado ao Legacy Authoring.
