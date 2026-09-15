<!-- PT_ASSET_RELEASE_1_0_FINALIZATION_V1 -->

**Release state:** 1.0.0 certified for PT Asset Tool scope; production writes remain safety-locked.

# Current release note — 1.0.0 (14/09/2026)

Asset Enrichment v9 Fix136 is active; Field SPM/SPP/SPC staging and Effects `.part` preview are integrated. Static writer remains blocked by physically observed multi-normal divergence and requires topology-aware loop/corner selection. No production/client/server write authorization is enabled.

---

# PT Asset Tool — Development Snapshot 2026-09-02 R12

Internal application version remains `0.12.0`. This is an **unreleased development snapshot**, not a promoted V1 build.

R12 incorporates the first real-Blender controlled edit reported for the generic rigid saved-Blender candidate: `priestess_c01_m5`, `lod=default`, object `MbmC01`. The R11 candidate reported `edit_observed=true`, preserved all 14 non-target object blocks byte-identically, kept file size/counts stable, resolved all Physique bones, and remained candidate-only. R12 does **not** promote production from that single witness; it adds structured/revalidatable candidate evidence, explicit human-review recording, and a profile/LOD/object certification coverage plan.

R10 incorporates real manual R9 client/Blender evidence: rigid multi-INX ambiguity and selected-context guards passed; a `Bcn02f.inx` reset exposed LOD names absent from its associated SMD, so generic rigid import now performs host-side INX-LOD→SMD NodeName coverage preflight before Blender and before destructive workspace reset. App-level client discovery was also aligned with the historical layout already used by `Settings.discover()`/doctor. No production authorization changed.

## Added / changed in this development line

- folder/entity facet in the catalog (`Category → Folder → Role → Extension`);
- granular NPC/Monster roles: `MODEL`, `CONFIG`, `ANIMATION`, `TEXTURE`, `AUDIO`, `SOURCE_3D`, `SUPPORT`;
- human-readable extension descriptions;
- UI semantic taxonomy for documented physical trees such as `StartImage`, `Inter/Chat`, `ButtonInfo`, `sinGage`, `SkillIcon`, `ReStart` and item icon trees;
- UI path precedence corrected so `StartImage/Opening/npc` and `Image/Sinimage/NPC` stay frontend/UI assets instead of polluting runtime NPC coverage;
- distinction between inventory item icons and `DropItem` world assets;
- Monster/NPC physical entity catalog with representative preview/model and fail-closed runtime/writer status;
- GUI `Entidades` tab backed by `/api/entities` plus detailed entity evidence;
- canonical entity seed from the supplied physical client tree: 351 entities (267 Monster, 84 NPC);
- entity detail now includes registry families, resolved bindings, physical dependency readiness and pairing-proven cross-folder relations without merging entities by name;
- UI tree evidence summary from the supplied `Image/Sinimage` + `StartImage` tree;
- generic Blender import workspace dispatcher;
- fail-closed generic build dispatcher;
- R12 rigid candidate provenance now records target object, selected LOD/profile, edit-observed state, non-target drift, unknown Physique bones, verification errors, structural counts and writer identity;
- `certification rigid-candidate-review` revalidates a R12 candidate artifact/provenance/source/context before recording separate automatic controlled-edit evidence and explicit human PASS/FAIL/SKIP;
- `view rigid-candidate` reimports the candidate SMD itself with the pinned INX+skeleton+LOD into a separate `pt_build/candidate_review` Blender workspace, so human review is performed on writer output rather than only on the edited input `.blend`;
- `audit rigid-authoring-certification-plan` reports canonical profile/LOD/object coverage without treating external logs as locally reverified certification;
- the first real-Blender Priestess/default/MbmC01 witness is retained as `PASS_REPORTED` development evidence, explicitly below runtime/production promotion;
- candidate INX MotionInfo writer (`pt_build` only), now preservation-aware for valid non-canonical encoded frame representations;
- INX no-op corpus proof: 542/542 supplied NPC/Monster INX byte-identical, covering 531 `MODERN_172` and 11 `LEGACY_120` files;
- INX corpus contained 73 files / 100 records with valid non-canonical start encodings; source representation is preserved rather than normalized;
- controlled INX candidate edit probe: 542/542 supplied files reparsed with file size and byte allowlist preserved;
- candidate SMB key writer (`pt_build` only), with binary layout parsing separated from closed-hierarchy animation evaluation;
- SMB no-op corpus proof: 18/18 supplied SMB byte-identical; one support skeleton (`Ahinf.smb`) has an external parent and is preserved without weakening animation hierarchy validation;
- controlled SMB candidate edit probe: 14 editable-key files passed, 4 files had no editable keys, 0 failures;
- new read-only `audit inx-writer-corpus` and `audit smb-writer-corpus` commands for reproducible candidate-writer evidence on a configured client;
- reproducible `audit inx-writer-edit-corpus` / `audit smb-writer-edit-corpus` now formalize the previously ad-hoc controlled-edit proof using temporary outputs only; deep readiness can promote evidence to `CANDIDATE_EDIT_CORPUS_PROVEN`, never to production.
- animation source-side regression gate;
- new deduplicated `audit animation-corpus` reuses registry-proven INX/SMB contexts, separates semantic registry coverage from physical fixture/client coverage and never promotes visual/binding status;
- `audit animation-certification-plan` turns physical animation contexts into a deterministic human Blender review queue covering semantic groups/layouts/core motion states without automatic certification.
- canonical character/LOD profile registry;
- `profiles verify` validates canonical profile components against the configured client and cross-checks exact registry target, skeleton, INX and LOD groups without authorizing writes;
- `profiles discover` expands LOD/profile evidence beyond the two canonical profiles: current registry discovery finds 1,940 asset+INX candidates, of which 55 are structurally candidate-ready and one is already canonical/runtime-proven; discovery remains authoring-disabled.
- exact-path profile matching is exposed through `asset inspect` and GUI asset detail;
- `audit binding-coverage` now reports every unresolved rigid binding mode, not only `CONFIG_ONLY`;
- binding coverage classifies known frontend/UI roots separately from runtime NPC/Monster trees;
- supplied corpus result after that correction: runtime NPC rigid coverage 95/96 resolved; the remaining `Bcn05_` model stays fail-closed while pairing evidence points to the separate `Bcn05` entity;
- GUI suppresses rigid Blender/motion actions when required INX/SMB dependencies are physically missing;
- Stage0.72 stages 0–7 exposed by the UI action flow;
- Stage0.72 fixture regression split into fast representative coverage and opt-in full corpus coverage;
- preview-only recovery for the already-documented recoverable TGA outlier;
- application smoke checks UI taxonomy, entity catalog, candidate writer contracts, profile registry and binding coverage contracts;
- development tests collect directly from the project root without requiring manual `PYTHONPATH=.`;
- normal `assets list` is now identity-focused; historical certification columns are opt-in with `assets list --gates`, with an explicit PENDING/N/A/binding legend;
- new `explain` command documents statuses, bindings, structural, visual, roundtrip, object-local, TexLinks and desktop launcher semantics directly in the CLI;
- Monster/NPC census first-run now creates a missing semantic census automatically and fixes the consolidated `--client-root` refresh routing bug;
- interactive Blender validators are available from the GUI through a constrained PASS/FAIL/SKIP stdin bridge; arbitrary stdin is rejected and answers are accepted only after a real review prompt is emitted;
- GUI review controls now display the exact pending human-review question, preventing ambiguity in multi-gate validations;
- animation UI supports motion, selected/core/all Action loading and verified head/tier selection; CLI prints selected versus loaded Actions so `--load-actions all` is no longer mistaken for simultaneous playback;
- GUI exposes verified `Cabeças compatíveis` when the registry can prove head candidates for the selected body/root;
- object-local and TexLink errors now explain the narrower family/source-shape requirements and point to the appropriate generic inspection path;
- application smoke includes an explicit interactive-review UI contract.
- developer documentation rewritten around reverse-engineering evidence rather than user-operation instructions;
- new `REVERSE_ENGINEERING_FORMATOS.md` records proven binary sizes/offsets and preservation rules;
- new `MAPA_MODULOS_SCRIPTS.md` explains runtime, audit, Blender, research, candidate, promotion and production module families;
- developer-doc inventory gate fails if a runtime/Blender Python module is added without being documented;
- shared conservative physical-tree semantic classifier prevents legacy `CHARACTER` labels from hiding `char/monster`/`char/npc` while keeping frontend `StartImage`/`Sinimage` out of runtime groups;
- shared `resolve_asset_motion_context` removes duplicated INX/SMB context logic between CLI and corpus audits;
- `audit animation-corpus` deduplicates registry-proven motion contexts and produces source-side corpus evidence without claiming Blender/visual certification.
- new `audit development-readiness` summarizes maturity/blockers/priorities; optional `--deep` reruns read-only INX/SMB/animation corpus evidence without granting production authorization.
- new `deploy plan` is a read-only app-level deployment planner: it verifies artifact containment/provenance and enumerates drift/backup/rollback blockers while keeping `client_write_authorized=false`.
- `profiles discover` now scans the complete registry for exact LOD evidence; current canonical inventory yields 1,940 asset+INX candidates, 55 structurally ready candidates and 1 canonical runtime-proven profile, while all discovered candidates remain authoring-disabled.
- `audit development-readiness` emits a machine-readable maturity matrix (`OPERATIONAL`, `PARTIAL`, `CANDIDATE`, `DEFERRED`, `BLOCKED`) so roadmap status is derived from executable evidence rather than prose only.
- `audit development-readiness --deep` reruns read-only INX/SMB edit-corpus and animation evidence and can raise candidate maturity only to `CANDIDATE_EDIT_CORPUS_PROVEN`; it never grants production authorization.
- `audit animation-certification-plan` builds a deterministic Blender/human-review queue across physical INX/SMB contexts, semantic groups and complementary motion states without writing certifications automatically.
- deployment planning now explicitly separates a production-authorized asset writer from client-publish authorization; even a certified build remains non-deployable until drift, transaction manifest, verified backup, rollback and post-write verification gates exist.
- `deploy simulate` proves atomic replace, post-write SHA/size verification and rollback entirely inside `pt_build`; `--inject-failure postwrite` proves recovery after a controlled failure without opening the real client for writing.
- `deploy state` classifies live bytes as `ORIGINAL_SOURCE`, `MANAGED_ARTIFACT`, `UNKNOWN_DRIFT` or `MISSING`; `deploy restore-plan` only considers a known managed artifact semantically restorable and still keeps apply disabled.

## Explicitly not promoted

- Mixed-Physique: canonical audit found zero representatives, so support remains fail-closed.
- INX/SMB candidate writers are **not** authorized for client production writes.
- A byte-identical corpus roundtrip is evidence for preservation, not sufficient production authorization by itself.
- Monster/NPC entity identity does not authorize runtime binding or writers.
- Pairing-proven cross-folder relations are diagnostic evidence; they do not merge entity identities or promote an unbound model.
- Profile/LOD identity does not authorize geometry writers.
- Generic publish/restore is not enabled.

## Useful development commands

```bash
python3 pt_asset.py audit binding-coverage --category MONSTER
python3 pt_asset.py audit binding-coverage --category NPC --output pt_build/npc_binding_coverage.json
python3 pt_asset.py audit inx-writer-corpus --output pt_build/inx_writer_corpus.json
python3 pt_asset.py audit smb-writer-corpus --output pt_build/smb_writer_corpus.json
python3 pt_asset.py entities list --group NPC
python3 pt_asset.py entities inspect NPC Ahin
python3 pt_asset.py profiles list
python3 pt_asset.py profiles inspect pikeman_c01_m4
python3 pt_asset.py profiles lod pikeman_c01_m4 --lod high
python3 pt_asset.py profiles verify pikeman_c01_m4
python3 pt_asset.py profiles verify --all --output pt_build/profile_verify.json
python3 pt_asset.py profiles discover --limit 50
python3 pt_asset.py audit development-readiness
python3 pt_asset.py audit development-readiness --deep
python3 pt_asset.py audit animation-certification-plan --motions-per-context 3 --output pt_build/animation_certification_plan.json
python3 pt_asset.py audit inx-writer-edit-corpus --output pt_build/inx_writer_edit_corpus.json
python3 pt_asset.py audit smb-writer-edit-corpus --output pt_build/smb_writer_edit_corpus.json
python3 pt_asset.py import <asset> --no-open
python3 pt_asset.py build <asset> --plan
python3 pt_asset.py deploy plan <asset> --artifact pt_build/path/to/build.smd
```

## Latest regression in this environment

- development suite: **92 passed, 1 skipped**;
- historical/maintained suite: **175 passed, 1 skipped**;
- combined: **267 passed, 2 skipped, 0 failed**;
- skip 1: historical overlay installer test (installer intentionally removed from standalone runtime);
- skip 2: full ~188 MB Stage0.72 corpus (opt-in slow fixture test);
- `status`: PASS against supplied fixture client;
- `smoke`: PASS against supplied fixture client;
- Blender launcher unavailable in this environment only (diagnostic);
- all four certified rare writers retain their original SHA-256 hashes.

To run the full Stage0.72 fixture corpus in a developer checkout:

```bash
PT_RUN_SLOW_FIXTURE_TESTS=1 python3 -m pytest -q dev_tests/test_stage072_fixture_corpus.py
```

- object-local POS/SCALE existing-key writer candidate added with exact byte allowlist, 1/256 SCALE grid, corpus audit, and rotation/TmPrevRot kept fail-closed.
