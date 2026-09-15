# Diagnóstico do corpus `summit_reverse_samples_v3.zip`

- 294 amostras / 14 extensões.
- 34 INX: 25 `MODERN_172` e 9 `LEGACY_120`.
- 21 `.ini` físicos existem no corpus; 2 ficam sob `char/npc` ou `char/monster`.
- O relatório anterior que dizia “No `.ini` samples were collected” estava incorreto: essa frase era hardcoded no analyzer v3.
- 25 definições server-side de NPC/monstro foram reconhecidas pelo auditor.
- Várias definições já resolvem o `.INX` físico mesmo sem `.INI` físico. Isso é compatível com o source atual: `smModelDecode()` troca a extensão lógica para `.inx` via `smFindFile()`.
- 0/25 bundles ficam runtime-complete dentro do ZIP v3 porque a coleta parava no INX e não seguia os aliases `szModelFile(.ASE)->.SMD` e `szMotionFile(.ASE)->.SMB`.
- Portanto o gate correto agora não é “coletar INI”; é “fechar `server definition -> INX -> SMD/SMB -> textures`”.
