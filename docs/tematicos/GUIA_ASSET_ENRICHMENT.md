# Guia do Summit Asset Enrichment

> **Documentação 1.0:** Guia server/enrichment 1.0. Para índice completo veja `README.md`; para comandos exaustivos veja `CLI_REFERENCE_1_0.md`.

O **Summit Asset Enrichment** entende o conteúdo do servidor como bundles funcionais e liga esses bundles aos assets do client. Ele não é um simples comparador de pastas e não deve ser usado como “copiar tudo que está faltando”.

A versão ativa e única suportada neste snapshot é **v9 Fix136**, em `vendor/summit_asset_enrichment_v9/`. O vendor v6 não faz parte da distribuição ativa; referências a ele existem apenas em material histórico.

O Design Tool integra descoberta/validação, migration plan, dependency graph e o editor staging de Field metadata SPM/SPP/SPC. Os comandos de `apply`/`install-apply` do vendor continuam separados e não são disparados automaticamente pela UI.

## 1. Qual problema ele resolve

Um Monster do servidor não é apenas um `.inf`. Um Field não é apenas um `.smd`. Um Item não é apenas um `.txt`.

O Enrichment tenta responder: **“quais arquivos e contratos precisam existir juntos para esta coisa funcionar?”**

## 2. Os quatro bundles principais

### Monster

```text
GameServer/monster/*.inf
  → name/*.zhoon
  → char/.../*.ini (nome lógico)
  → *.inx
  → *.smd / *.smb
  → texturas
  → drops
  → spawn/evento
```

### NPC

```text
GameServer/npc/*.npc
  → name/*.zhoon
  → model package client/server
  → SPC quando NPC fixo
  → shop/quest/evento quando aplicável
```

### Field

```text
stage SMD/ASE
  → GameServer/Field/<stage>.spp
  → GameServer/Field/<stage>.spc
  → GameServer/Field/<stage>.spm
  → Monster/NPC referenciados
```

### Item

```text
GameServer/OpenItem/*.txt
  → ZHOON quando usado
  → server item code map
  → catálogo do client
  → modelo/drop/icon/categoria
  → drops/shops/eventos
```

## 3. O conceito mais importante: lifecycle

O servidor mistura conteúdo estático, assets compartilhados, configuração, persistência, logs e estado de segurança. A extensão sozinha não diz se um arquivo é “editável como asset”.

| Lifecycle | Exemplos | Tratamento |
|---|---|---|
| Asset estático | INF, NPC, ZHOON, OpenItem, SPM | analisar como bundle |
| Metadata de Field | SPP | layout conhecido |
| Metadata em review | SPC | clone/typed writer, não hex livre |
| 3D compartilhado | INX, SMD, SMB, ASE | pipeline PT Asset Tool |
| Visual compartilhado | BMP/TGA/DDS/JPG/PNG | somente com referência provada |
| Config operacional | Configs/*.ini | review deliberado |
| Persistência | DataServer, PostBox, WAR | fora do asset graph |
| Segurança/estado | cpItem.dat, BlessCastle.dat, BlackUser | bloqueado |
| Integridade runtime | FuncBox | bloqueado |
| Log/forensics | LogItemData/*.itm, LOGS | excluído da autoria |

### Por que `LogItemData/*.itm` não é asset

Esses arquivos são snapshots/logs de `sITEMINFO`, usados para auditoria/anti-dup/diagnóstico. Eles podem ter nomes e dados de item dentro, mas não são as definições estáticas que você deve migrar ou editar.


## Editor de Field metadata integrado (1.0.0)

Na aba **Servidor / Asset Enrichment**, escolha `Fields` no Explorador de bundles. A aplicação pode inspecionar e criar drafts para os três companions do stage:

- **SPM**: spawn/atores, texto legacy;
- **SPP**: start points, 200 registros canónicos;
- **SPC**: NPCs fixos/merchants, somente clone-patch de ADD_NPC conhecido.

Os drafts ficam em `pt_build/server_field_editor`. Não existe publish no server root. Detalhes em `FIELD_METADATA_EDITOR.md`.

## 4. Configurar o server root

No pacote integrado:

```bash
cd app
python3 pt_asset.py config set-server-root \
  "/path/to/Servidor"
```

Ou use:

```bash
--server-root "/path/to/Servidor"
```

## 5. Gates read-only integrados

### Validar ambiente do servidor

```bash
python3 pt_asset.py \
  --client-root "/caminho/cliente" \
  --server-root "/caminho/Servidor" \
  validate server-environment-auto
```

### Analisar Asset Enrichment

```bash
python3 pt_asset.py \
  --client-root "/caminho/cliente" \
  --server-root "/caminho/Servidor" \
  validate server-design-auto
```

Esse gate executa inventário + Monster/NPC + Fields + OpenItem e grava reports em `pt_build`.

### Integração client + server

```bash
python3 pt_asset.py \
  --client-root "/caminho/cliente" \
  --server-root "/caminho/Servidor" \
  validate integration-regression-auto
```

Use durante desenvolvimento para garantir que as correções de formatos físicos e os parsers server-aware continuam compatíveis.

## 6. Como usar a aba Servidor / Enrichment

### Raiz do servidor

Salva ou troca o path do servidor.

### Validar ambiente

Confirma que a raiz existe, é legível e está separada do client/`pt_build`.

### Analisar Asset Enrichment

Faz o censo completo de design read-only.

### Validar Client + Server

Executa regressões focadas de integração.

### Explorador de bundles

Permite filtrar Monster/NPC, Fields e OpenItem por:

- estado;
- texto/path/código;
- motivo de REVIEW/BLOCKED.

Ao clicar numa linha, a UI explica a cadeia observada e o motivo daquele estado.

## 7. Como interpretar REVIEW e BLOCKED

### `ZHOON_REFERENCE_MISSING`

A definição aponta para um recurso de nome/chat não encontrado. O visual pode existir, mas o bundle server-side ainda está incompleto.

### `MODEL_INX_NOT_RESOLVED_CLIENT_OR_SERVER`

O model lógico não resolve para um INX conhecido em nenhuma das duas raízes.

### `AMBIGUOUS_STAGE_BASENAME`

Mais de um stage SMD tem o mesmo basename. O Tool não escolhe automaticamente porque isso pode ligar o field ao mapa errado.

### `SPC_NOT_PRESENT` / `SPM_NOT_PRESENT`

O companion não existe. Pode ser legítimo para alguns fields, mas o bundle é classificado como parcial até o contrato runtime estar entendido.

### `DUPLICATE_CODE`

Mais de um OpenItem usa o mesmo code. É uma colisão semântica que precisa de revisão.

### `CODE_NOT_PARSED`

A identidade do OpenItem não foi extraída com segurança.

## 8. Plano e grafo v9 dentro do Design Tool

A integração preserva a ferramenta original, mas oferece duas operações **read-only** diretamente na aba `Servidor / Enrichment`:

- **Gerar plano v9** — executa o planner do Asset Enrichment em modo `plan`, usando os roots configurados no Design Tool. O resultado vai para `pt_build/enrichment_vendor`; nenhuma linha é aplicada automaticamente.
- **Grafo de dependências v9** — executa o gerador de grafo e grava os artefatos em `pt_build/enrichment_vendor`. Ele serve para visualizar referências e gaps, não para corrigir conteúdo sozinho.

Os equivalentes de CLI são:

```bash
python3 pt_asset.py --client-root "/caminho/cliente" --server-root "/caminho/Servidor" audit enrichment-plan
python3 pt_asset.py --client-root "/caminho/cliente" --server-root "/caminho/Servidor" audit enrichment-graph --skip-client-scan
```

O Design Tool **não expõe `apply` pela UI**. Isso é intencional: planejar e explicar dependências é seguro durante desenvolvimento; publicar conteúdo pertence ao fluxo de release/rollback.

## 9. A versão standalone v9

A ferramenta original possui scripts adicionais de planejamento, reverse engineering e criação de conteúdo.

### Gerar plano de migração

```bash
cd vendor/summit_asset_enrichment_v9
python3 migrate_assets.py --config summit_paths.json plan \
  --out manifests/migration_plan.csv
```

`plan` não altera os roots.

### Aplicar somente AUTO

```bash
python3 migrate_assets.py --config summit_paths.json apply \
  manifests/migration_plan.csv
```

**Importante:** `apply` é uma operação de escrita. Ela não é exposta automaticamente pelo Design Tool e deve ser usada apenas com backup/snapshot, manifest revisado e política de release apropriada.

### Grafo de dependências

```bash
python3 build_dependency_graph.py --config summit_paths.json \
  --out-dir dependency_graph
```

### Inspeção de reverse

```bash
python3 reverse_inspect.py /caminho/arquivo.inx
```

### Scaffold de Monster/NPC

```bash
python3 character_bundle_tool.py example --kind monster --out monster.json
python3 character_bundle_tool.py scaffold monster.json --out generated/MyMonster
```

O scaffold não inventa INX/SMD/SMB; esses continuam no PT Asset Tool.

## 10. AUTO / REVIEW / BLOCKED do migrador standalone

- **AUTO** — origem, destino, estrutura e dependências estão provados dentro da política do migrador.
- **REVIEW** — há boa evidência, mas ainda existe decisão semântica/runtime.
- **BLOCKED** — o caso não pode entrar por bulk copy seguro.

Mesmo no standalone, “AUTO” é uma decisão do plano de migração, não uma autorização geral para produção do jogo.

## 11. Conteúdo novo

### Monster/NPC

Prefira clone/template de uma definição funcional e valide o bundle inteiro.

### Field

SPM e SPP são mais bem compreendidos. SPC exige clone/typed patch. Stage SMD 0.72 não deve ser gerado server-side em bulk enquanto a variante runtime não estiver provada.

### Item

É obrigatório sincronizar server item code map e catálogo do client. Não derive o modelo visual apenas do item code.

## 11. O que nunca fazer automaticamente

- copiar DataServer/WAR/PostBox entre ambientes como assets;
- copiar `LogItemData/*.itm` para “restaurar itens”;
- sobrescrever configs operacionais por missing-only;
- escolher um stage ambíguo só pelo basename;
- copiar INX legacy como destino MODERN;
- promover Stage 0.72 server-side por header apenas;
- aplicar um manifest REVIEW/BLOCKED como se fosse AUTO.

## 12. Fluxo recomendado

1. Rode `server-design-auto`.
2. Resolva REVIEW/BLOCKED pelo Explorador de bundles.
3. Para assets 3D, use o Design Tool e seus gates físicos.
4. Gere planos standalone apenas quando precisar de migração/enriquecimento controlado.
5. Mantenha writes separados de discovery.
6. Antes de produção, valide o bundle completo no runtime.

<!-- PT_GENERAL_CENSUS_GUI_PREFLIGHT_2026-09-21 -->

## Censo geral: configuração e acompanhamento sem ambiguidade

Antes do censo, a GUI valida client, server, Source Summit e Source EU, lista donors salvos, mostra blockers/warnings e gera o comando CLI equivalente. Donors vazios não bloqueiam execução, mas reduzem a evidência de recovery.

O botão usa a configuração persistente. Se `pt_asset.py ... audit general-asset-census --donor-client ...` for executado manualmente, esses argumentos não são importados automaticamente para o formulário. Salve os mesmos roots/donors para tornar os dois caminhos equivalentes.

A UI distingue `NOT_RUN`, `RUNNING`, `FRESH_CONFIG` e `STALE_CONFIG`. Processos iniciados fora da GUI não têm acompanhamento de progresso; o resultado só é observado depois da gravação do relatório final.

<!-- PT_SERVER_ENRICHMENT_WORKFLOW_ARCH_V2_2026-09-22 -->
## GUI Server / Enrichment: uma etapa por workflow

A página **Servidor / Asset Enrichment** não é um segundo editor de conteúdo. A responsabilidade dela é descobrir, medir, classificar, recuperar para staging e validar evidência server-side. Authoring de Item, Monster, NPC, SPM/SPP/SPC e investigação de World Closure pertencem a **Management Legacy**.

A GUI é dividida em seis superfícies independentes:

1. **Configuração** — `server_root`, Source Summit, Source EU e donors read-only.
2. **Diagnóstico** — ambiente, inventário e contratos source/player.
3. **Censo & recuperação** — Censo geral plan-only, agregações em `pt_build`, plano/grafo de donors.
4. **Validação** — gates agregados Client + Server. REVIEW de conteúdo é encaminhado para Management Legacy.
5. **Evidência avançada** — Contract Registry para entender formatos/runtime; não contém o Asset Compiler de conteúdo.
6. **Atividade** — execução, console, histórico e acesso ao resultado dos jobs iniciados nesta página.

Uma tarefa iniciada em Server permanece em **Servidor → Atividade** enquanto executa e depois de terminar. **Abrir resultado** retorna ao workflow que gerou o relatório; o Catálogo não é usado como caixa de saída de jobs.

### Formato dos donors

Cada textarea aceita uma entrada por linha. São válidas tanto a forma persistente quanto uma linha copiada do CLI:

```text
DONOR1=/caminho/para/client
DONOR2=/caminho com espaços/client
--donor-client 'DONOR3=/caminho com espaços/client'
```

Para server, use o mesmo formato ou `--donor-server 'LABEL=/caminho'`. Labels aceitam letras, números, `_` e `-`. Linhas vazias e comentários iniciados por `#` são ignorados. A validação informa a linha e o motivo exatos; se houver erro, roots e donors não são persistidos parcialmente.

<!-- PT_CLIENT_ENRICHMENT_WORKFLOW_ARCH_V3_2026-09-22 -->
## Cliente / Enrichment — arquitetura por workflow

A aba **Cliente / Enrichment** não é um segundo Catálogo nem um segundo explorador de Entidades. Ela organiza operações agregadas client-side em workflows separados:

1. **Visão geral** — root atual, métricas e handoff explícito para Catálogo/Entidades;
2. **Diagnóstico** — `audit client-enrichment`, auditoria das 10 classes e resumos de registry/entidades;
3. **Censo & recuperação** — lado CLIENT do censo geral e dependency graph; Source/donors são a configuração compartilhada em **Servidor → Configuração**;
4. **Validação** — gaps do Client Enrichment e evidência/certificações, sem duplicar authoring;
5. **Texture Enhancement** — somente o workflow global/batch; enhancement individual continua no Catálogo;
6. **Atividade** — execução, console, histórico e retorno ao resultado das tarefas iniciadas nessa página.

### Autoridade por tarefa

- **Catálogo**: asset físico individual, capabilities certificadas e enhancement individual;
- **Entidades**: relações físicas/registry por entidade;
- **Cliente / Enrichment**: análise agregada, reachability, gaps, dependency graph e batch global de texturas.

Uma linha de gap/censo pode fazer handoff para o Catálogo quando existe um path físico, mas o relatório continua sendo lido na aba Cliente.

### Tarefas

Jobs iniciados em Cliente / Enrichment são marcados com `surface=client` e permanecem em **Cliente → Atividade** durante e depois da execução. Eles não são duplicados em **Tarefas gerais**. O botão **Abrir resultado** retorna para Diagnóstico, Censo, Validação ou Texture Enhancement conforme a origem.

### Texture Enhancement global

O batch global continua separado do enhancement individual porque possui lifecycle próprio: geração/resume em `app/pt_build/texture_upscale/runs`, pré-validação de hashes, publicação transacional, backups e rollback. Para uma única textura, use o Catálogo.

<!-- PT_CATALOG_ENTITY_PERF_VISUAL_V4_2026-09-22 -->

## Catálogo / Entidades — performance e Visual Bundles (V4)

### Performance

`Entidades` usa um snapshot derivado do catálogo + registry, invalidado por revisão. A listagem e a busca reutilizam esse snapshot; apenas o detalhe selecionado calcula `physical_dependency_status`. A resposta de lista é resumida e não transporta `all_paths`, `registry_assets` ou relações completas.

No Catálogo, selecionar um asset não recarrega a listagem. Buscas obsoletas de Catálogo/Entidades são canceladas no browser. A galeria só cria `<img>` de preview quando o modo Galeria está visível. Previews BMP/TGA decodificados ficam em cache limitado por `path + mtime_ns + size`.

A API expõe métricas não autoritativas de diagnóstico (`performance.query_ms` no Catálogo e contadores/tempo do snapshot em Entidades). Elas servem para observar o hot path; não são gates de release.

### Item runtime != representação visual

O Catálogo distingue duas camadas:

- **identidade runtime**: código sITEM/OpenItem (ex.: `DA102`, `DA301`);
- **Visual Bundle**: conjunto físico de icon/drop/equipped-model/config/textures que compartilha uma aparência comprovada.

Um Visual Bundle nunca funde códigos runtime. Itens separados podem aparecer no mesmo bundle quando o registry comprova o mesmo conjunto completo de dependências de textura. Configs/modelos equipados entram no bundle somente quando a cadeia registry comprova a mesma assinatura visual. Um `Axxx.INI` same-stem de um INX comprovado pode ser anexado quando o arquivo físico existe.

O filtro `Entidade -> Catálogo`, para ITEM, abre os paths do Visual Bundle quando este existe. Isso permite navegar em conjunto por arquivos como `it<code>`, texturas drop e configs de aparência sem transformar convenções de filename em identidade runtime.

Agrupamento por semelhança parcial de nome ou por uma única textura compartilhada não é promovido a verdade de identidade.

<!-- PT_CATALOG_PERSISTENT_ITEM_RELATIONS_V5_2026-09-22 -->

## Catálogo persistente e relações visuais de item · V5

O Catálogo/Entidades não deve fazer uma nova varredura física do client apenas porque o utilizador mudou de aba ou reiniciou a UI. O ponto de sincronização física é **Reindexar**. A navegação normal reutiliza o censo persistido em `pt_build/state/asset_registry/asset_inventory.json`, o pairing INX e snapshots derivados. Alterações externas ao client tornam-se visíveis após Reindexar.

A representação visual de item é uma visão derivada, não uma nova identidade runtime. O índice `pt_build/state/item_visual_bundle_index_v1.json` reutiliza o runtime item catalog, o `asset_inventory.json` e, quando disponível, `pt_build/enrichment_vendor/dependency_graph/graph.json`. Ele separa explicitamente: **Inventário · imagem**, **Chão · modelo**, **Chão · textura**, **Equipado · config**, **Equipado · modelo** e **Equipado · textura**. Códigos runtime distintos continuam distintos mesmo quando reutilizam exatamente o mesmo conjunto visual.

O agrupamento automático só usa evidência persistida. Para itens diferentes, um bundle visual compartilhado requer o mesmo conjunto completo e não vazio de dependências de textura. Configs/INX/modelos equipados entram quando o registry ou o dependency graph prova a ligação. Sem prova, o asset permanece fora daquela relação.

O utilizador pode corrigir o **papel visual** de um asset no detalhe do Catálogo. A correção fica apenas no estado da UI; não altera o client. A UI preserva e exibe a classificação automática original, permitindo distinguir evidência automática de override manual.
