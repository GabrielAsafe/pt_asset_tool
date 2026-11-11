# Summit Content Port

Offline migration toolchain for legacy gameplay/content data. Model/stage geometry formats
(`SMD`, `SMB`, `INX`, `ASE`) are deliberately outside this project; paths to those
assets are treated as opaque references only.

The implementation follows the same horizontal-migration pattern used by the newer
Summit systems: a neutral domain model, an interface boundary, a legacy source and a
compiled source can coexist. Calls are switched only after parity is demonstrated.

## Field runtime pack

Field authoring is split into three editable canonical JSON families and compiled into
one runtime binary:

```
stage_spawns/*.json        (legacy SPM semantics)
stage_start_points/*.json  (legacy SPP semantics)
fixed_npcs/*.json          (legacy SPC semantics, canonical npc_id references)
              \
               +-- compile_field_runtime.py
              /
Content/text index --------+
               |
               +--> Content/packs/field_runtime.sfld
                    sections: SSPB + SPPT + SPCN
```

`DecodeOpenMonster()` reads the embedded SSPB section. `STG_AREA::LoadStartPoint()`
reads SPPT and `STG_AREA::LoadCharInfoFixed()` reads SPCN. These runtime reads are
strict and executable-relative; they do not fall back to physical `.spm`, `.spp` or
`.spc` files. SPP/SPC slot numbers are preserved so legacy iteration/randomization
behavior remains stable. Fixed NPC JSON stores `npc_id`; the compiler resolves that
ID against canonical NPC definitions and places the logical definition path in the
pack for the existing `smCharDecode()` bridge.

One-time import from an existing server tree:

```bash
python3 tools/content_port/import_field_runtime_legacy.py --repo-root /path/to/summit
```

Then rebuild the normal standalone runtime content:

```bash
python3 tools/content_port/consolidate_canonical_content.py --repo-root /path/to/summit
```

The old standalone `stage_spawns.sspb` is now only an internal compiler intermediate;
it is removed from the canonical build output and deployment.

Binary layout and migration invariants are documented in `FIELD_RUNTIME_SFLD_V1.md`.

### Field authoring policy

After migration, `.spm`, `.spp` and `.spc` are import-only legacy formats. Runtime
loads are pack-only. Persistent field edits must be made in canonical JSON and rebuilt.
The old GM start-point/fixed-NPC mutators are disabled so a live server cannot create a
second, ignored source of truth. Use `migrate_field_runtime.py --prune-legacy` only after
a successful build/deploy; it archives the legacy field files before removing them.

## Map catalog slice

The static map catalog is now end-to-end. `semanticize_maps.py` converts the current
legacy `InitField()` source into profile-specific `summit.map-catalog/v1` UTF-8 JSON;
`compile_maps.py` emits deterministic `SMAP v1`; `CompiledMapContentSource` verifies
the canonical layout and SHA-256 before loading neutral `MapDefinition` objects; and
`LegacyMapAdapter` materializes them into the existing `sFIELD` runtime.

Client/server remain separate because 14 legacy fields differ semantically. The `smConfig`
custom field intentionally remains on the legacy runtime path, but it no longer reserves field 53:
it is appended at the first free field after the static catalog. The static compiled path
preserves reciprocal `AddGate()` behavior, feature-gated
`WORLDCUP_FIELD` stage objects and the four orphan warp `LimitLevel` writes.

The static map catalog is also resolved from executable-relative compiled packs in the current runtime. The source-derived compiler reproduces the handoff client/server packs byte-for-byte. Format details are in `SMAP_V1.md`.

```bash
python3 tools/content_port/semanticize_maps.py \
  Shared/world/field/field_legacy_client.inl --profile client --source-root . \
  --output /tmp/client.maps.json
python3 tools/content_port/compile_maps.py /tmp/client.maps.json /tmp/maps_client.smap
python3 tools/content_port/inspect_maps.py /tmp/maps_client.smap
```

## Shadow JSON

Every supplied textual file is converted to UTF-8 JSON with provenance, SHA-256 and
raw byte evidence. Known gameplay families are parsed semantically at byte-token
level. This is necessary because the corpus contains files that mix CP949 directives
with Western byte strings, so assigning one codec to an entire file is unsafe.

The shadow import is intentionally non-destructive. It is an audit/authoring bridge,
not yet a declaration that every generic `.ini`, `.sin`, `.msg` or `.lua` line has a
closed semantic schema.

## Item runtime authority migration

OpenItem JSON under `Content/canonical/text/` is the semantic source of truth. During
the migration away from the legacy executable item tables, each item may optionally
declare `runtime_profiles` (`client`, `server`) and an extensionless cooked icon
identity under `assets.icon`.

Profile resolution is deliberately transitional and fail-closed:

```text
canonical OpenItem runtime_profiles present
        -> explicit canonical include/exclude decision
canonical OpenItem runtime_profiles absent
        -> legacy client/server item-code profile fallback
```

The generated `Content/canonical/item_profiles/*.items.json` files therefore describe
the legacy fallback surface; they no longer override an explicit canonical decision.
This lets items move to canonical authority incrementally without changing the
behavior of unmigrated items. After all runtime-relevant items have explicit profile
coverage, the legacy fallback can be retired.

`assets.icon.logical_path` is extensionless by design. Authoring evidence can still be
BMP/TGA/PNG/DDS, but the declared runtime format is `dds`; a separate cooked-asset
gate must prove the DDS exists before the legacy image fallback is disabled. Canonical
item metadata does not authorize copying a donor file directly into runtime.

Example:

```json
{
  "runtime_profiles": ["client", "server"],
  "assets": {
    "icon": {
      "logical_path": "image/Sinimage/Items/Event/itSP123",
      "runtime_format": "dds",
      "runtime_required": true
    }
  }
}
```

`compile_definitions.py` applies this explicit policy before the legacy profile
fallback. `validate_item_profile_pack.py` resolves the same effective policy when
checking generated client/server packs, and `validate_compiled_item_materialization.py`
uses the effective server policy for NPC-shop materialization checks.

## Reproducible build

```bash
python3 tools/content_port/build_text_pipeline.py \
  --corpus /path/to/summit_text_corpus \
  --source-root . \
  --out-root /tmp/summit_content_build
```

This performs:

1. byte-aware import of the entire supplied textual corpus;
2. shadow validation;
3. cross-reference audit (SPM -> active top-level monster INF, linked files, IDs);
4. extraction of all 54 hardcoded maps from both client and server `InitField()`;
5. client/server map semantic comparison;
6. semanticization of static fields 0..52 and compilation of client/server SMAP v1;
7. compilation of field runtime data into one `field_runtime.sfld` container:
   SPM -> SSPB v2, SPP -> SPPT v1, and SPC -> SPCN v1.

Individual commands remain available:

```bash
python3 tools/content_port/import_corpus.py --corpus ... --source-root . --out ...
python3 tools/content_port/validate_shadow.py ...
python3 tools/content_port/validate_relations.py --shadow ... --corpus ... --out .../RELATIONS.json
python3 tools/content_port/compile_field_runtime.py \
  --canonical-spawns SourceCode/Content/canonical/stage_spawns \
  --canonical-start-points SourceCode/Content/canonical/stage_start_points \
  --canonical-fixed-npcs SourceCode/Content/canonical/fixed_npcs \
  --canonical-text SourceCode/Content/canonical/text \
  /tmp/field_runtime.sfld
python3 tools/content_port/inspect_field_runtime.py /tmp/field_runtime.sfld
```

`compile_shadow.py`/`inspect_binary.py` provide a generic audit container for the
whole shadow tree. It is not the final domain runtime format; runtime families get
explicit versioned packs such as SSPB.

## Gameplay reference / Quest Codex / Mix Guide

Player-facing reference data that must not become authoritative quest state lives in
`Content/canonical/gameplay_reference/`. The first slice imports the supplied PT-BR
quest guide, an explicit conservative runtime-binding manifest, and the supplied PT-BR mix table.

`compile_gameplay_reference.py` emits `Content/packs/gameplay_reference.sgrf`. The
pack is deployed to both client and server, but the initial consumer is the V2 client
Quest Journal. The journal exposes a read-only Codex and enriches live/classic quest
rows when a verified runtime ID or a live title matches the guide. The same pack also feeds the client Mix Guide opened by the existing NPC mix-guide opcode; no HTTP request is required at runtime.

Static guide data includes objectives, NPCs, maps/locations, quest items, documented
rewards, prerequisites, class/faction restrictions, stages, notes and source
provenance. Accepted/completed state, kill counters, cooldowns and reward grants stay
server-authoritative and are never inferred from the guide.

Mix reference data remains static: recipe category, exact sheltom ingredients, minimum level, source notation, bonuses, rules and source provenance. The canonical JSON is stored unchanged under `gameplay_reference/mix/`, while SGRF v2 provides a structured runtime view for the client.

The Level 80 PT-BR Tier-5 guide entry is intentionally present in canonical data but
is not marked supported until the current Summit Rank5 chain is proven equivalent.

```bash
python3 tools/content_port/compile_gameplay_reference.py \
  Content/canonical/gameplay_reference \
  Content/packs/gameplay_reference.sgrf
python3 tools/content_port/inspect_gameplay_reference.py \
  Content/packs/gameplay_reference.sgrf
```
