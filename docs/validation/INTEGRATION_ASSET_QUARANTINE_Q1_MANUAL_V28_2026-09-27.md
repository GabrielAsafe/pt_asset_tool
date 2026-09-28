# Integration Validation — Asset Quarantine Q1 Manual V2.8 — 2026-09-27

## Scope

Adds an explicit manual-only quarantine action for exactly one strict Q1 component. No delete path and no automatic/batch Q1 move are introduced.

## Safety contract

- ranking A/B/C remains review priority only;
- only `manual_quarantine_eligible=true` can reach `apply-component`;
- exact `URC-*` id and `MOVE_Q1_COMPONENT_TO_QUARANTINE` confirmation required;
- band A, <=10 members, no protected/entity/positive evidence, no external edges, documented invalid member required;
- every member remains `REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE`, graph-linked and not root-reachable;
- plan V2 captures bytes/SHA-256 for every physical member only after all structural gates pass;
- apply revalidates retention report SHA, asset TSV SHA, component membership, bytes and SHA-256;
- transactional rollback on move failure;
- existing restore handles both Q0 and Q1 transaction payloads;
- `deletion_authorized=false` everywhere.

## Validation

- focused quarantine/retention/effect/census: **47 passed**;
- focused regression: **40 passed, 1 skipped; PASS**;
- CLI parser smoke: `quarantine apply-component` present;
- package snapshot: **716 files PASS**; `VERIFY_PACKAGE=PASS`.

The historical 1.0 certification remains baseline only; full client/server/Blender runtime gates were not rerun here.
