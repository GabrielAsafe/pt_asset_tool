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
