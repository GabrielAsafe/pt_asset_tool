# Etervale: data-format tooling imported from the previous source

## Scope

The **Asset Tool** now owns the reusable source implementations for legacy **data formats** from the supplied
`contentETools.zip`. The import is deliberately kept separate from the Asset Tool's existing legacy models,
Blender, authoring and deployment systems. These scripts do not require the old C++ source tree merely to
inspect packs or compile the supported canonical JSON families.

The import **does not** install the old `Content/` as active Etervale game content. The old data catalog remains
input/reference material, not an Etervale runtime authority. Etervale currently reads its authored `assets/GameServer`
data using `PristonTale.WorldImport`, and its 3D assets through `Shared/PristonTale.Assets` and Engine3D; the
old Summit packed formats below are not established as supported by these readers.

## Moved code

| Imported files | New location | Status |
| --- | --- | --- |
| `tools/content_port/*.py` | `app/pt_asset_tool/legacy_data_tools/content_port/` | Ported, selected compilers/inspectors exposed |
| `tools/content_port/schemas/*.json` | `app/pt_asset_tool/legacy_data_tools/content_port/schemas/` | Available through `data-types schemas/validate-json` |
| Content port documentation and Python test sources | same folder, with original relative paths | Reference and regression material |
| `tools/content_workbench/*.py` and README | `app/pt_asset_tool/legacy_data_tools/content_workbench/` | Source preserved; **not** launched (old catalog/workspace dependencies) |
| ASE read-only inspectors | `app/pt_asset_tool/legacy_data_tools/ase_inspect/` | Exposed through `data-types ase-inspect` |

`MIGRATED_DATA_TOOL_SOURCES.json` records the original relative path and SHA-256 for each imported file.
`compile_field_runtime.py` uses an in-process Python helper instead of launching another Python executable,
so SFLD compilation can work when the Asset Tool is frozen by PyInstaller. The change is noted in the provenance
manifest. The remaining imported scripts are preserved as received, **not automatically executable**.

Explicitly *not migrated*: hundreds of old-source `validate_*` regression gates, source-patching scripts, Wine/native
model cook and texture cook tied to the old C++ runtime, automated deployment/quarantine scripts, old runtime scripts
that modify the database, and output artifacts in `Content/packs`. Those are not portable data-format modules.

## Formats and public CLI

From the Asset Tool `app/` directory:

```bash
python3 pt_asset.py data-types list
python3 pt_asset.py data-types schemas
python3 pt_asset.py data-types inspect /path/to/Content/packs/maps_client.smap
python3 pt_asset.py data-types inspect /path/to/Content/packs/field_runtime.sfld
```

| Format | Data purpose | Inspect | Compile (staging only) |
| --- | --- | --- | --- |
| SMAP | Map definitions, gates, warps, ambient | Yes | `compile smap <client.maps.json>` |
| SCFG | Monsters/NPCs/items | Yes | `compile scfg <canonical/text> --item-profile ... --npc-shop-overrides ...` |
| SRES | Text resources and embedded localization | Yes | `compile sres <canonical/text>` |
| SFLD | Stage spawn, start point, fixed NPC, GM points | Yes | `compile-field --spawns ... --start-points ... --fixed-npcs ... --text ...` |
| SGCF | Gameplay config | Yes | `compile sgcf <canonical/text>` |
| SGRF | Quests/mixing gameplay references | Yes | `compile sgrf <canonical/gameplay_reference>` |
| SCSP | Coin and time shop | Yes | `compile scsp <canonical/commerce/coin_shop.json>` |
| SSKM | Skin/equipment reform mappings | Yes | `compile sskm <canonical/item_profiles/skin_reforms.json>` |
| SSPB | Old standalone stage spawns | Yes | Internal compiler retained, no public wrapper (replaced by SFLD) |
| SLOC | Old localization container | Yes | Internal compiler retained, merged into SRES |
| SCTB | Generic legacy shadow bundle | Yes | Import retained, no public wrapper |

`compile` and `compile-field` write only inside the Asset Tool's `pt_build/data_types/` directory under `--root`
(default: current working directory). They fail rather than silently overwrite output. No command above deploys to
`assets/`, updates databases, or changes the C# runtime.

Example, with the old canonical data available as a read-only input:

```bash
python3 pt_asset.py --root /path/to/asset-tool-app \
    data-types compile scsp /path/to/old/Content/canonical/commerce/coin_shop.json

python3 pt_asset.py --root /path/to/asset-tool-app \
    data-types compile-field \
    --spawns /path/to/old/Content/canonical/stage_spawns \
    --start-points /path/to/old/Content/canonical/stage_start_points \
    --fixed-npcs /path/to/old/Content/canonical/fixed_npcs \
    --text /path/to/old/Content/canonical/text
```

Schemas are inspectable and validated by the imported standard-library schema-subset validator:

```bash
python3 pt_asset.py data-types validate-json \
    --schema equipment_sets /path/to/equipment_sets.json
```

## Etervale native readers and code boundaries

Etervale has its own **C# authoritative readers and exporters**. Their `.csproj` files remain in the Etervale
repository, because their project references point to Etervale's `Shared/`, `Client/`, and `Persistence/` projects.
Moving these projects physically into the Asset Tool would break those references and risks maintaining two copies of
the format contract. The Asset Tool instead discovers them through the single repository root:

```bash
python3 pt_asset.py data-types etervale-tools \
  --repo-root '/home/gabriel/Transferências/Etervale-git'
```

The first native validation adapter can plan a read-only `.smd`/`.smb`/`.inx`/texture inspection using the **real
Etervale** `PristonTale.AssetDump` reader (requires prebuilt .NET tool to execute):

```bash
python3 pt_asset.py data-types etervale-inspect \
  --repo-root '/home/gabriel/Transferências/Etervale-git' \
  --asset 'Field/Ricarten/village-2.smd'
```

Only appending `--execute` launches the C# program. That command uses `dotnet run ... -c Release --no-build`,
restricts its input to a file under the given Etervale `assets/`, and does not write game assets.

| Etervale tool | Responsibility | Treatment in Asset Tool |
| --- | --- | --- |
| `PristonTale.AssetDump` | Inspect actual SMD/SMB/INX/BMP/TGA | Read-only CLI bridge |
| `PristonTale.GltfExport` | Export SMD/SMB/INX to glTF/GLB | Discovered; future staged exporter |
| `PristonTale.WorldImport` | Parse CP949 `assets/GameServer`, import into persistence | Discovered only; import changes database |
| `PristonTale.WorldJson` | Export world catalog JSON | Discovered only |
| `PristonTale.VfxImport` | Produce modern effect `.vfx.json` | Discovered only; import writes content |
| `PristonTale.DataImport` | Copy/unmask source assets | Discovered only; writes assets |

## Verification performed against supplied legacy inputs

- 11 binary packs inspected successfully: SCSP, three SCFG variants, SFLD, SGCF, SGRF, two SMAP variants,
  SSKM, and SRES.
- Recompiled output **identical byte-for-byte** to supplied packs: SMAP client **and server**, SRES, SGCF, SGRF,
  SCSP, SSKM, SFLD, SCFG client and SCFG server when the respective profiles and NPC overrides were supplied.
  Evidence hashes are in `VALIDATION_RESULTS.json`.
- SCFG compiled **without** item profile/overrides does **not** reproduce the supplied unprofiled
  `definitions.scfg`; it is a different output (more definitions/directives). This difference is not suppressed.
- New CLI tests verify format listing, JSON schemas, safe staging, overwrite refusal, corrupted pack rejection,
  AssetDump command planning and protection from path traversal.

**Not yet verified:** real Etervale C# compilation or runtime acceptance of the old `.smap/.scfg/.sfld` etc.
Neither `.NET` builds nor the Etervale game client were executed on the user's machine. A missing legacy pack in the
Etervale project is not evidence that Etervale needs this format.

## Architecture boundary for the planned UI redesign

Use `data-types` as the domain/format service, not as an authorization to publish or deploy. A prospective UI should
present separate statuses for *source available*, *schema valid*, *compiled*, *readback valid*, *Etervale reader
validated*, and *runtime tested*. Old-source configuration discovery and source-code C++ reference scans are separate
migration tasks and must not be represented as done by this import.
