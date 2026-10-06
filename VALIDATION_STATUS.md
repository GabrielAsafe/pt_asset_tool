# Validation Status — V2.10 English Localization — 2026-09-28

## Overall

**PT Asset Tool 1.0.0 / V2.10 localization layer: TARGETED PASS / REGRESSION PASS**

V2.10 changes the first-party web UI and default operational/developer documentation to English. It does not expand authoring, client/server write, quarantine, or delete authority.

## Localization boundary

English-localized:

- first-party web UI labels, help text, workflow descriptions, prompts, toasts, and selected API-facing operator messages;
- root README and documentation index;
- authoritative operator/developer documentation under `docs/en/`.

Intentionally not translated:

- semantic catalog game `display_name` values used for matching;
- `canonical_id`, runtime codes, file paths, hashes, evidence tokens, and raw source excerpts;
- historical Portuguese documentation retained for provenance/path compatibility.

## Current validation

- English localization validator: `EN_LOCALIZATION=PASS`.
- English localization tests: 3 passed.
- V2.9 semantic-authoring + V2.10 localization focused suite: 42 passed.
- Focused regression: 40 passed, 1 skipped; `REGRESSION_FOCUSED=PASS`.
- Documentation audit: 76 files, 0 errors.
- JavaScript syntax (`node --check`): PASS.
- Package snapshot: 757 files; PASS.
- `VERIFY_PACKAGE=PASS`.

## Safety state

- production authorization: false by default;
- client write authorization: false by default;
- server write authorization: false by default;
- Q0/Q1 quarantine remains reversible;
- Q1 review score remains prioritization only;
- delete authority remains false;
- V2.8 exact-component manual quarantine gates remain unchanged;
- V2.9 semantic authoring identity/provenance gates remain unchanged.

## Current quarantine state known from operator evidence

The operator has previously quarantined four Q0 documented-invalid zero-linkage assets and the exact Q1 component `URC-02537` (`m_fury.smd` + `m_fury.tga`) transactionally with restore available. V2.10 does not modify quarantine state or transaction storage.

## References

- `docs/en/README.md`
- `docs/en/validation/LOCALIZATION_EN_V210.md`
- `docs/en/topics/SEMANTIC_AUTHORING_CATALOG.md`
- `docs/en/topics/ASSET_QUARANTINE_WORKFLOW.md`

## V2.11 — Summit Canonical Source Integration (2026-10-01)

Focused automated validation: `38 passed` across `test_summit_canonical_v211.py`, `test_legacy_authoring_pipeline.py`, and `test_legacy_name_catalog.py`. Coverage includes fail-closed authority schemas, Semantic Catalog V2 alias-overlay behavior, missing-display-name fallback, atomic fields+directives editing, CP1252/capacity guards, presence-only boolean directives, complete-tree staging with per-file source/stage hashes, legacy writer disablement, CLIENT/SERVER map separation, `legacy_field_code`/dynamic field 53 handling, gameplay/localization browsers, Quest/Mix reference boundaries, and canonical ContractGraph/profile edges.

`Content(5).zip` was audited directly against the V2.11 provider. The observed canonical census is:

- 1,924 Item definitions;
- 383 Monster definitions;
- 175 NPC definitions;
- 53 CLIENT + 53 SERVER static map entries, kept as separate profiles;
- 31 Item canonical IDs without a sufficiently friendly display alias;
- 5,604 canonical text resources across the resource families, plus 10 canonical text metadata documents;
- 10 authoritative gameplay-config documents with 578 semantic entries;
- 56 spawn stages;
- Quest Codex reference content: 88 quests, 14 bindings total, 13 supported;
- Mix Guide reference content: 127 recipes.

All nine pack files in the supplied `Content(5)` match the SHA-256 values declared by its current `BUILD.json`; current pack freshness therefore validates as `FRESH` for that supplied snapshot.

The localization production-publish gate remains **BLOCKED**. The supplied project evidence records `validate_legacy_localization_bridge.py` as `RESULT=FAIL`, with the expected runtime contracts `MultiByteToWideChar(CP_UTF8`, `WideCharToMultiByte`, and `return 1252u` missing. Editing and preview/validation remain available; production publish fails closed.

The supplied `Content(5)` archive contains the canonical content tree and packs but not `tools/content_port`. Consequently this environment can validate the live provider/catalog/census/current pack hashes and construct full-tree stages, but it cannot independently rerun the source validators/compilers after a mutation. Recompile/inspect of a modified stage remains a runtime gate against a configured Summit root that includes the canonical toolchain.

Release packaging gates after the V2.11 integration: `EN_LOCALIZATION=PASS`, JavaScript syntax `PASS`, `SNAPSHOT_MANIFEST_CHECK=PASS` (770 static files), and `PACKAGE_VERIFY=PASS`.
