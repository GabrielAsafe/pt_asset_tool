# Integration Validation — Summit Canonical Source V2.11

**Date:** 2026-10-01  
**Scope:** canonical provider, Semantic Catalog V2, typed writers, full-tree staging/provenance, pack freshness, canonical ContractGraph, specialized browsers, and legacy-authority guards.

## Automated validation

Focused V2.11 + legacy-authoring/name-catalog suite:

```text
38 passed
```

Covered cases include:

1. Unknown canonical authority schemas fail closed.
2. Canonical source determines entity existence; the V2.9 name map is display/alias overlay only.
3. Source-only Item IDs receive `CODE — canonical_id` plus `MISSING_DISPLAY_NAME`, never invented friendly names.
4. CLIENT/SERVER item and map profiles remain separate, including `legacy_field_code` and explicit dynamic field 53 handling.
5. Definition writer updates `semantic.fields` and `semantic.directives`/raw payload atomically while preserving unknown tokens, provenance, compatibility data and raw representation.
6. CP1252/byte-capacity violations fail closed; presence-only boolean directives retain their empty directive payload when set true and reject unvalidated false/removal transformations.
7. Staging copies the complete canonical tree, including `item_profiles`, and records source/staged per-file SHA-256 inventories plus aggregate fingerprints.
8. SPM/SPP/SPC/legacy authoritative staging is disabled in canonical mode while import/inspection paths remain separate.
9. Gameplay Config authoring is restricted to `immutable_gameplay_config`; UI/help INIs remain read-only.
10. Localization browser exposes locale/report data and the production-publish gate.
11. Quest Codex and Mix Guide are explicitly `REFERENCE_ONLY`; they do not become quest-runtime authority.
12. Canonical text resource census excludes metadata documents rather than silently widening authoring authority.
13. Declared canonical-family fingerprints are kept distinct from Asset Tool-computed tree fingerprints.
14. UI/API routing covers status, browsers, staging, publish/restore, map comparison and build freshness.

## Direct audit of supplied canonical content

The supplied `Content(5).zip` was loaded through `SummitCanonicalContentProvider` and produced:

```text
Items                 1924
Monsters               383
NPCs                   175
CLIENT maps             53
SERVER maps             53
Missing Item aliases    31
Text resources        5604
Text metadata docs       10
Gameplay configs         10
Gameplay config entries 578
Spawn stages             56
Quest Codex quests       88
Quest bindings           14
Supported bindings       13
Mix recipes             127
```

All nine supplied packs match the SHA-256 values currently declared by `Content/BUILD.json`; current-snapshot pack freshness is `FRESH`.

The provider exposes both the family hashes declared by `CANONICAL_SOURCE.json` and independently computed Asset Tool fingerprints. They are intentionally labeled separately; an Asset Tool-computed tree digest is not represented as if it were the source manifest's hashing contract.

## Localization blocker

Production localization publish remains blocked. Supplied evidence for `validate_legacy_localization_bridge.py` records `RESULT=FAIL` because the expected runtime contracts are missing:

```text
MultiByteToWideChar(CP_UTF8
WideCharToMultiByte
return 1252u
```

This is a publish gate, not a browser/editor gate.

## Toolchain-dependent gate

`Content(5).zip` includes the real canonical content tree and current packs, but not `tools/content_port`. Therefore this package independently validates source discovery, catalog/census, typed staging/provenance and current `BUILD.json` pack hashes, but does not claim to have recompiled a modified live stage in this environment.

When configured against a full Summit root, V2.11 invokes the source validators/compilers from that root and fails closed if they are absent or fail. Full-tree staging is retained even after the upstream out-root dependency is corrected, so `canonical/item_profiles` and the rest of the canonical layout are always present during compilation.
