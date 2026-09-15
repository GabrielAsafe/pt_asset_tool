# Autonomous continuation — 2026-09-02

This file records the autonomous continuation performed after the received `r7_current` snapshot. Read it after `RETOMADA_DESENVOLVIMENTO.md`; it supersedes the immediate gap described there around rigid multi-INX authoring identity.

## Completed in this continuation

1. Added an explicit rigid `selected_context` identity to authoring workspaces:
   - logical + physical `model_info_inx` identity (path, size, SHA-256);
   - logical + physical `skeleton_smb` identity (path, size, SHA-256);
   - effective LOD;
   - normalized full `high/default/low` `lod_groups`;
   - canonical SHA-256 signature of those `lod_groups`;
   - selected LOD node list.
2. Rigid authoring manifests are now fail-closed when `selected_context` is missing or drifts.
3. Rigid candidate build planning revalidates the manifest context against the current registry and resolver before becoming `READY`.
4. Candidate rigid `*.build.json` provenance now carries and revalidates `selected_context`.
5. Deployment planning/transaction preparation carries the selected context forward, snapshots build provenance, and transaction verification rechecks context drift/snapshot consistency.
6. Rigid import now uses the skeleton SMB associated with the selected INX config and persists the exact context used to create the Blender workspace.
7. Multi-INX equivalence was tightened: automatic selection is only allowed when the complete skeleton + full LOD group semantics are equivalent, rather than merely matching the currently auto-selected LOD.
8. Added `audit rigid-model-info-contexts`, a read-only audit that classifies multi-INX rigid assets as `SEMANTICALLY_EQUIVALENT` or `AMBIGUOUS_MODEL_INFO_CONFIG` and marks ambiguous assets as requiring explicit `--model-info`.

## Safety/policy preserved

- No client write path was enabled.
- `deploy apply` remains absent.
- Candidate writer output remains `pt_build` only.
- No production writer was promoted.
- The four certified rare-rigid writers were not modified and their SHA-256 hashes remain exactly the frozen values.

## Validation performed

- 52/52 reproducible focused/dev tests passed in this snapshot environment.
- Historical/maintained suite: 175 PASS / 1 SKIP using a temporary test-only `payload -> .` compatibility symlink, removed immediately after the run.
- A broader dev batch produced 36 PASS and 8 failures solely because `fixture_client` is intentionally absent from this snapshot; those failures were `FileNotFoundError` for that missing external fixture, not assertion/regression failures.
- Python `compileall`: PASS.
- JavaScript `node --check`: PASS.
- shell `bash -n`: PASS.
- CLI parser/version smoke: PASS (`0.12.0`, new audit command present).

## Certified writer hashes rechecked

```text
229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42  pt_asset_tool/rare_rigid_edit.py
0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991  pt_asset_tool/rare_rigid_multivertex.py
010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0  pt_asset_tool/rare_rigid_multibone_bridge.py
67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96  pt_asset_tool/rare_rigid_normal_bridge.py
```

## Exact next step

Run the new read-only audit on the real configured client/registry:

```bash
python3 pt_asset.py audit rigid-model-info-contexts --sample-limit 0 --output pt_build/audits/rigid_model_info_contexts.json
```

Then inspect every `AMBIGUOUS_MODEL_INFO_CONFIG` row and use explicit `--model-info` for affected imports. After that, the next evidence-producing tasks remain the real Blender corpus execution of static/rigid/Stage candidates and representative animation pose-space review. Those cannot be truthfully certified from this snapshot alone because the real client/fixture/bundles and Blender runtime evidence are not included.
