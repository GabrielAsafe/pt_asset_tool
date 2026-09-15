# PT Asset Tool — Validation Status R14 Handoff

Date: 2026-09-03
State: **WORKING / NOT RELEASED / NOT PRODUCTION PROMOTED**
Internal version: `0.12.0`

## Safety

- client source write default: disabled
- production authorization: disabled
- deploy apply: not enabled
- candidate outputs: `pt_build` only
- certified rare writer hashes: unchanged

## Validation at handoff

### PASS

- Python compileall: PASS
- focused R14 regression: **85 passed**
- offline Release 1.0 coverage generation: PASS as diagnostic, status `PARTIAL`
- offline LOD corpus generation: PASS

Current LOD corpus states:

- associated INX configs: 2036
- configs with LOD: 1940
- IMPORTABLE: 1906
- IMPORTABLE_FIXED16_MODEL_KEY: 22
- AUTHORABLE_SINGLE_TIER_FULL_CONTAINER: 10
- MISSING_SMD_NODES_FAIL_CLOSED: 2
- NO_LOD_GROUPS: 96

### Environment-limited

A broad `dev_tests` run stopped at maxfail=20 with 82 tests already passing. The 20 displayed failures all depended on the absent `fixture_client` tree/files. They are not counted as functional R14 failures, but the full suite must be rerun on a fixture-capable/client environment before a formal snapshot.

A generated selection of tests without a literal `fixture_client` reference progressed beyond 90% twice but exceeded the local timeout before producing a final pytest summary. Do not claim it as a completed pass.

### Last confirmed baselines before the latest LOD/coverage changes

- reproducible dev suite: 124/124 PASS
- historical compatibility suite: 175 PASS / 1 SKIP

Both should be rerun before the next formal user-testing build.

## Known external gate

No authentic Mixed-Physique Model0.62 representative exists in the current corpus. Synthetic pipeline is implemented, but physical certification requires an authoritative real sample.

## Not yet ready for user test

`validate release-1-auto` is present but its per-domain matrix gates are still being audited for false greens. Do not ask the user to run it yet merely because the command exists.
