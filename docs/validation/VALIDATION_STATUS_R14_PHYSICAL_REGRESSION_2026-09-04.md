# PT Asset Tool R14 — physical regression gate status — 2026-09-04

## Environment evidence received

The physical `validate environment-auto` report is PASS with `environment_ready=true`, Blender 5.2.0 LTS headless filesystem bridge PASS, certified rare-writer hashes PASS, six physical client samples unchanged, and client writes disabled.

## Development completed after environment PASS

- Added source-aware static representative backfill so Release 1 does not spend witnesses on static assets with no current saved-Blender candidate objects.
- Added motion-owning INX selection for bound animation pose witnesses; e.g. `char/tmABCD/MfbC01.smd` now selects `M5Bip.inx`/`m5.smb` rather than an unrelated geometry/model-info INX.
- Added fail-closed standalone rigid TexLink path for an exact sibling SMB: filename is only a hypothesis and must pass the existing structural gate before Blender import/reimport.
- Added conservative legacy-degenerate support to the generic rigid writer: only a degenerate export triangle whose exact source polygon/vertex set was already degenerate is allowed; new degeneracy fails. Vertices with no non-degenerate adjacent face may reuse only the exact source-bone-proven source normal direction.
- Added pose diagnostics to failed bound and standalone animation batch rows.
- Added `validate physical-regression-auto`, a focused client gate using historical failures plus current representatives.

## Local validation

- `python3 -m compileall -q .`: PASS.
- Non-fixture dev tests: 186/186 PASS in two reproducible batches (163 + 23).
- Four certified rare-writer SHA-256 values unchanged.
- `VERIFY_PACKAGE.sh`: PASS.

## Next physical gate

Run from `app/`:

```bash
python3 pt_asset.py --client-root "/path/to/client" validate physical-regression-auto
```

Report: `pt_build/devtest/physical_regression_auto/result.json`.

This gate is intentionally smaller than the full Release-1 gate. A PASS means return to `validate release-1-auto --resume`; it does not authorize production or client writes.
