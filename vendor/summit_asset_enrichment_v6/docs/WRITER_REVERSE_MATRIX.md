# Matriz de writer / reverse

| Formato | O que sabemos | Writer novo? | Caminho recomendado |
|---|---|---:|---|
| SPM | texto; directives ACTOR/BOSS_ACTOR/MAX_ACTOR_POS/MAX_ACTOR/DELAY | **sim, com template/parser** | preservar encoding e testar spawn |
| SPP | 200 registros `<iii>` de 12 B = 2.400 B | **sim** | `create_known_files.py spp` |
| SPC | 100 x 504 B = 50.400 B | parcial | gerar writer das structs atuais antes de autoria livre |
| INX Summit | `smMODELINFO`, 95.268 B, motion table 104 | não duplicar | PT Asset Tool / source atual; keyword/path importa |
| INX Priston | 67.084 B, motion table 52 | não usar no Summit | converter somente por pipeline conhecido, nunca copiar direto |
| SMD Model 0.62 | container/model conhecido pelo PT tool | sim via tool existente | reutilizar PT Asset Tool |
| SMB | família `smPAT3D`/model data | sim via tool existente | reutilizar PT Asset Tool |
| SMD Stage 0.72 | leitura/escrita Summit divergentes em StageArea WORD/DWORD | **bloqueado** | resolver formato/runtime antes |
| INF/NPC | texto decodificado por `smCharDecode` | sim por template | extrair gramática exata do parser e preservar charset |
| OpenItem TXT | texto parser-driven | sim por template | sincronizar server code map + client catalog |
| ZHOON | legado server-side; encodings/layouts mistos | clone/template primeiro | corpus + roundtrip antes de writer genérico |
| BMP/TGA | formatos conhecidos; algumas famílias BMP são protegidas | condicionado | detectar família; não “desproteger” por bulk |
| DDS | runtime moderno presente em algumas árvores | condicionado | só introduzir onde família/runtime já comprova |
| ASE | textual/export em algumas famílias de item/model | condicionado | provar se é runtime input ou source/export daquela família |

## Comando de corpus

```bash
python3 collect_reverse_samples.py --config summit_paths.json \
  --per-type 3 --out summit_reverse_samples.zip
```

Cada entrada recebe SHA-256 e relatório estrutural. Use esse ZIP para criar testes de roundtrip do PT Asset Tool ou de writers novos.

## Critério de corpus

Amostras devem representar **linhagens diferentes**, não apenas arquivos aleatórios do mesmo diretório. O coletor prioriza roots Summit e doadores configurados, limita tamanho por arquivo e evita executáveis.

## Atualização v6 — SPC e fechamento de bundle

| Formato/etapa | v6 |
|---|---|
| SPC parser | **GREEN**; `code!=0` é o gate real; `0x48470070` é o código ativo padrão observado |
| SPC clone-based patch | **GREEN com guardas**: donor ativo + SPC 50.400 B + slot blank/explicit + base SHA-256 + backup/rollback |
| SPC synthetic-from-zero | **BLOCKED**; não inventar campos desconhecidos de `smCHAR_INFO` |
| Bundle visual | **GREEN** somente após closure recursivo INX + SMD/SMB + texturas |
| Bundle Summit-ready | exige também todos os INX `MODERN_172` e localization server-side presente |

O corpus v5 mede 21/25 no gate antigo `INX -> SMD/SMB`, 17/25 no closure com textura e 16/25 no gate Summit-ready.
