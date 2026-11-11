# Summit Field Runtime Pack (SFLD v1)

`field_runtime.sfld` is the single runtime binary for legacy Field metadata that used
to be split across `.spm`, `.spp`, and `.spc` files.

Authoring remains split into independent canonical JSON families:

- `Content/canonical/stage_spawns/` — monster/boss spawn rules (SPM semantics)
- `Content/canonical/stage_start_points/` — fixed monster spawn positions (SPP semantics)
- `Content/canonical/fixed_npcs/` — fixed NPC placements (SPC semantics)

The runtime never edits those values. Persistent changes are made in canonical JSON and
then compiled/deployed.

## Container

All integer fields are little-endian. The top-level SFLD header is 64 bytes:

| Offset | Size | Meaning |
|---:|---:|---|
| 0 | 4 | magic `SFLD` |
| 4 | 2 | version = 1 |
| 6 | 2 | flags = 0 |
| 8 | 4 | section count |
| 12 | 4 | section table offset = 64 |
| 16 | 4 | section data offset |
| 20 | 4 | total file size |
| 24 | 8 | reserved = 0 |
| 32 | 32 | SHA-256 of bytes `[64..EOF)` |

Each section-table row is 48 bytes:

| Offset | Size | Meaning |
|---:|---:|---|
| 0 | 4 | section tag |
| 4 | 2 | section version |
| 6 | 2 | flags = 0 |
| 8 | 4 | section offset |
| 12 | 4 | section byte length |
| 16 | 32 | SHA-256 of section bytes |

SFLD v1 contains exactly the field families below.

## SSPB v2 — stage spawns

The existing deterministic `stage_spawns.sspb` payload is embedded unchanged as the
`SSPB` section. `DecodeOpenMonster()` obtains this section through
`CompiledFieldRuntimeSource` and passes it to the existing SSPB reader.

## SPPT v1 — stage start points

SPPT stores only active SPP records and preserves the original 0..199 slot number.
That preserves legacy iteration/randomization behaviour while avoiding 200 fixed records
per map in the authoring JSON.

Canonical row:

```json
{"slot": 5, "state": 1, "x": -1000, "z": -2000}
```

At runtime it is materialized back into `STG_START_POINT[200]`.

## SPCN v1 — fixed NPC placements

SPCN stores only active SPC placements and preserves the original 0..99 slot number.
The canonical JSON refers to a canonical NPC identity, not to a legacy physical `.NPC`
file:

```json
{
  "slot": 20,
  "npc_id": "npc.ji_woo",
  "x": -175442,
  "y": 52480,
  "z": -4438784,
  "ax": 0,
  "ay": 1000,
  "az": 0,
  "state": 0
}
```

During compilation, `npc_id` is resolved against the canonical text/definition index.
The pack retains the logical definition key required by the current `smCharDecode()`
bridge. The physical `.NPC` file is not read in strict compiled-definition runtime.

At runtime SPCN is materialized into the minimum legacy `smTRNAS_PLAYERINFO` state that
`OpenNpc()` still expects; the NPC definition itself comes from `definitions_*.scfg`.

## Migration

Run once while the legacy `.spp/.spc` files still exist:

```bash
python3 SourceCode/tools/content_port/migrate_field_runtime.py \
  --repo-root /path/to/repository
```

After validating the client/server with the new pack, the same migration can archive and
remove runtime `.spm/.spp/.spc` files:

```bash
python3 SourceCode/tools/content_port/migrate_field_runtime.py \
  --repo-root /path/to/repository \
  --prune-legacy
```

`--prune-legacy` first creates a ZIP under
`SourceCode/Content/migration_backups/` and only removes legacy field files after a
successful build and deployment.
