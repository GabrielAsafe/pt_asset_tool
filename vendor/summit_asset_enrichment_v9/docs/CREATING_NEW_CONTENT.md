# Como criar novo conteúdo

O caminho mais seguro é distinguir conteúdo **data-driven** (monstro/NPC/item/parte de Field) de conteúdo que exige **código + assets** (nova classe jogável).

## 1. Novo monstro

### Cliente

1. Escolha um pacote funcional da **mesma geração Summit** como referência.
2. Crie/importe o 3D pelo PT Asset Tool já pesquisado, em vez de escrever SMD/SMB/INX do zero por um segundo pipeline.
3. Garanta `INI -> INX -> SMD/SMB -> textures` sem refs quebradas.
4. Para INX, preserve a geração de 95.268 bytes e a coerência de keyword/path usada pelo loader.

### Servidor

1. Copie como template um `GameServer/Monster/*.inf` cuja estrutura seja próxima do monstro desejado.
2. Edite somente campos reconhecidos pelo `smCharDecode` atual.
3. Use model refs que existam no cliente.
4. Se houver name/zhoon, crie a partir de uma amostra da mesma família/encoding.
5. Drops devem usar OpenItem codes realmente registrados.
6. Adicione o spawn via SPM, evento ou código correspondente.

### Validação

```bash
python3 build_dependency_graph.py --config summit_paths.json --out-dir dependency_graph
python3 reverse_inspect.py /path/do/novo.inx
```

O novo monstro só está “completo” quando o grafo não contém refs essenciais faltando e o runtime carrega/spawna sem erro.

## 2. Novo NPC

### Cliente

Um NPC pode ter pacote próprio em `char/npc` ou reutilizar um visual já existente. O padrão dos 19 NPCs server-only auditados mostra que essa reutilização é comum e útil para primeiro validar a definição server-side.

### Servidor

1. Crie `GameServer/NPC/<nome>.NPC` a partir de um template funcional.
2. Ajuste model ref/campos aceitos pelo mesmo decoder legado.
3. Adicione zhoon/name resource quando a família exigir.
4. Para NPC fixo de mapa, placement pode estar no SPC.
5. Para NPC de evento, procure primeiro a lógica de spawn/abertura do evento antes de editar SPC.

### SPC

O tamanho canônico atual é 50.400 bytes: 100 registros de `smTRNAS_PLAYERINFO` com 504 bytes. Isso prova o framing, mas **não é suficiente para um writer genérico seguro**: cada campo interno de `smCHAR_INFO`/player-info precisa ser serializado conforme o build atual. Até esse writer ser gerado diretamente das structs atuais, prefira o editor existente ou clone/patch estruturado de um registro comprovado.

## 3. Novo item

Adicionar item novo exige sincronizar dois mundos:

### Servidor

- `GameServer/OpenItem/*.txt`;
- mapa/código de item no servidor;
- loot/shop/drop/event references.

### Cliente

- registro no `sItem`/`item_catalog_recovered.inc` ou a fonte que o gera;
- `ItemFilePath`/categoria para icon/UI;
- `DorpItem` para o modelo de chão `DropItem/it<DorpItem>.ASE`;
- demais imagens/texturas exigidas pela família.

Não derive o arquivo visual somente do item code. O source atual mostra que `DorpItem` é um campo próprio.

Os 69 ícones pendentes do FIX 058 continuam sendo **conteúdo sem origem**, não candidatos a “gerar parecido”.

## 4. Novo Field/mapa

Bundle conceitual:

```text
CLIENT Field/<map>.smd              stage 3D
SERVER GameServer/Field/<map>.spm  spawn directives
SERVER GameServer/Field/<map>.spp  start points
SERVER GameServer/Field/<map>.spc  NPCs/fixed chars
```

### Pode ser criado agora

- SPM: é textual e a gramática básica é conhecida pelo parser; use arquivo funcional como template.
- SPP: writer estrutural está em `create_known_files.py`.

### Não automatizar ainda

Stage SMD 0.72 tem uma divergência crítica no source Summit: leitura atual usa `DWORD` para `StageArea`, enquanto o writer legado ainda escreve `WORD`, sob o mesmo header 0.72. Portanto novo Stage SMD deve continuar no pipeline 3D/PT tool validado, ou aguardar correção/normalização explícita do formato.

## 5. Nova classe/personagem jogável

Isso **não é file-only**.

O core atual declara capacidade para 10 jobs, mas habilita 8. Assassin (9) e Shaman (10) já têm vestígios/IDs no source, porém o comentário do build atual os mantém desabilitados até restaurar assets/handlers. A tela de criação ainda trabalha com quatro jobs por raça, e Assassin aparece comentado no fluxo Tempskron.

### Checklist para restaurar Assassin/Shaman ou adicionar um job

1. **Job IDs/capacidade:** atualizar `MAX_JOBNUM` e todos os arrays dimensionados/loops que assumem 8.
2. **Character selection:** aumentar/reestruturar arrays `JobCharacter`, imagens e hitboxes; não só descomentar um bloco.
3. **Criação do personagem:** stats iniciais, brood/race, body/face defaults e validação server-side.
4. **Modelos base:** body/head/face e animações da classe.
5. **Armaduras:** tabelas `szArmorNumFile*` em cliente e servidor, com INI/INX/SMD/textures existentes.
6. **Weapons/spec restrictions:** itens que aceitam o novo job e especializações.
7. **Skills:** tabelas, parser, UI, efeitos, packets e handlers cliente/servidor.
8. **Rank/quests/master:** nomes, NPCs e progressão.
9. **UI/localization:** imagens de seleção, job name, help/ranking/shop etc.
10. **Persistência/protocolo:** provar que job code e campos serializados não truncam/filtram 9/10.
11. **Segurança:** servidor deve validar job/skill/item; não confiar no cliente.
12. **Runtime:** criar, entrar, relogar, equipar, trocar mapa, subir rank e testar PvE/PvP.

### Ordem recomendada

**Restaurar Assassin (9) e Shaman (10) antes de inventar job 11.** O source já reserva capacidade 10 e contém hooks parciais para essas classes. Um job 11 exigiria primeiro ampliar uma fronteira estrutural que hoje é explicitamente 10.

## 6. Critério para um “writer novo”

Um writer só deve ser promovido a produção se:

1. parseia um corpus real sem perda;
2. read -> write -> read preserva os campos conhecidos;
3. o output tem tamanho/header corretos;
4. referências continuam resolvíveis;
5. o runtime Summit aceita pelo menos duas amostras geradas independentes;
6. diferenças binárias desconhecidas são explicadas ou conscientemente preservadas.

## 7. Evidência nova do corpus 2026-09-04

O corpus real confirmou o encadeamento de NPC fixo diretamente dentro do SPC. Cada registro ativo de 504 bytes contém, entre outros campos, duas strings que formam a ponte cliente/servidor:

```text
smTRNAS_PLAYERINFO
  +0x000  size/code
  +0x008  smCHAR_INFO.szName[32]
  +0x028  smCHAR_INFO.szModelName[64]   -> char\\npc\\...\\*.INI (cliente)
  +0x068  smCHAR_INFO.szModelName2[60] -> GameServer\\npc\\*.NPC (servidor)
  ...
  +0x1D8  dwObjectSerial
  +0x1DC  x
  +0x1E0  y
  +0x1E4  z
  +0x1E8  ax
  +0x1EC  ay
  +0x1F0  az
  +0x1F4  state
```

Exemplos reais incluem `char\\npc\\TN-005\\TN-005.INI` + `GameServer\\npc\\navisko-store.npc`. Isso fecha a relação conceitual **Field SPC -> client model INI + server NPC definition**.

Para INX, agora há duas famílias matematicamente provadas pelo source histórico/atual:

```text
LEGACY_120  67,084 bytes  MOTION_TOOL_MAX=52   sizeof(smMOTIONINFO)=120
MODERN_172  95,268 bytes  MOTION_TOOL_MAX=104  sizeof(smMOTIONINFO)=172
```

O Summit atual verifica `dwFileLen == sizeof(smMODELINFO)`, portanto o writer novo do Summit deve produzir `MODERN_172`. O layout `LEGACY_120` serve para leitura/conversão/arqueologia, não como destino binário nativo.

## 8. Fluxo operacional v6 para NPC fixo

A autoria de SPC deixa de ser apenas um request abstrato. O writer suportado é **clone-based**, porque o source prova o framing e os offsets essenciais, mas ainda não justifica sintetizar um `smCHAR_INFO` completo do zero.

```bash
python3 character_bundle_tool.py spc-patch npc.json \
  --config summit_paths.json \
  --bundle-dir generated/MyNpc
```

Regras do patch:

1. source SPC deve ter exatamente 50.400 bytes;
2. donor do writer deve ter o código ativo padrão observado `0x48470070`;
3. o writer preserva os bytes desconhecidos do donor;
4. `szName`, `szModelName[64]` e `szModelName2[60]` são substituídos;
5. `ModelNameCode2` e object serial donor-specific são zerados;
6. coordenadas e ângulos vêm do spec;
7. slot automático precisa ser completamente zerado; um slot `code=0` com conteúdo antigo só pode ser escolhido explicitamente;
8. `spc_patch_manifest.json` prende a alteração ao SHA-256 do SPC original.

Isso combina com o runtime: `LoadCharInfoFixed()` lê os 100 structs em bloco; os loops chamam `OpenNpc()` somente quando `code` é não-zero; `OpenNpc()` atribui um novo serial com `GetNewObjectSerial()`.

### Instalação

Depois do PT Asset Tool e do SPC patch:

```bash
python3 character_bundle_tool.py mirror-visuals npc.json --bundle-dir generated/MyNpc
python3 character_bundle_tool.py validate-stage npc.json --bundle-dir generated/MyNpc
python3 character_bundle_tool.py install-plan npc.json --config summit_paths.json --bundle-dir generated/MyNpc --out generated/MyNpc/install_plan.json
python3 character_bundle_tool.py install-apply generated/MyNpc/install_plan.json --out-log generated/MyNpc/install_apply.json
```

Para desfazer a transação:

```bash
python3 character_bundle_tool.py rollback generated/MyNpc/install_apply.json
```
