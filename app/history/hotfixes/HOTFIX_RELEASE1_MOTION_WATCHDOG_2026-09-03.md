# Release 1 motion semantic watchdog/checkpoint hotfix — 2026-09-03

## Trigger

The real-client `validate release-1-auto --resume` run progressed normally through
`MOTION_SEMANTIC 475/494` and then stopped producing progress.  The previous
implementation executed `_semantic_inx_edit` and `_semantic_smb_edit` directly in
the main process with no per-operation watchdog and only logged every 25 contexts.
One pathological physical INX/SMB context could therefore stall the entire Release
1 gate indefinitely, and completed semantic rows were not persisted until all 494
contexts returned.

## Changes

- print START/DONE for every motion-semantic context;
- POSIX wall-clock watchdog per INX writer operation and per SMB writer operation;
- default watchdog: 120 seconds per writer (CLI `--motion-semantic-timeout`);
- timeout is fail-closed for that writer/context and the corpus continues;
- source INX/SMB SHA-256 is checked before/after every temporary edit;
- append-only checkpoint under
  `pt_build/devtest/release_1_auto/motion_semantic_checkpoint.jsonl`;
- `--resume` reuses only completed PASS/SKIP semantic rows whose exact INX and SMB
  SHA-256 still match;
- FAIL/TIMEOUT rows are never reused and are retried;
- an `*.in_progress.json` marker identifies the exact context if the process is
  externally killed or crashes;
- candidates remain temporary/pt_build only; no client or production write is
  authorized by this hotfix.

## Validation in handoff environment

- `python3 -m compileall -q pt_asset_tool dev_tests`: PASS
- `dev_tests/test_release_1_auto.py`: 27 PASS
- new checkpoint/timeout/pair-limit tests: 3 PASS
- broader tests that require `/mnt/data/fixture_client` still fail only because that
  physical fixture is absent from this handoff environment, matching the existing
  R14 limitation.

## Real-client command

After stopping the old hung process, unzip this hotfix over the existing `app/`
and keep `pt_build`. Then run:

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  validate release-1-auto --resume
```

The default 120-second watchdog is intentionally conservative.  A timeout is
reported as a Release 1 blocker; it is not converted to PASS.
