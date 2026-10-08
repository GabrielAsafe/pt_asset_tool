# PT Asset Tool Documentation

English is the default operator/developer documentation language as of the V2.10 localization layer.

Start here:

1. [`en/getting_started/INSTALLATION_QUICKSTART.md`](en/getting_started/INSTALLATION_QUICKSTART.md)
2. [`en/getting_started/USER_MANUAL.md`](en/getting_started/USER_MANUAL.md)
3. [`en/getting_started/GUI_MANUAL.md`](en/getting_started/GUI_MANUAL.md)
4. [`en/getting_started/CLI_REFERENCE.md`](en/getting_started/CLI_REFERENCE.md)
5. [`en/README.md`](en/README.md) — full English documentation map.

## Language and provenance policy

The first-party UI and operational documentation are English-first. Game display names from `priston_asset_name_map_v1.json` remain in the source game locale because they are data used for semantic matching, not UI labels.

Existing Portuguese documents under `comece_aqui/`, `engenharia/`, `cobertura_funcional/`, `tematicos/`, `release/`, and `validation/` are retained for historical provenance and compatibility with existing paths/scripts. New operator-facing references should use `docs/en/`.

Raw evidence, source excerpts, runtime identifiers, file paths, hashes, codes, and canonical IDs are never translated.

## Documentation validation

Current validation runbook: [`en/engineering/VALIDATION_RUNBOOK.md`](en/engineering/VALIDATION_RUNBOOK.md).

```bash
python3 docs/validation/validate_documentation.py
```

The package also includes localization-focused tests for the English UI/documentation surface.

## Source API inventory

The current exhaustive maintained first-party Python symbol reference is generated from the implementation at [`en/engineering/SOURCE_API_REFERENCE.md`](en/engineering/SOURCE_API_REFERENCE.md). Documentation validation fails when source and reference diverge.
