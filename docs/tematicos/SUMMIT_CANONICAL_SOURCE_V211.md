# PT Asset Tool V2.11 — Summit Canonical Source Integration

**Status:** implemented foundation / fail-closed canonical authoring.  
**Date:** 2026-10-01.

## Authority model

V2.11 changes the authoring authority to:

`Summit Content/canonical/** -> SummitCanonicalContentProvider -> Semantic Catalog V2 -> Typed Authoring -> schema validation -> staged compilation -> pack validation -> explicit publish`.

`priston_asset_name_map_v1.json` remains installed, but only as a display alias / pt-BR friendly-name / ambiguity / migration overlay. It no longer decides which entities exist.

When `Content/CANONICAL_SOURCE.json` exists, an unknown or malformed canonical schema is fail-closed. The tool does not silently fall back to an authoritative legacy writer.

## Semantic Catalog V2

`pt_asset_tool.summit_canonical` scans canonical JSON live and exposes source fingerprints, definition counts, item-profile membership, separate CLIENT/SERVER map profiles, pack freshness, localization gate, and a canonical ContractGraph.

Items that exist in the canonical source but have no trusted friendly alias are shown as `<CODE> — <canonical_id>` with `MISSING_DISPLAY_NAME`. No friendly name is invented.

CLIENT and SERVER maps are separate profile rows. Field 53 is explicitly marked as a legacy dynamic-field exception and is never collapsed into a normal static-map contract.

## Definition writers

ITEM/MONSTER/NPC edits are atomic across the semantic representation used by the compiler:

- `semantic.fields`
- matching `semantic.directives[*].values`
- `raw_values_hex`
- `quoted`

The writer preserves unedited document content including `unknown_tokens`, source provenance, compatibility payloads and raw representation metadata. Missing or ambiguous directive mappings are rejected rather than producing a UI/SCFG split-brain. CP1252 representability and declared byte-capacity checks are enforced before stage.

## Field writers and legacy formats

In canonical mode:

- SPM -> canonical `stage_spawns` JSON -> `field_runtime.sfld`
- SPP -> canonical `stage_start_points` JSON -> `field_runtime.sfld`
- SPC -> canonical `fixed_npcs` JSON -> `field_runtime.sfld`

Legacy SPM/SPP/SPC and definition writers remain inspect/import/compare/diagnostic surfaces. Their authoritative stage/publish path is disabled while canonical mode is active.

## Staging, build and publish

Every canonical stage copies the complete `Content/canonical` tree, including `canonical/item_profiles`, before validation/build. This deliberately avoids the current clean-`out-root` layout dependency while keeping a future source-side fix compatible.

The stage pipeline validates canonical text and schemas, builds the canonical pack set, runs pack inspectors/profile validation, records hashes/fingerprints and materializes a staged `BUILD.json`.

Publishing is two-phase and explicit:

1. `PUBLISH CANONICAL SOURCE` — source JSON only.
2. `PUBLISH CANONICAL PACKS` — verified packs plus `BUILD.json`.

Client/server deployment is intentionally a separate third phase. Restore is transactional and protects against source/pack drift.

## Localization blocker

Localization edit/preview/validation are enabled. Production publish is blocked unless `validate_legacy_localization_bridge.py` actually passes. A failing validator cannot be bypassed by the canonical authoring API.

## UI / CLI

The Management surface now includes a V2.11 canonical panel with authority status, counts, fingerprints, pack freshness, localization gate and typed JSON authoring for ITEM, MONSTER, NPC, STAGE_SPAWN, STAGE_START_POINT, FIXED_NPC, MAP, GAMEPLAY_CONFIG, LOCALIZATION and CANONICAL_TEXT.

CLI entry point: `pt_asset canonical` with `status`, `catalog`, `capabilities`, `stage`, `publish-source`, `publish-packs`, and `restore` commands.

## ContractGraph

Canonical graph edges explicitly model:

- canonical source -> canonical families/profile authorities;
- family/profile -> compiled pack;
- `BUILD.json` -> pack hash gate;
- definition document -> profile-scoped definitions packs;
- CLIENT map profile -> `maps_client.smap`;
- SERVER map profile -> `maps_server.smap`;
- field 53 -> explicit legacy exception.

These are source/build authority edges, not inferred legacy runtime authority.
