# PT Asset Tool — English Documentation

This directory is the default English documentation surface for PT Asset Tool.

## Start here

1. `getting_started/INSTALLATION_QUICKSTART.md`
2. `getting_started/USER_MANUAL.md`
3. `getting_started/GUI_MANUAL.md`
4. `getting_started/CLI_REFERENCE.md`
5. `getting_started/DEPENDENCIES.md`

## Functional coverage

- `functional/FEATURE_MATRIX.md`
- `functional/FORMATS_AND_WRITERS.md`
- `functional/SERVER_ENRICHMENT.md`
- `functional/RECOVERY_AGGREGATION_DEPLOYMENT.md`
- `functional/REPORTS_AND_OUTPUTS.md`
- `functional/SECURITY_AND_SAFETY.md`
- `functional/TROUBLESHOOTING.md`

## Engineering

- `engineering/ARCHITECTURE.md`
- `engineering/DEVELOPER_MANUAL.md`
- `engineering/MODULE_REFERENCE.md`
- `engineering/SOURCE_API_REFERENCE.md` — exhaustive AST-generated runtime Python symbol reference
- `engineering/VALIDATION_RUNBOOK.md`
- `engineering/SUMMIT_GAME_ASSET_ENRICHMENT.md`

## Topic guides

- `topics/DESIGN_TOOL.md`
- `topics/ASSET_ENRICHMENT.md`
- `topics/CLIENT_SERVER_WORKFLOW.md`
- `topics/LEGACY_MANAGEMENT_AUTHORING.md`
- `topics/SEMANTIC_AUTHORING_CATALOG.md`
- `topics/ASSET_CONTRACT_GRAPH.md`
- `topics/ASSET_RETENTION_AND_COOKED_DDS.md`
- `topics/ASSET_QUARANTINE_WORKFLOW.md`
- `topics/TEXTURE_UPSCALE_PIPELINE.md`
- `topics/EFFECTS_AND_PARTICLES.md`
- `topics/FIELD_METADATA_EDITOR.md`
- `topics/SUPERSET_AGGREGATOR.md`
- `topics/PORTABLE_APP.md`

## Release and validation

- `release/RELEASE_NOTES.md`
- `release/KNOWN_LIMITATIONS.md`
- `validation/LOCALIZATION_EN_V210.md`

## Language policy

The application UI and the operational documentation are English-first. Game-facing display names from the semantic catalog remain in their source locale when they are part of the game data contract. Internal IDs, file paths, runtime codes, hashes, and raw evidence are never translated.

The original Portuguese documentation is retained outside `docs/en/` for provenance and historical comparison. It is not the default operator documentation.
