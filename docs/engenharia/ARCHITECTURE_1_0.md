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
- `VERIFY_PACKAGE.sh`: verifier estrutural da distribuição estática e da política fresh-install;
- `app/RUN_REGRESSION_FOCUSED.sh`: regressões focadas preservadas da linha RC;

## Núcleo

- `config.py`, `app_config.py`: discovery de roots e configuração machine-local em `pt_build/state`;
- `registry_bootstrap.py`: discovery físico e geração do registry da instalação atual;
- `resolver.py`: resolução case-aware;
- `registry.py`: assets/families/dependencies consumindo o registry gerado;
- `semantic_path.py`: classificação de navegação (não autoridade de writer);
- `certification.py`: journal machine-local em `pt_build/state/certifications`;
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
- particles: first-party `pt_asset_tool/particle_service.py` + bridges top-level `pt_part_*`, `pt_effect_*`; a UI principal é a superfície canônica e o standalone é compatibilidade.

## Release gates

`release_1_auto.py` agrega environment, server design, physical corpora/writers/codecs e coverage. `release_1_coverage.py` mantém a matriz de domínio/capability. O status de capability é separado de target-content readiness.

## Vendor

`summit_asset_enrichment_v9` é o único vendor ativo (`v9-fix136`). `vendor/` é reservado a código/dados upstream ou componentes externos versionados separadamente; módulos first-party como partículas, enhancement e editores pertencem ao core, mesmo quando possuem launcher próprio. O pacote não transporta cópias de vendors obsoletos.

## UI

`ui_catalog.py` indexa, `ui_capabilities.py` decide ações, `ui_actions.py` monta comandos allowlisted, `ui_jobs.py` gerencia jobs/reviews e `ui_app.py` serve API/UI local. O browser não monta shell arbitrário.

## Testes

- `app/dev_tests/`: contracts/corpus/regression tests;
- `app/tests/`: integration/source/UI tests adicionais;
- `RUN_REGRESSION_FOCUSED.sh`, `RUN_RELEASE_FAST.sh`: runners operacionais;
- gates reais podem exigir client/server/Blender externos.
