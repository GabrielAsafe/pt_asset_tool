# R12 manual test — second rigid controlled-edit witness

Goal: create a **new R12 provenance artifact** and review the **reimported candidate output**, not only the edited source `.blend`.

## 1. Import Priestess/default

```bash
cd "/home/gabriel/Transferências/PT_Asset_Tool_dev_snapshot_2026-09-02_r12_autonomous/app"

python3 pt_asset.py import "char/tmABCD/MfbC01.smd" \
  --profile priestess_c01_m5 \
  --lod default
```

Edit **only `MsmC01`**. For this witness, move one existing vertex slightly. Do not add/delete topology, rename objects, change material IDs, skeleton, or another object. Save `imported.blend`.

## 2. Build controlled candidate

```bash
python3 pt_asset.py build "char/tmABCD/MfbC01.smd" \
  --candidate \
  --object MsmC01 \
  --require-edit
```

Expected essentials:

```text
status=PASS
authorization=CANDIDATE_PT_BUILD_ONLY
verification.edit_observed=true
verification.non_target_changed=[]
verification.unknown_physique_bones=[]
verification.errors=[]
production_authorized=false
client_write_authorized=false
client_modified=false
```

Default artifact path:

```text
pt_build/candidate_build/char__tmABCD__MfbC01/MfbC01.smd
```

## 3. Reimport the candidate itself for human review

```bash
python3 pt_asset.py view rigid-candidate "char/tmABCD/MfbC01.smd" \
  --artifact pt_build/candidate_build/char__tmABCD__MfbC01/MfbC01.smd
```

This opens a different `.blend` under `pt_build/candidate_review/...`. Review the **candidate reimport**, especially:

- the intended `MsmC01` vertex move is present;
- the mesh has no visible corruption;
- body parts remain aligned;
- rig/binding does not visibly explode;
- materials/textures load plausibly.

The exact review question in the manifest is:

> Does the reimported candidate output preserve the intended edited geometry, rig binding and materials without visible corruption?

## 4. Record the review

Only after inspecting the candidate reimport:

```bash
python3 pt_asset.py certification rigid-candidate-review "char/tmABCD/MfbC01.smd" \
  --artifact pt_build/candidate_build/char__tmABCD__MfbC01/MfbC01.smd \
  --result PASS \
  --notes "R12 MsmC01 single-vertex candidate reimport reviewed in Blender"
```

Use `FAIL` rather than forcing PASS if anything looks wrong; `SKIP` is valid if review is inconclusive.

## 5. Show coverage

```bash
python3 pt_asset.py audit rigid-authoring-certification-plan \
  --profile priestess_c01_m5
```

Expected after a successful R12 test:

- historical `MbmC01/default`: `external_real_blender_reported=true`, but not automatically counted as locally reverified R12 evidence;
- new `MsmC01/default`: `controlled_edit_proven=true`, `human_review_result=PASS`, `context_pass=true`;
- every row still has production authorization false.

Do **not** deploy/apply the candidate to the client.
