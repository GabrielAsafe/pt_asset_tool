# Summit reverse corpus — findings

Corpus: **485 samples**, 16 extensions.

## Deterministic layout findings

- **INX 95,268 bytes = MODERN_172**: current Summit `smMODELINFO`, `MOTION_TOOL_MAX=104`, `smMOTIONINFO=172`.
- **INX 67,084 bytes = LEGACY_120**: older layout (`MOTION_TOOL_MAX=52`, `smMOTIONINFO=120`); not native to the current 95,268-byte Summit loader.
- **Physical `.INI` is not a runtime requirement when the corresponding `.INX` exists**: `smModelDecode()` calls `smFindFile(logicalPath, "inx")`.
- **INX runtime chain is typed**: `szModelFile(.ASE) → .SMD`, `szMotionFile(.ASE) → .SMB`, link descriptors `.INI/.IN → .INX`.
- **SPP 2,400 bytes = current canonical**: 200 records × 12 bytes `{int state,int x,int z}`; 600 bytes is the legacy 50-record form.
- **SPC 50,400 bytes = current canonical**: 100 × 504-byte `smTRNAS_PLAYERINFO`; runtime opens records when `code != 0`; every active code observed in this corpus is the standard `0x48470070 (smTRANSCODE_ADD_NPC)`.
- **SPC `dwObjectSerial` is ephemeral**: `OpenNpc()` replaces it with `GetNewObjectSerial()` at runtime, so a writer must not preserve a donor serial as identity.
- **SPM is text**, normally CP949 in historical data; current source also accepts English aliases for spawn directives.

## Corpus coverage

| extension | samples | observed sizes |
|---|---:|---|
| `.ase` | 16 | 2839×3, 3404×3, 4238×2, 7791×1, 20543×2, 33227×2, 44688×2, 765658×1 |
| `.bmp` | 72 | 58×12, 3126×5, 6198×8, 12342×17, 24630×3, 49206×9, 49208×1, 98358×5, 196662×8, 196664×1, 262198×1, 393272×2 |
| `.dds` | 60 | 132×6, 4224×3, 8320×4, 16512×18, 32896×3, 65664×11, 131200×1, 262272×13, 1048704×1 |
| `.inf` | 18 | 95×15, 1441×1, 1501×1, 1502×1 |
| `.ini` | 21 | 3×1, 27×1, 47×1, 53×1, 56×1, 64×1, 65×6, 66×2, 67×1, 211×1, 222×2, 729×1, 1003×1, 1016×1 |
| `.inx` | 47 | 67084×11, 95268×36 |
| `.jpg` | 13 | 2103×1, 41093×4, 49134×3, 50322×2, 155062×1, 252511×1, 395017×1 |
| `.npc` | 22 | 116×2, 156×3, 173×2, 181×1, 186×1, 327×1, 361×1, 470×1, 507×1, 526×1, 646×1, 659×1, 689×1, 903×1, 1028×1, 1031×1, 1034×1, 1036×1 |
| `.png` | 11 | 157×1, 165×1, 166×1, 426×1, 796×1, 1170×1, 1352×1, 26975×1, 58842×1, 494156×1, 2050146×1 |
| `.smb` | 61 | 556×12, 3264×2, 3520×1, 4304×2, 8480×2, 11392×2, 66324×1, 71868×1, 78352×1, 97420×1, 127836×1, 147416×3, 151088×1, 151592×1, 155636×3, 172256×3, 451848×1, 469260×5, 483332×1, 601484×2, 603176×1, 624972×1, 683608×1, 883024×1, 1057516×1, 1082388×2, 1108948×1, 1422732×1, 1427252×1, 1631756×1, 1777816×1, 1815600×1, 3030084×1, 9619400×1 |
| `.smd` | 50 | 3517×12, 5604×7, 7480×2, 9240×2, 11102×1, 11752×1, 20638×1, 82106×1, 118039×5, 133966×3, 179995×1, 191855×1, 194140×3, 197735×1, 200039×1, 204126×1, 205273×1, 210000×1, 226992×1, 227236×1, 247871×1, 260119×1, 276615×1 |
| `.spc` | 3 | 50400×3 |
| `.spm` | 9 | 0×2, 131×1, 203×1, 205×2, 206×2, 241×1 |
| `.spp` | 5 | 600×2, 2400×3 |
| `.tga` | 46 | 16×2, 300×7, 786×1, 2092×1, 3090×1, 16428×15, 65580×4, 131116×4, 262188×10, 524332×1 |
| `.zhoon` | 31 | 0×3, 15×3, 18×1, 19×1, 20×1, 37×1, 41×1, 42×1, 59×1, 62×1, 89×1, 133×1, 190×2, 191×2, 196×1, 243×1, 252×1, 262×1, 357×1, 369×1, 420×1, 446×1, 482×1, 556×1, 655×1 |

## Runtime character bundles

| family | kind | server definition | INX | runtime chain | textures | Summit-ready |
|---|---|---|---|---|---|---|
| `summit` | npc | `GameServer/NPC/Xmasguy.npc` | MISSING | MISSING | OK | NO |
| `summit` | npc | `GameServer/NPC/quest.npc` | OK | OK | MISSING | NO |
| `summit` | npc | `GameServer/NPC/navisko-warehouse.npc` | MISSING | MISSING | OK | NO |
| `exmachina` | monster | `GameServer/Monster/Cstone.inf` | OK | OK | OK | YES |
| `exmachina` | monster | `GameServer/Monster/45_I_Hound.inf` | OK | OK | MISSING | NO |
| `exmachina` | monster | `GameServer/Monster/35_I_Zombie.inf` | OK | OK | OK | YES |
| `exmachina` | npc | `GameServer/NPC/quest.npc` | OK | OK | MISSING | NO |
| `exmachina` | npc | `GameServer/NPC/Ahin.NPC` | OK | OK | OK | YES |
| `exmachina` | npc | `GameServer/NPC/Nadia-Removed.NPC` | OK | OK | OK | YES |
| `priston` | npc | `GameServer/NPC/Xmasguy.npc` | MISSING | MISSING | OK | NO |
| `priston` | npc | `GameServer/NPC/quest.npc` | OK | OK | MISSING | NO |
| `priston` | npc | `GameServer/NPC/navisko-warehouse.npc` | MISSING | MISSING | OK | NO |
| `summit` | npc | `GameServer/NPC/navisko-dragoman.npc` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/navisko-store.npc` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/Sod_01.NPC` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/Sod_02.NPC` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/navisko-civilian2.npc` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/desert-guard.npc` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/Sod_03.NPC` | OK | OK | OK | YES |
| `summit` | npc | `GameServer/NPC/Sod_04.NPC` | OK | OK | OK | YES |
| `exmachina` | npc | `GameServer/NPC/ricarden-store.NPC` | OK | OK | OK | YES |
| `exmachina` | npc | `GameServer/NPC/ricarden-warehouse.npc` | OK | OK | OK | YES |
| `exmachina` | npc | `GameServer/NPC/Soul.NPC` | OK | OK | OK | YES |
| `priston` | npc | `GameServer/NPC/acasia-store.NPC` | OK | OK | OK | NO |
| `exmachina` | npc | `GameServer/NPC/Nadia.NPC` | OK | OK | OK | YES |

## Bundle closure gate

- Basic `INX → SMD/SMB` closure: **21/25**.
- Recursive runtime + texture closure: **17/25**.
- Native Summit-ready bundles (`MODERN_172` + localization + recursive runtime + textures): **16/25**.

### Repeated unresolved bundle dependencies

- `runtime:char/npcXms/ChTree_Longbo.inx` × 2
- `runtime:char/npc/npc-10.inx` × 2
- `texture:char/npc/MN-011/MN-012-h.BMP` × 1
- `texture:char/npc/MN-011/MN-012-b.BMP` × 1
- `texture:char/npc/MN-011/MN-012-ob.BMP` × 1
- `texture:char/monster/Hound/houndD_opa.jpg` × 1
- `texture:char/npc/MN-011/MN-012-h.dds` × 1
- `texture:char/npc/MN-011/MN-012-b.dds` × 1
- `texture:char/npc/MN-011/MN-012-ob.dds` × 1
- `texture:Char/Npc/MN-011/MN-012-h.BMP` × 1
- `texture:Char/Npc/MN-011/MN-012-b.BMP` × 1
- `texture:Char/Npc/MN-011/MN-012-ob.BMP` × 1

## Other gaps / evidence quality

- The corpus contains **21 `.ini` files**, of which **2** are under `char/npc` or `char/monster`. Physical character `.INI` remains authoring evidence, not necessarily a runtime dependency.
- Empty evidence files remain present: `.spm`=2, `.zhoon`=3. Keep them as provenance, never as templates.

## Recommended authoring confidence

| family | status |
|---|---|
| SPP current writer | GREEN |
| SPM template/writer | GREEN after actor-name validation against loaded monster list |
| SPC parser/dumper | GREEN |
| SPC clone-based record writer | GREEN with a known-good active donor record, exact 50,400-byte file, base SHA-256 guard, and transactional replacement |
| SPC synthetic-from-zero writer | BLOCKED — unknown `smCHAR_INFO` semantics should not be invented |
| INX classify/read/core dependency parse | GREEN |
| INX roundtrip | GREEN only through the already-certified PT Asset Tool path |
| Full new NPC/monster bundle | GREEN when the v6 `summit_ready_complete` gate passes; 3D authoring remains delegated to PT Asset Tool |
