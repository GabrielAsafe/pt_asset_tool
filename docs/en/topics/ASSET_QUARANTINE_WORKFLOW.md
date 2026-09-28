# Asset Quarantine Workflow

Quarantine is reversible staging outside the runtime client. It is not deletion.

## Q0

Q0 is intentionally narrow. Eligibility requires a documented invalid/non-runtime outlier with zero graph linkage, zero root reachability, zero positive evidence, and no entity-bundle protection.

## Q1 review

Root-unreachable graph components receive review bands `A`, `B`, `C`, or `BLOCKED`. The score is review priority only.

`BLOCKED` is used when positive retention/entity evidence exists.

## Manual Q1 component quarantine

A component is manually movable only through the dedicated exact-component command and strict eligibility gates. Current safeguards include:

- band A;
- exact component ID;
- small maximum component size;
- zero protected/entity/positive-evidence members;
- zero external incoming/outgoing edges;
- at least one documented invalid member;
- physical member manifest with bytes/SHA-256;
- explicit confirmation phrase;
- transactional move and restore journal.

## Commands

```bash
python3 app/pt_asset.py audit quarantine-plan
python3 app/pt_asset.py quarantine review --band A --limit 50
python3 app/pt_asset.py quarantine review --component URC-02537
```

Manual component move:

```bash
python3 app/pt_asset.py quarantine apply-component \
  --component URC-02537 \
  --confirm MOVE_Q1_COMPONENT_TO_QUARANTINE
```

Restore:

```bash
python3 app/pt_asset.py quarantine restore \
  --confirm RESTORE_QUARANTINE
```

Deletion remains unauthorized.
