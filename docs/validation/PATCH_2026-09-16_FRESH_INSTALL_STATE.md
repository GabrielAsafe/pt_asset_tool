# Patch 2026-09-16 — Fresh install and runtime-state separation

## Goal

Make a clean PT Asset Tool checkout independent of state generated on the development machine. Static code/reference data stays in the package; client-derived inventory, configuration, certifications, caches and runtime evidence are generated per installation under `app/pt_build/`.

## Removed packaged state

The package no longer ships:

- `app/data/asset_registry/asset_inventory.json`;
- `app/data/asset_registry/inx_physical_pairing.csv`;
- `root_skeleton_bindings_v7.json` and the broken `smb_skeleton_signatures_v1.json` cache;
- `app/certifications/assets.jsonl`;
- generated canonical character-profile instances;
- development witness state;
- `app/pt_asset_app_config.json`;
- root/app historical backup trees and obsolete RC verifier copies.

The old SMB signature cache was intentionally removed rather than migrated: 955 of 958 stored entries represented parser errors, so preserving it would preserve failed historical state rather than useful evidence.

## Generated runtime registry

`pt_asset_tool.registry_bootstrap` now scans the configured current client read-only and writes machine-local registry state to:

```text
app/pt_build/state/asset_registry/
  asset_inventory.json
  inx_physical_pairing.csv
  registry_meta.json
```

The bootstrap rebuilds Model0.62 structural metadata, Stage0.72 metadata, INX groups/references, texture/config/support-file classification and INX physical pairing from the current client. `Settings.discover()` bootstraps the registry when it is missing; `python3 pt_asset.py registry rebuild` forces a rebuild explicitly.

The registry source tree is never modified.

## Other migrations

- active code formerly hidden under `history_py/` moved to `pt_asset_tool/legacy_runtime/`;
- canonical Pikeman/Priestess profiles moved to `dev_tests/fixtures/character_profiles/` and are no longer runtime requirements;
- the Monster/NPC semantic catalog moved to `data/reference/entity_catalog/` and remains optional enrichment of the live physical catalog;
- certification state moved to `pt_build/state/certifications/`;
- local app configuration moved to `pt_build/state/pt_asset_app_config.json`;
- external development witnesses are consumed only from `pt_build/state/development_evidence/`.

## Fresh-install policy

`VERIFY_PACKAGE.sh` now rejects packaged machine-local/generated state and historical backup trees. `SNAPSHOT_MUTABLE_PATHS.txt` is comment-only because all mutable state lives under `pt_build`, which is excluded from the static snapshot.

Corpus tests that require the real game client use the generated runtime registry and skip when no client exists; synthetic/unit tests remain self-contained and mandatory. Historical RC tests are retained as regression tests and exposed through `app/RUN_REGRESSION_FOCUSED.sh` rather than through a frozen historical verifier.

## Additional cleanup and contract fixes

- the root-skeleton cache remains generated on demand beside the runtime registry and now consistently declares `PT_ROOT_SKELETON_BINDINGS_V7` (the old helper still emitted a V6 format label);
- `history/`, `app/history/`, root `evidence/`, obsolete RC runner/verifier copies, intermediate `VALIDATION_STATUS_R*` documents and `docs/togpt_dont_bother_reading/` are removed from the distributed tree; Git remains the archive for those intermediate states;
- only the final Release 1 certification evidence is kept as immutable historical evidence under `docs/release/` and `docs/evidence/`;
- the active Summit enrichment specification was retained under `docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md`;
- the v9 vendor keeps active static audit/reference datasets used by its graph/migration logic, but old v2-v8 patch-note files, v3 diagnosis and v7 intermediate reports are removed; its package manifest is regenerated from the files actually shipped;
- `.gitignore` excludes `app/pt_build/` and Python/test caches, so first-run state does not pollute source-control status.

## Certified writer recertification

Moving the still-active legacy Blender importer from `history_py/` to `pt_asset_tool/legacy_runtime/` changes import lines in two certified writers without changing their writer logic. The integrity contract is centralized in `pt_asset_tool/certified_writers.py` and recertified as:

```text
rare_rigid_edit.py                 3ff2769bbc9762c04fb992fbad52ba7d60ae6a53f19c22d4f1d68e274697eec3
rare_rigid_multivertex.py          0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991
rare_rigid_multibone_bridge.py     010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0
rare_rigid_normal_bridge.py        2c0f75931e54a72cd87be2bc6694370f849c24c3f2b4b44afbdbc288dcaf622c
```

## Regression status

On a fresh source checkout without the external game corpus or Blender installed:

```text
dev_tests:               315 passed, 102 skipped
app/tests:                97 passed, 119 skipped
RUN_REGRESSION_FOCUSED:   40 passed, 1 skipped
```

Skips are reserved for tests that explicitly require an external real-client corpus or a generated payload. No test file was removed to obtain these results.
