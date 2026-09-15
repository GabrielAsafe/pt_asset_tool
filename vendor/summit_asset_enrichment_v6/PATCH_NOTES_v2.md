# Summit Asset Enrichment v2 — post-first-run fixes

## Fixed

1. `collect_reverse_samples.py`
   - pool key now includes `label + side + resolved root + extension`;
   - prevents client/server roots with the same label (e.g. `exmachina`) from mixing;
   - archive paths now include the side: `samples/<label>/<side>/<relative-path>`.

2. `migrate_assets.py apply`
   - target absolute path is rebuilt from configured Summit root + `target_rel`;
   - existing directory casing is preserved case-insensitively (`tmABCD` vs `tmabcd`);
   - stale/edited manifest `target_path` is no longer trusted for writes;
   - target escape protection added;
   - error output is grouped by side/profile/detail and prints examples;
   - new `diagnose` command parses a previous `.apply.csv`.

3. `asset_common.py`
   - byte copy is atomic through a temporary file + `os.replace`;
   - legacy metadata copying is best-effort; metadata errors do not invalidate identical asset bytes;
   - binary reference extraction was rewritten to avoid catastrophic regex backtracking on long printable binary runs.

## Recovery after the user's first run

The previous run already copied 76 files. Do not delete them and do not use `--overwrite`.

First diagnose the previous log:

```bash
python3 migrate_assets.py --config summit_paths.json diagnose \
  manifests/migration_plan.apply.csv
```

Then, with the v2 files in place, safely retry the same manifest:

```bash
python3 migrate_assets.py --config summit_paths.json apply \
  manifests/migration_plan.csv
```

Anything copied previously will be `PRESERVE_EXISTING`; only still-missing AUTO rows are retried.

Then collect reverse samples:

```bash
python3 collect_reverse_samples.py --config summit_paths.json \
  --per-type 3 --out summit_reverse_samples.zip
```
