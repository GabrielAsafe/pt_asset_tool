> **V2.11 authority notice (2026-10-01):** this V2.9 catalog is retained as historical/display-alias evidence. In canonical mode, entity existence and persistent authoring authority come from `Summit Content/canonical/**`; see `SUMMIT_CANONICAL_SOURCE_V211.md`.

# Semantic Authoring Catalog

The semantic authoring catalog maps human-facing game names to stable internal authoring identities.

Source methodology includes game localization for visible names and canonical package definitions for IDs/codes/models/paths. The master 1:1 view excludes visible-name collisions; ambiguous names remain separately represented.

## Primary identity

Use `canonical_id` as the authoring selection identity.

Do not assume `internal_name` or runtime item code is globally unique across semantic variants.

## Categories

The packaged catalog covers:

- items;
- monsters/mobs;
- NPCs;
- maps;
- spawn stages;
- texts/labels used as supporting mapping evidence.

## Authoring integration

- Item selector resolves display name → `canonical_id` → runtime code/definition/path.
- Monster selector resolves display name → Monster definition/model metadata.
- NPC selector resolves display name → NPC definition/model metadata.
- Map selector resolves display name → field/stage → SPM/SPP/SPC targets.
- SPM offers related mob selection.
- SPC offers related NPC selection.
- Monster drops/NPC shops can insert related item codes while preserving semantic provenance.

## Locale policy

The UI labels are English. `display_name` remains the game-facing source value, commonly pt-BR in this catalog, because translating it would break the intended mapping to actual game content.
