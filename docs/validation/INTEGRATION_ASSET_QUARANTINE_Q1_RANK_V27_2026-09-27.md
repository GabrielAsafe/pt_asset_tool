# Asset Quarantine Q1 Review Ranking V2.7 — 2026-09-27

## Scope

Read-only ranking over persisted Q1 root-unreachable graph components. No Q1 move/delete path is introduced.

## Contract

- `review_score` is prioritization only.
- `review_band` is `A`, `B`, `C` or `BLOCKED`.
- positive retention state/evidence or entity bundle => `BLOCKED`.
- `quarantine apply` remains Q0-only.
- `deletion_authorized=false` remains invariant.
- ranking is deterministic and exposes `review_factors`.

## Validation

Targeted tests cover:
- small isolated documented-invalid component => priority A;
- valid isolated component => priority C;
- positive-evidence component => BLOCKED;
- review queue filtering;
- Q0 apply/restore/stale-plan regression.

## Executed gates

- focused quarantine/retention/effect/census/cooker-evidence: 37 passed;
- `RUN_REGRESSION_FOCUSED.sh`: 40 passed, 1 skipped; PASS;
- clean static snapshot: 715 files;
- `VERIFY_PACKAGE.sh`: PASS;
- full client/server/Blender runtime gate was not rerun in this environment.
