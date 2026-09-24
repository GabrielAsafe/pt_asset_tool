# Management Legacy + Legacy Authoring Python

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Data:** 2026-09-21  
**Status:** guia operacional atual para a integração Management/World Closure/Authoring.

## 1. Objetivo

Esta integração substitui o uso operacional de ferramentas históricas onde o formato/workflow já foi provado. O princípio é:

```text
EXE histórico → evidência estática
source/corpus  → contrato
contrato       → parser/writer Python
writer         → stage/transação verificada
```

Nenhum executável histórico precisa ser iniciado.

### Estado real do reverse / integração

O pacote Management foi inventariado por **hash binário único**. O estado operacional não vem mais da tabela histórica `legacy_management_tools.json`: ela permanece apenas como provenance/taxonomia. A fonte de verdade atual é `pt_asset_tool.legacy_apps.reverse_manifest`, que exige uma decisão explícita para cada PE único do arquivo fornecido.

A regra de produto é: **portar a capacidade útil, não clonar a interface Windows**. Quando o comportamento antigo é correto e o formato foi provado, o Python preserva a semântica com testes. Quando o legado é destrutivo, version-specific ou incompatível com o stack atual (localhost + SQLite + Fedora/Wine), o substituto corrige o desenho e registra a diferença.

Estado operacional resumido:

| Ferramenta histórica | Substituto Python atual |
|---|---|
| NPCManager | SPC canónico, layout 100 × 504 bytes |
| PriTaTor | Item/Monster/NPC/Field authoring + Bulk EXP/Gold + World Closure |
| Editor de Itens | OpenItem create/edit para runtime codes conhecidos |
| Editor de Monstros | Monster INF create/edit estruturado |
| ItemDistributor | Postbox plan/apply com append + backup |
| Procura item pelo nome | scanner userdata/warehouse + duplicados |
| ControllerUser / Editor de conta | inspeção, stats source-backed, rename, migração de conta, inventário, delete/batch/clear revisado |
| MudarNome | rename transacional de personagem/conta, incluindo 6 slots de userinfo |
| Level Editor | Level/XP com offsets provados e tabela XP auditada |
| ClanSoDManager / SoD Atualiza | SQLite local |
| Editor Japaokiko | Hotuk, SPC, BPRank SQLite, campos de personagem; rede Windows removida |
| PTprotector | análise de regras/logs + bloqueio SQLite explícito |
| Portas SQL | obsoleto no stack localhost + SQLite |
| ConfigRestarter.ini | supervisor Linux/Wine baseado no contrato disponível |

Limites deliberados não são apresentados como “apps faltando”. Por exemplo, o reverse do ControllerUser prova busca por `Code/Head/CheckSum` e delete persistente, mas não prova um writer arbitrário desses três identificadores; portanto a UI oferece busca/inspeção/delete, não um editor inventado. Registro de um novo código `sITEM` no runtime também continua separado de criar uma definição OpenItem para um código que o runtime já conhece.

## 2. O que veio do Management

### PriTaTor

Evidência para:

- Monster search/edit;
- EXP/gold/drop lines;
- map actor membership;
- boss membership;
- spawn rate/times;
- item search/add-remove workflow;
- NPC workflow;
- backup/restore workflow.

### NPCManager

Evidência para `Field/*.spc` e campos visíveis de NPC fixo. A autoria atual usa o ABI/corpus SPC provado pelo projeto, não o EXE como writer.

### ItemDistributor / scanners / admin tools

As capacidades comprovadas foram portadas para `pt_asset_tool.legacy_apps`. Elas continuam fora do **asset authoring** porque operam persistência de conta/personagem, mas são funcionalidades Python operacionais da aplicação: Postbox, scanner/duplicados, rename, Level/XP, stats source-backed, migração de conta e administração de inventário comprovada pelo reverse.

### ItemEditor / Editor de Monstros

A existência do workflow é confirmada. Internals nativos não provados não são usados como autoridade de writer.

## 3. Taxonomia PriTaTor

A classificação histórica por prefixo continua disponível **internamente** como evidência auxiliar. O operador não precisa conhecer, escolher ou manter essa tabela na UI. Identidade runtime continua baseada no catálogo `sITEM` source-verificado.

## 4. Contrato runtime sITEM

O adapter expõe os nomes C++ corretos, incluindo:

- `code`;
- `ItemFilePath`;
- `Class`;
- `DorpItem`;
- `SetModelPosi`;
- `SoundIndex`;
- `WeaponClass`.

Paths derivados:

```text
image/Sinimage/Items/<ItemFilePath>/it<DorpItem>.bmp
image/Sinimage/Items/DropItem/it<DorpItem>.ASE
```

Isso é usado para closure física e identity gating.

## 5. Auditoria Management

A auditoria é suporte à autoria. Com roots configurados, cruza:

```text
SPM → Monster → item code → OpenItem → sITEM → DorpItem → client assets
```

Sem `server_root`, pode operar apenas em modo contrato/evidência.

## 6. World Closure Explorer

O explorer não é um editor. Ele responde “o que está conectado, presente, ausente ou ambíguo?”.

### Itens

Mostra code, runtime identity e presença do ícone/drop model esperado.

### Maps/SPM

Mostra metadata de campo e referências resolvidas.

### Monster/NPC

Mostra definição e resolução correspondente.

## 7. Ponte para Authoring

Selecionar uma linha **não muda de tab nem abre o editor automaticamente**. O detalhe explica a closure e, se houver um target authorable, mostra uma ação explícita como `Editar monstro`, `Editar NPC`, `Editar SPM` ou `Abrir definição do item`.

Quando essa ação é acionada, o path exato é transportado para o editor. Em ITEM, a resolução vem do census de OpenItem; duplicidade fica bloqueada.


### Como interpretar `REVIEW`

`REVIEW` nunca deve aparecer sozinho. O Explorer expõe `review_reasons` e `review_actions`: motivo humano, detalhe técnico e a próxima ação possível. Exemplos: OpenItem ausente para um código referenciado, actor SPM sem Monster único, ícone/ASE esperado ausente ou erro de leitura/encoding.

Em Monster/NPC, `item_reference_count` é uma varredura ampla e **0 não significa “sem drop”**. Para Monster, relatórios novos também expõem `drop_item_reference_count`, derivado especificamente das diretivas source-backed `FallItem`/`ExtraFallItem`. Mesmo `drop_item_reference_count = 0` não prova ausência total de recompensa: money drops ou mecanismos ainda fora do contrato podem existir. Referências `.zhoon` são companion/visual histórico, não tabela de drop.

## 8. Authoring pipeline

```text
Inspect
→ Spec
→ Stage
→ Validate
→ Publish
→ Verify
→ Runtime review
→ Restore
```

### Inspect

Lê o source target e produz identidade/hash/layout/fields.

### Spec

JSON Python-native que descreve apenas a mudança pretendida.

### Stage

Gera overlay/manifest em `pt_build`. Não escreve target.

### Publish

Publica somente o bundle validado, com backup/hash/replace atómico/post-verify.

### Restore

Restaura o backup da própria transação e recusa drift desconhecido.

## 9. ITEM

### CREATE

Exemplo:

```json
{
  "kind": "ITEM",
  "mode": "CREATE",
  "path": "GameServer/OpenItem/WA121.txt",
  "fields": {
    "name": "Created Axe",
    "code": "WA121",
    "price": 1000
  }
}
```

O code precisa existir na runtime table source-verificada.

### EDIT

```json
{
  "kind": "ITEM",
  "mode": "EDIT",
  "path": "GameServer/OpenItem/WA121.txt",
  "expected_sha256": "...",
  "patch": {
    "set": {"name": "New Axe", "price": 999}
  }
}
```

Unknown lines são preservadas.

## 10. MONSTER

```json
{
  "kind": "MONSTER",
  "mode": "EDIT",
  "path": "GameServer/Monster/Cuepy.inf",
  "patch": {
    "set": {"experience": 777},
    "drops": [
      {"percentage": 70, "items": ["WA121", "WC108"]},
      {"percentage": 30, "money": [1, 10]}
    ]
  }
}
```

O writer suporta item drop, money drop, NoItem, extra drop, dialogs e linked file.

## 11. NPC

```json
{
  "kind": "NPC",
  "mode": "EDIT",
  "path": "GameServer/NPC/Shop.npc",
  "patch": {
    "shops": {
      "weapon": ["WA121", "WS210"],
      "defence": ["DA112"],
      "etc": []
    },
    "dialogs": ["Hello player"]
  }
}
```

## 12. SPM

Operações:

```text
ADD_ACTOR
REMOVE_ACTOR
ADD_BOSS
REMOVE_BOSS
SET_DIRECTIVE
```

Diretivas SET:

```text
MAX_ACTOR_POS
MAX_ACTOR
DELAY
```

Boss pode receber `slave_count` e lista de `hours`.

## 13. SPP

Canónico:

```text
200 records × 12 bytes
<state:int32, x:int32, z:int32>
```

Somente índices válidos e layout canónico são aceitos.

## 14. SPC

Canónico:

```text
100 records × 504 bytes
```

Operações:

```text
ADD
REPLACE
REMOVE
```

O record é construído pelo writer nativo do projeto.

## 15. CLI

```bash
python3 pt_asset.py legacy-authoring capabilities
python3 pt_asset.py legacy-authoring inspect --kind ITEM --path GameServer/OpenItem/WA121.txt
python3 pt_asset.py legacy-authoring stage --spec spec.json
python3 pt_asset.py legacy-authoring publish --confirm 'APPLY ASSET BUNDLE'
python3 pt_asset.py legacy-authoring restore --confirm 'RESTORE ASSET BUNDLE'
```

## 16. GUI

A aba foi reorganizada por **tarefas**, não por ferramentas históricas:

- **Item · criar/editar** — mostra requisitos, lookup runtime e abre ITEM CREATE/EDIT;
- **Monstro · criar/editar** — mostra campos mínimos, relação com ModelFile e placement SPM;
- **NPC · criar/editar** — mostra definição NPC, shops/dialogs e placement SPC;
- **Mapa / Field** — separa SPM (spawns), SPP (start points) e SPC (NPCs fixos) e deixa claro que a geometria Stage do client é outro pipeline;
- **World Closure** — constrói/consulta as relações e transporta targets resolvidos para o editor;
- **Evidência técnica** — hashes, ferramentas históricas e matriz de substituição Python. Não é requisito para authoring.

Fluxo operacional:

1. escolha a tarefa (Item/Monstro/NPC/Mapa);
2. leia **O que você precisa**;
3. use CREATE/EDIT ou encontre o target no World Closure;
4. Inspect/Create;
5. ajuste spec;
6. arme BUILD;
7. Stage;
8. revise manifest;
9. arme ASSET DEPLOY;
10. Publish;
11. valide em runtime;
12. Restore se necessário.

## 17. Por que `REVIEW` e authoring podem coexistir?

`REVIEW` pertence à closure/auditoria. O writer possui gates próprios.

Um item pode ter:

```text
OpenItem OK
sITEM OK
icon PRESENT
DropItem ASE MISSING
→ REVIEW
```

Se a definição OpenItem está identificada e o code runtime é válido, ela pode continuar editável. A ausência do ASE ainda fica visível e não é escondida.

## 18. Boundaries

Bloqueado:

- novo code runtime `sITEM`;
- userdata/warehouse;
- internals não provados de executáveis nativos;
- target ambíguo;
- non-canonical SPP/SPC;
- source drift;
- publish/restore sem confirmação;
- write fora da transação tipada.

## 19. Regra operacional

Não use os executáveis históricos para “completar” uma operação que o Asset Tool bloqueou. Um bloqueio significa que falta contrato/evidência para aquele write. Recupere/prove o formato primeiro e então promova o writer com testes/corpus/roundtrip.

<!-- PT_MANAGEMENT_LEGACY_WORKFLOW_V9_2026-09-23 -->
## Management Legacy V9 — workflows por tarefa, SQLite e seleção source-backed

A superfície **Management Legacy** é organizada por tarefa. O editor Python não é global: ele aparece somente dentro de **Item**, **Monstro**, **NPC** ou **Mapa / Field** e mantém estado independente por workflow. **Personagem / Conta**, **Itens / Postbox**, **Admin local** e **World Closure** não reutilizam esse editor.

### Item

A UI carrega o catálogo runtime source-backed e cruza os códigos com `GameServer/OpenItem/*.txt`. Os seletores mostram `CODE — Nome` quando existe uma definição OpenItem, ou indicam claramente quando o código runtime ainda não possui OpenItem. O operador não precisa memorizar nem digitar códigos em operações de distribuição/shops/drops assistidas.

Criar Item nesta página significa criar uma nova definição OpenItem para um código runtime já conhecido. Registrar um código `sITEM` totalmente novo continua fora do writer certificado.

### Monstro / NPC / Mapa

Cada tarefa monta o writer correspondente. Monstro e NPC usam os parsers/writers textuais source-backed; Mapa seleciona explicitamente SPM, SPP ou SPC. `World Closure` serve para localizar relações, explicar REVIEW e abrir o target na tarefa correta — não existe um segundo editor global.

O fluxo de escrita é sempre:

`selecionar target → inspect/create → stage em pt_build → revisar manifest → publish armado → validar no jogo → restore se necessário`

`Publish` só é habilitado depois de um Stage bem-sucedido da tarefa atual. Um manifest antigo de outra tarefa não é reutilizado silenciosamente.

### Personagem / Conta e Postbox

Personagens e contas existentes são lidos de `DataServer/userdata` e `DataServer/userinfo` e aparecem como seletores. Alterações viram planos revisáveis e, quando aplicáveis, usam backup e guards de drift. Distribuição via Postbox usa um item escolhido do catálogo `CODE — Nome`.

### Admin local / SQLite

O runtime atual usa SQLite local. A UI procura arquivos `.sqlite3`, `.sqlite` e `.db`, abre-os em modo read-only para descobrir o schema e escolhe a base pelo conjunto de tabelas realmente presente. SoD, BPRank e bloqueio de conta verificam a tabela/colunas antes de produzir plano. Quando existem bancos separados, a ação seleciona um candidato que suporte a capability correspondente.

O adapter SQL Server/pyodbc permanece apenas como referência/migração histórica em código isolado e não é usado pela superfície Fedora atual.

### Workspace de planos

Planos e backups Legacy usam o app root canônico:

`app/pt_build/legacy_apps/...`

O backend aceita tanto o root do repositório quanto o diretório `app/` sem gerar `app/app/pt_build`.

### Erros HTTP

- `404`: identidade/arquivo/target não existe.
- `409`: configuração ou armamento necessário está ausente.
- `422`: payload, valor, confirmação ou operação foi rejeitado pelo contrato.
- `500`: falha interna inesperada.

Requests canceladas pelo browser durante navegação/filtros são tratadas como disconnect benigno; `BrokenPipeError` não gera uma segunda resposta nem traceback ruidoso.
