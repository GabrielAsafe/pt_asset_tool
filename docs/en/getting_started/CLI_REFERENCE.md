# CLI Reference

The authoritative command list is always available from the parser:

```bash
cd app
python3 pt_asset.py --help
```

Use subcommand help for the exact options of the installed version:

```bash
python3 pt_asset.py audit --help
python3 pt_asset.py quarantine --help
python3 pt_asset.py quarantine apply-component --help
```

## Common configuration

```bash
python3 pt_asset.py \
  --client-root "/path/to/Summit/client" \
  --server-root "/path/to/Summit/Server" \
  <command>
```

Only use the actual server root. Do not guess a server path.

## Asset retention

Generate the authoritative retention projection through General Census / retention audit:

```bash
python3 pt_asset.py \
  --client-root "/path/to/client" \
  --server-root "/path/to/server" \
  audit asset-retention \
  --source-root "/path/to/SourceCode"
```

Query the persisted retention result without rerunning census:

```bash
python3 pt_asset.py audit asset-retention-query \
  --path 'Effect/AssaEffect/MonsterFury/m_fury.tga'
```

Other useful filters include state, family, substring query, component, offset, and limit where supported by the installed version.

## Effect runtime coverage

```bash
python3 pt_asset.py \
  --client-root "/path/to/client" \
  audit effect-runtime-coverage \
  --source-root "/path/to/SourceCode"
```

This resolves known effect-loader roots and produces root-unreachable component evidence.

## Quarantine plan

```bash
python3 pt_asset.py audit quarantine-plan
python3 pt_asset.py quarantine status
python3 pt_asset.py quarantine review --band A --limit 50
```

Q0 apply is explicit and reversible:

```bash
python3 pt_asset.py quarantine apply \
  --confirm MOVE_Q0_TO_QUARANTINE
```

Manual Q1 component quarantine requires the V2 plan format and exact component ID:

```bash
python3 pt_asset.py quarantine review --component URC-02537

python3 pt_asset.py quarantine apply-component \
  --component URC-02537 \
  --confirm MOVE_Q1_COMPONENT_TO_QUARANTINE
```

Restore:

```bash
python3 pt_asset.py quarantine restore \
  --confirm RESTORE_QUARANTINE
```

There is no automatic delete authority in these workflows.

## Dependency diagnostics

```bash
python3 pt_asset.py dependencies
```

## Package validation

From the package root:

```bash
./VERIFY_PACKAGE.sh
```

For development validation use the English runbook in `docs/en/engineering/VALIDATION_RUNBOOK.md`.
