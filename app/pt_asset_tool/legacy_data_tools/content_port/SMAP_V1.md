# SMAP v1 — compiled static map catalog

`SMAP` is the versioned runtime pack for the static portion of Summit's legacy
`InitField()` map catalog. It is compiled offline from `summit.map-catalog/v1`
UTF-8 JSON. The runtime does not parse JSON.

The current client and server catalogs intentionally remain separate because 14
legacy fields differ semantically between the two sides. Static field codes are a
contiguous range `0..N-1`; the legacy `smConfig` custom field is not reserved at a
fixed code and is appended at runtime as field `N`. The pack header therefore stores
`static_field_count=N` and `dynamic_field_code=N`.

All integer fields are little-endian fixed-width values. No raw C++ structs are
serialized.

## Header (128 bytes)

| Offset | Type | Meaning |
| ---: | --- | --- |
| 0 | `char[4]` | `SMAP` |
| 4 | `u16` | version = 1 |
| 6 | `u16` | header bytes = 128 |
| 8 | `u32` | profile: 1 client, 2 server |
| 12 | `u32` | flags, currently 0 |
| 16..71 | count/offset pairs | maps, stage objects, start points, gates, warp gates, warp outs, ambient |
| 72 | `u32` | UTF-8 string-table offset |
| 76 | `u32` | string-table bytes |
| 80 | `u32` | dynamic legacy field code (first field after the static range) |
| 84 | `u32` | static field count |
| 88 | `u32` | feature mask; bit 0 = `worldcup_field` |
| 92 | `u32` | reserved = 0 |
| 96 | `u8[32]` | SHA-256 of bytes `[128, EOF)` |

## Records

- map: 112 bytes
- stage object: 16 bytes (`asset string`, bip flag, required features, forbidden features)
- start point: 8 bytes (`x`, `z`)
- field gate: 16 bytes (`target field`, `x`, `z`, `y`)
- warp gate: 36 bytes (`x`, `z`, `y`, size, height, limit, effect, out start/count)
- warp-out gate: 16 bytes (`target field`, `x`, `z`, `y`)
- ambient: 20 bytes (`x`, `y`, `z`, radius, sound code)

Map image IDs use `0xFFFFFFFF` as the null-string sentinel. The UTF-8 string table
starts with an empty string at offset zero.

The final three words in each 112-byte map record preserve a legacy anomaly:
`has_orphan_warp_limit`, `orphan_warp_limit`, `reserved`. Four maps currently carry
such an orphan `LimitLevel` write. The compiler preserves it instead of guessing
which warp gate the legacy code intended to modify.

## Determinism

String interning order is part of SMAP v1 reproducibility: per map, stage-object
paths are interned first, followed by map ID, stage path and optional map-image ID.
The current compiler reproduces the handoff client/server packs byte-for-byte.

## Runtime contract

`CompiledMapContentSource` requires the section layout to be canonical and contiguous,
requires reserved fields to be zero, validates every child range and string offset,
and verifies the header SHA-256 against bytes `[128, EOF)`. Profile mismatch is
rejected by `LegacyMapAdapter` before materialization.

The runtime bridge is opt-in through `SUMMIT_MAP_PACK`. With
`SUMMIT_MAP_STRICT=1`, any pack/load/materialization failure makes `InitField()` fail;
without strict mode, `InitField()` reconstructs the original hardcoded catalog. Static
fields are loaded from SMAP and the `smConfig` custom field is finalized at
`dynamic_field_code == static_field_count` (the first free field) exactly as
in the legacy path. `WORLDCUP_FIELD` is translated to feature bit 0 at runtime.

The compiler input itself can be regenerated from the current legacy source with
`semanticize_maps.py`. That source-to-pack path is covered by a golden SHA/byte parity
test so changes to legacy map semantics cannot silently produce a different SMAP.
