# R11 manual test — Priestess rigid saved-Blender candidate

This test is intentionally candidate-only and must not write the client.

## 1. Confirm the saved profile/LOD scope

```bash
python3 pt_asset.py import "char/tmABCD/MfbC01.smd" \
  --profile priestess_c01_m5 \
  --lod default \
  --no-open

python3 pt_asset.py build "char/tmABCD/MfbC01.smd" --plan
```

Expected `candidate_scope`:

```text
selected_lod = default
eligible_objects = [MbmC01, MsmC01, MlmC01]
selection_required = true
manifest_verification_status = PASS
status = READY
```

## 2. Make one minimal controlled edit

Open the workspace `.blend` and edit only `MbmC01`.

Recommended first witness: move one existing vertex by a very small amount. Do not delete/add vertices or faces, do not rename the object, do not change material assignment, and do not edit the armature.

Save the `.blend`.

## 3. Build the candidate and require real edit evidence

```bash
python3 pt_asset.py build "char/tmABCD/MfbC01.smd" \
  --candidate \
  --object MbmC01 \
  --require-edit
```

Desired result:

```text
status = PASS
candidate_kind = RIGID
verification.status = PASS
verification.edit_required = true
verification.edit_observed = true
verification.non_target_changed = []
verification.unknown_physique_bones = []
production_authorized = false
client_write_authorized = false
client_modified = false
```

If `TARGET_EDIT_NOT_OBSERVED` appears, the candidate remained byte-identical for the target and the Blender edit did not reach the writer output. Do not weaken this gate.

If any non-target block changed or an unknown Physique bone appears, treat it as a real failure and keep the writer unpromoted.

Do not run deploy/apply.
