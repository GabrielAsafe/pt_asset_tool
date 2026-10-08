# Summit Canonical Source Integration — V2.11

> **Historical V2.11 contract.** The authority/staging model remains useful background, but map dynamic-field behavior was superseded by V2.12. For the current rule, see `SUMMIT_CANONICAL_EXTENDED_DOMAINS_V212.md`: field 53 may be a normal static map and the dynamic field uses `append_after_static`.

## Authority

The authoring chain is now:

`Content/canonical/** -> SummitCanonicalContentProvider -> Semantic Catalog V2 -> typed authoring -> schema validation -> staged compilation -> pack validation -> explicit publish`.

The legacy `priston_asset_name_map_v1.json` remains installed as a display alias, pt-BR friendly-name, ambiguity and migration overlay only. It is not entity-existence authority. Source-only items without a trusted friendly name render deterministically as `CODE — canonical_id` and carry `MISSING_DISPLAY_NAME`.

## Typed writers

ITEM, MONSTER and NPC writers update compiler-consumed `semantic.fields` and matching `semantic.directives` payloads atomically, including `values`, `raw_values_hex` and `quoted`. Unknown tokens, source provenance, compatibility payloads and unrelated raw representation metadata are preserved. Missing/ambiguous directive mappings, CP1252 representation failures and declared byte-capacity violations fail closed.

SPM/SPP/SPC become legacy import-only surfaces in canonical mode. Persistent field editing targets canonical `stage_spawns`, `stage_start_points` and `fixed_npcs`, then rebuilds `field_runtime.sfld`.

## Maps and profiles

`client.maps.json` and `server.maps.json` are separate authorities and are never collapsed. The UI/API can compare a canonical map across profiles. At V2.11, field 53 was treated as an explicit legacy read-only exception; V2.12 superseded this rule with `append_after_static`. Item client/server profile membership is exposed independently as well.

## Browsers and reference content

The canonical resource browser indexes all canonical text resources and leaves families without a typed writer read-only. Item profiles are browsable. Quest Codex and Mix Guide are exposed from gameplay reference content as `REFERENCE_ONLY`; they are not quest-state or crafting transaction authority.

Gameplay config and localization use typed canonical JSON staging and the current source validators/compilers. Localization edit/preview are enabled, while production publish remains blocked unless `validate_legacy_localization_bridge.py --source-root ...` passes.

## Stage / build / publish

Every stage copies the complete canonical tree, including `canonical/item_profiles`, to avoid the current clean-out-root coupling. It runs canonical validation, compiles and inspects all nine packs, validates item-profile pack closure, records source-family fingerprints and creates a staged `BUILD.json` with verified hashes.

Publishing is explicit and two-phase:

1. `PUBLISH CANONICAL SOURCE` — canonical JSON only.
2. `PUBLISH CANONICAL PACKS` — the verified pack set plus `BUILD.json`.

Client/server deployment remains a separate third phase. Tree-wide drift gates run before phase 1 and between phases. Restore reverts the canonical JSON and generated pack/BUILD transaction together, subject to drift protection.

## ContractGraph

The canonical graph emits positive evidence for source authority, canonical family/profile membership, runtime paths/linked files, map/stage references, item-profile membership and pack/BUILD relationships. In the V2.11 graph contract, CLIENT/SERVER map edges were distinct and field 53 was marked `LEGACY_EXCEPTION`; current V2.12 behavior uses the catalog-level `append_after_static` dynamic-field policy instead. Graph evidence never converts legacy inputs into authoring authority.

## CLI

Use `pt_asset canonical status|catalog|capabilities|stage|publish-source|publish-packs|restore`. The UI exposes the same V2.11 status, browsers, typed staging and explicit publish phases in Management.
