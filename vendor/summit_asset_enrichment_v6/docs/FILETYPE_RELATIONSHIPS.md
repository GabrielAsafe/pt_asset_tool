# Relações entre arquivos do Summit

## Visão geral

```text
SERVER GameServer/monster/*.inf
    | smCharDecode / model reference
    v
CLIENT char/monster/.../*.ini
    -> *.inx (modelo + motion table)
    -> *.smd / *.smb (geometria/model data)
    -> BMP/TGA/DDS (textures)

SERVER GameServer/npc/*.npc
    | smCharDecode / model reference
    v
CLIENT char/npc/... ou char/monster/...
    -> INI -> INX/SMD/SMB/textures

SERVER GameServer/Field/<stage>.spm  -> monster/spawn directives
SERVER GameServer/Field/<stage>.spp  -> start points
SERVER GameServer/Field/<stage>.spc  -> fixed NPC/player-info records
                    ^
                    | basename derived from configured stage
CLIENT Field/<stage>.smd             -> stage/map geometry

SERVER GameServer/OpenItem/*.txt
    -> server item-code mapping / item semantics
    -> monster/NPC/drop references
CLIENT sItem catalog
    -> ItemFilePath + LastCategory -> icon/UI family
    -> DorpItem -> image/Sinimage/Items/DropItem/it<DorpItem>.ASE

SERVER name/*.zhoon
    -> server-side name/text resource
    -> no general client mirror was found in the audit
```

## Matriz por tipo

| Tipo | Lado | Papel | Relação principal | Política |
|---|---|---|---|---|
| `.INF` | servidor | definição de monstro | referencia modelo e gameplay; carregado por `smCharDecode` | template + parser atual |
| `.NPC` | servidor | definição de NPC | referencia pacote visual; carregado por `smCharDecode` | template + parser atual |
| `.ZHOON` | servidor | nome/recurso legado | usado junto a entidades/itens em famílias auditadas | preservar encoding/layout |
| OpenItem `.TXT` | servidor | definição de item | item code, drops, catálogo | criar só com código/catalog sincronizados |
| `.SPM` | servidor | spawn/atores | `ACTOR`, `BOSS_ACTOR`, limites/delay | texto; criar a partir da gramática do parser |
| `.SPP` | servidor | start points | 200 x (`state`,`x`,`z`) | writer conhecido, 2.400 B |
| `.SPC` | servidor | personagens fixos | 100 x `smTRNAS_PLAYERINFO` | 50.400 B; writer só após cobrir campos semânticos |
| `.INI` | cliente | pacote/model config | aponta para modelo/motion/texturas | data-driven |
| `.INX` | cliente | `smMODELINFO` + motions | path/keyword e SMD associados | Summit = 95.268 B; usar geração correta/PT tool |
| `.SMD` Model 0.62 | cliente | modelo 3D | INX/INI/texturas | PT Asset Tool como referência/autoria |
| `.SMB` | cliente | container/model data | mesma família `smPAT3D` | PT Asset Tool |
| `.SMD` Stage 0.72 | cliente | mapa/stage | Field + server SPM/SPP/SPC | **não gerar/copiar cegamente** |
| `.ASE` | cliente | referência/export de modelo/drop | `DorpItem` do catálogo em items | validar pipeline real por família |
| BMP/TGA/DDS | cliente | textura/UI | paths em pacotes/catálogo | DDS só quando runtime/família comprova |

## Monster

O servidor enumera `GameServer/monster/*.inf`. A definição é decodificada e seus model refs devem resolver no cliente. Um monstro completo pode ainda depender de:

- pacote visual cliente;
- `.zhoon`/name resource no servidor;
- OpenItem codes usados nos drops;
- Field `.spm` ou lógica/evento que o spawna.

Por isso “ter o INF” não significa “ter o monstro completo”.

## NPC

`GameServer/npc/*.npc` também passa pelo decoder legado. O NPC pode reutilizar um pacote visual existente de `char/npc` ou até `char/monster`. Placement pode vir de `.spc`, lógica de evento ou código dedicado.

## Field

O runtime deriva `.spp`, `.spc` e `.spm` do basename do stage configurado. Isso cria uma relação forte:

```text
Field/iron3.smd
GameServer/Field/iron3.spp
GameServer/Field/iron3.spc
GameServer/Field/iron3.spm
```

Nem todos os quatro precisam existir em todo mapa, mas um gap deve ser interpretado pelo parser/runtime, não só por simetria de filename.

## Items

A auditoria anterior inferia em alguns pontos `item code == nome visual`; o source atual permite corrigir isso. O cliente usa `sItem[j].DorpItem` para montar `DropItem/it<DorpItem>.ASE`, enquanto icon/category vêm de outros campos do catálogo. Portanto um OpenItem server-side e seu ícone/drop model client-side são **relações de catálogo**, não uma simples igualdade de nome.

## Armaduras / personagens jogáveis

O source `szArmorNumFile_New_2` conecta job/slot a `char/tmABCD/*.ini`; esses INI levam à cadeia INX -> SMD/model -> textures. Essa tabela precisa ficar consistente no cliente e servidor quando um job/armor set é adicionado.
