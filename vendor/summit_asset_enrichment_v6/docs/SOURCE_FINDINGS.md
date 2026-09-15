# Findings consolidados usados pelo pacote

## FIX 058

- reconciliação histórica foi missing-only;
- 3.754 arquivos foram restaurados a partir de `ptbr-antigo`, sem overwrite;
- 69 ícones TimeShop/ItemShop continuaram pendentes após pesquisar todas as origens autorizadas;
- não é aceitável inventar/falsificar esses ícones nem usar um asset apenas “parecido”.

## Formatos

- INX Priston predominante: 67.084 B; Summit/ExMachina: 95.268 B;
- SPP Summit: 2.400 B; 600 B é framing legado de 50 registros;
- SPC: 50.400 B = 100 x `smTRNAS_PLAYERINFO` de 504 B;
- SPM: texto de spawn;
- FuncBox: 788 B, mas não é alvo de enriquecimento automático;
- BlessCastle.dat é estado/config runtime e não deve ser reconciliado como asset;
- Stage SMD 0.72 possui divergência estrutural importante no source Summit atual.

## Gaps auditados

- 35 modelos de monstro server-only foram classificados; 17 são self-contained, 11 possuem variante self-contained, 6 exigem dependency bundle, 1 (`KhanDoor`) fica bloqueado por zhoon ausente;
- 19 NPCs server-only fortes têm client asset correspondente; MapleTree/MapleFairy continua com gap de pacote;
- Field tem 13 componentes candidatos; `dcave.ase.spc` é a lacuna de componente de maior confiança, porém os doadores divergem binariamente, então permanece REVIEW; `AncientW/SeaA/Slab` também ficam em REVIEW;
- 206 OpenItems estavam ausentes por identidade semântica; conflitos `SP149/OA136` não podem ser auto-mergeados.

## Source atual

- cliente inclui `item_catalog_recovered.inc`;
- servidor inclui `item_code_map_mingw.inc`/mapping equivalente;
- item drop model usa `DorpItem`, portanto item code não é necessariamente filename visual;
- `MAX_JOBNUM=8`, `MAX_JOB_CAPACITY=10`; Assassin/Shaman permanecem reservados/desabilitados;
- character selection usa quatro jobs por raça no fluxo atual;
- monster, item, NPC e Field têm roots explícitos em `GameServer/...`, e SPP/SPC/SPM são derivados do basename do stage.

## Divergência de tabela de armaduras

- `SrcServer` usa slots `032, 033, 034`; `SrcGame` repete `032` onde o servidor usa `033`. O migrador não altera essa fonte automaticamente; veja `GAPS_AND_BUGFIX_CANDIDATES.md`.
