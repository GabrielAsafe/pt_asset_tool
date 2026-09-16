# PT Asset Tool R14 1.0.0 — Arquitetura

## Camadas

```text
pt_asset.py (consolidação/compatibilidade)
        |
        +--> pt_asset_tool.cli (parser/dispatch certificado)
        +--> pt_asset_gui.py / ui_app.py (UI local)
        +--> forensic/legacy workflow intercepts

Registry / resolver / config
        |
        +--> parsers e semântica de formatos
        +--> census / source evidence / server evidence
        +--> validators / corpus gates
        +--> Blender bridges
        +--> candidate writers
        +--> build provenance / deployment planning
        +--> release gates

Todos os outputs mutáveis -> app/pt_build
Target client/server -> read-only por padrão
```

## Entrypoints

- `app/pt_asset.py`: launcher consolidado 1.0 e compatibilidade histórica;
- `app/pt_asset_core_v0_8_9.py`: core wrapper;
- `app/pt_asset_gui.py`: UI local;
- `app/pt-asset-gui`: launcher shell;
- `app/pt_rc6_12_verify.py`: certificação estrutural do pacote;
- `VERIFY_PACKAGE.sh`: verifier de distribuição.

## Núcleo

- `config.py`, `app_config.py`: discovery/persistência de roots;
- `resolver.py`: resolução case-aware;
- `registry.py`: assets/families/dependencies;
- `semantic_path.py`: classificação de navegação (não autoridade de writer);
- `certification.py`: journal;
- `validation.py`: execução de gates;
- `workflow_dispatch.py`: build routing fail-closed;
- `build_provenance.py`: source/artifact hashes e sidecars;
- `deployment.py`: transações planejadas/simuladas.

## Evidence

- `source_catalog.py`, `source_evidence.py`, `source_contract_census.py`, `skill_contract_census.py`;
- `server_inventory.py`, `server_bundle_census.py`, `server_field_census.py`, `server_item_census.py`;
- `general_asset_census.py`, `contract_graph.py`, `client_manifest_evidence.py`.

## Format families

- Model0.62: `model062_*`, rigid/static/object-local/TexLink/material modules;
- Stage0.72: `stage072_*`;
- motion: `motion_core.py`, `inx_writer.py`, `smb_writer.py`, animation modules;
- texture: `texture_codec_devtest.py`, `texture_overlay.py`;
- rare rigid: `rare_rigid_*`;
- particles: top-level `pt_part_*`, `pt_effect_*`.

## Release gates

`release_1_auto.py` agrega environment, server design, physical corpora/writers/codecs e coverage. `release_1_coverage.py` mantém a matriz de domínio/capability. O status de capability é separado de target-content readiness.

## Vendor

`summit_asset_enrichment_v9` é o vendor ativo (`v9-fix136`). v6 é referência histórica.

## UI

`ui_catalog.py` indexa, `ui_capabilities.py` decide ações, `ui_actions.py` monta comandos allowlisted, `ui_jobs.py` gerencia jobs/reviews e `ui_app.py` serve API/UI local. O browser não monta shell arbitrário.

## Testes

- `app/dev_tests/`: contracts/corpus/regression tests;
- `app/tests/`: integration/source/UI tests adicionais;
- `RUN_RC6_12_LOCAL_FOCUSED.sh`, `RUN_RELEASE_FAST.sh`: runners operacionais;
- gates reais podem exigir client/server/Blender externos.
