# Summit Tale — Asset Enrichment integrado ao PT Asset Tool

Estado da especificação server-side: **1.0 (04/09/2026)**.

Este documento integra ao PT Asset Tool o mapa técnico final do Summit Server. O objetivo é que o Design Tool trate **client e server como raízes independentes**, unidas por bundles funcionais, sem misturar conteúdo estático com persistência, segurança ou logs.

## Roots de design

- `client_root`: assets consumidos pelo client e inventário físico do PT Asset Tool.
- `server_root`: conteúdo e metadata consumidos pelo Summit Server.
- `pt_build`: único local autorizado para relatórios, candidates e outputs temporários.

O servidor permanece **read-only** nesta revisão. Nenhuma funcionalidade desta camada autoriza publicação no server.

## A unidade correta é o bundle

### Monster

`GameServer/monster/*.inf` → `name/*.zhoon` → model lógico (`char/.../*.ini`) → `*.inx` → `*.smd` / `*.smb` → texturas, mais drops e referência de spawn/evento.

### NPC

`GameServer/npc/*.npc` → `name/*.zhoon` → model package compartilhado com o client/server → placement `SPC` quando aplicável → lógica de shop/quest/evento.

### Field

Stage `SMD/ASE` → `GameServer/Field/<stage>.spp` + `.spc` + `.spm` → entidades Monster/NPC referenciadas.

- SPP Summit atual: `200 × 12 = 2400` bytes.
- SPC Summit atual: `100 × 504 = 50400` bytes.
- Stage 0.72 server-side continua **REVIEW** até a variante runtime WORD/DWORD estar provada no server, independentemente da certificação do pipeline client-side.

### Item

`GameServer/OpenItem/*.txt` (+ ZHOON quando usado) → item code map do server → catálogo do client → `DorpItem`/modelo/icon/categoria → drops/shops.

Item code não deve ser inferido como filename visual por igualdade de stem.

## Ciclo de vida server-side

O classificador `server_lifecycle.py` usa **path + formato + papel**, nunca somente extensão.

| Classe | Exemplos | Política |
|---|---|---|
| Asset estático | INF, NPC, ZHOON, OpenItem TXT, SPM | bundle validation antes de autoria |
| Metadata de field | SPP | layout Summit validado |
| Metadata em review | SPC | typed/clone-based only |
| 3D compartilhado | INI lógico, INX, SMD, SMB, ASE | PT Asset pipeline, server read-only |
| Visual compartilhado | BMP/TGA/DDS/JPG/PNG | só com referência provada |
| Config operacional | `Configs/*` | review deliberado |
| Persistência | `DataServer/*`, `PostBox/*`, WAR | bloqueado como asset |
| Segurança/estado | `cpItem.dat`, `BlessCastle.dat`, `BlackUser/*` | bloqueado |
| Integridade runtime | `FuncBox/*` | bloqueado |
| Logs/forensics | `LogItemData/*.itm`, `Log*`, `LOGS/*` | excluído da autoria |
| Binários/tooling | EXE/DLL/OCX/PDB/REG/BAT etc. | excluído |

O caso `LogItemData/<Head>@<Checksum>.itm` é deliberadamente **FORENSICS_ONLY**: é snapshot/log de `sITEMINFO`, não definição estática de item.

## INX e 3D compartilhado

O server possui INX/SMD/SMB reais e loaders da mesma família do engine. O Design Tool não considera essas cópias “lixo de client”. Elas entram no grafo apenas quando o caminho funcional prova que são necessárias.

INX conhecidos:

- `LEGACY_120`: 67.084 bytes — reconhecer como geração legítima, mas não usar como destino direto do Summit atual.
- `MODERN_172`: 95.268 bytes — layout esperado pela geração atual, ainda sensível a path/keywords.

SMD Model 0.62 e SMB continuam delegados ao PT Asset Tool e aos seus gates físicos. A presença no server não cria um writer server separado.

## UI

A aba **Servidor / Enrichment** mostra:

- raiz do servidor configurada;
- último environment/design/inventory report;
- quantidades de assets candidatos versus arquivos explicitamente excluídos;
- estado dos bundles Monster/NPC, Field e OpenItem;
- política de lifecycle usada pelo backend;
- ações automáticas read-only para validar ambiente, executar o Asset Enrichment e fazer o inventário completo.

A raiz pode ser persistida com:

```bash
python3 pt_asset.py config set-server-root "/caminho/Servidor"
```

ou fornecida por `--server-root` / `PT_SERVER_ROOT`.

## Gates automáticos

- `validate server-environment-auto`: preflight read-only e prova de separação de lifecycle.
- `audit server-inventory`: censo físico completo por path/lifecycle e layouts conhecidos.
- `audit server-bundles`: Monster/NPC, referências literais, INI lógico→INX entre server/client.
- `audit server-fields`: SPM/SPP/SPC + stage candidates por basename; ambiguidade fica REVIEW.
- `audit server-items`: CODE/ZHOON/duplicatas de OpenItem; não finge fechar catálogo client.
- `validate server-design-auto`: agrega environment + inventory + Monster/NPC + Field + OpenItem.

## Política de segurança

- `server_write_authorized = false`
- `persistence_write_authorized = false`
- `client_write_authorized = false`
- qualquer output automático fica sob `pt_build`
- persistência/log/segurança não pode ser promovida por missing-only, comparação de árvore ou extensão.

## Referência original

A versão final recebida do Asset Enrichment está preservada em:

`docs/reference/Summit_Server_Arquivos_e_Funcionamento_2026-09-04.docx`


## Gate automático integrado client + server

Depois do censo inicial do server e do primeiro physical regression do client, a validação rápida de integração é `validate integration-regression-auto`. O gate usa simultaneamente `--client-root` e `--server-root`, continua read-only para ambas as árvores e grava evidência apenas em `app/pt_build`.

Ele cobre: preflight dos dois ambientes; prova Blender da representação affine de animação; pose-space bound/standalone; corpus SMB e outliers exatos; codecs/TGA outlier; e reconstrução dos censos server Monster/NPC, Field e OpenItem com resolução case-insensitive compatível com o runtime Windows. Persistência, logs, segurança e configs operacionais continuam fora da superfície de autoria.


## Summit Asset Enrichment v9 ativo

A distribuição usa exclusivamente `vendor/summit_asset_enrichment_v9/` (`v9-fix136`). Versões anteriores não fazem parte do pacote operacional; o histórico delas permanece no Git. A UI integra os conceitos e a análise server-aware, mas **não expõe automaticamente os comandos de escrita** do pacote vendorizado. `migrate_assets.py apply`, `install-apply` e rollback permanecem tooling separado até promoção explícita dos gates de produção.

## Guias de uso integrados

Para operação do Design Tool e do Asset Enrichment sem precisar começar pela documentação de reverse engineering:

- `GUIA_DESIGN_TOOL.md` — catálogo, entidades, Blender, gates, writers e segurança do PT Asset Tool;
- `GUIA_ASSET_ENRICHMENT.md` — bundles server-side, lifecycle, UI e ferramenta standalone v6;
- `GUIA_WORKFLOW_CLIENT_SERVER.md` — workflow ponta a ponta de Monster/NPC, Field e Item.

A aba **Ajuda / Guias** da UI resume esse mesmo modelo mental e aponta para os documentos completos do pacote.


## Release 1.0

Os critérios de readiness, runtime acceptance e promoção segura dos writers estão em `docs/release/RELEASE_1_READINESS.md`.
