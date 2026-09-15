# Handoff técnico consolidado — Summit / PT Asset Tool

Data de consolidação: 2026-09-06  
Release documental: 0.17.1  
Base funcional: 0.17.0 Full Summit Superset

## 1. Objetivo do projeto

O objetivo deixou de ser simplesmente comparar árvores de ficheiros ou copiar tudo que existir em versões antigas. A aplicação deve conseguir responder, para cada entidade do jogo, quatro perguntas:

1. **O que esta entidade precisa para existir no cliente e no servidor?**
2. **Quais componentes já existem no Summit?**
3. **Quais componentes podem ser recuperados de fontes conhecidas, com proveniência?**
4. **Quais componentes podem ser gerados de forma segura quando não existe um servidor oficial disponível?**

A unidade de trabalho passa a ser a entidade e o seu contrato, não o diretório.

```text
ENTITY
  -> contracts
  -> required / optional / reference-only assets
  -> source/runtime evidence
  -> resolver multi-source
  -> aggregation plan
  -> staging overlay
  -> validation
```

O objetivo final é permitir evolução independente do Summit: conteúdo novo deve poder ser criado e integrado mesmo sem acesso ao servidor oficial atual, desde que o lado server-side seja inferível ou gerável a partir de contratos certificados.

## 2. Fontes usadas durante a investigação

### Cliente

- `CS / SUMMIT_CLIENT` — `/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente`
- `CO / OFFICIAL_CLIENT` — `/home/gabriel/old/velho`
- `CP / PT_EU_CLIENT` — `/home/gabriel/armazem/priston/servidor_cliente_PT_EU/Files/Game`

### Servidor

- `SS / SUMMIT_SERVER` — `/home/gabriel/Área de Trabalho/summit/Servidor`
- `SP / PT_EU_SERVER` — `/home/gabriel/armazem/priston/servidor_cliente_PT_EU/Files/Server`
- `SE / EXMACHINA_SERVER` — `/home/gabriel/armazem/priston/ExMachina/server`

### Source

- `CURRENT_SOURCE` — `/home/gabriel/Área de Trabalho/summit/SourceCode`
- `EU_REFERENCE_SOURCE` — `/home/gabriel/armazem/priston/PristonTale-EU-main-master`

Os paths acima são configuração conhecida da workstation usada nos runs físicos. A aplicação não deve tornar estes paths requisito estrutural; devem continuar configuráveis.

## 3. O que foi aprendido durante a investigação

### 3.1 Comparar apenas paths produz muitos falsos positivos

A comparação inicial mostrou que diferenças de capitalização (`.TGA` vs `.tga`) e `Thumbs.db` produziam milhares de diferenças sem significado. Também foi necessário distinguir:

- mesmo path ignorando case;
- mesmo basename em pasta diferente;
- mesmo conteúdo por SHA-256;
- mesmo path com conteúdo diferente;
- asset exclusivo de uma fonte.

Conclusão: **path, basename e conteúdo são dimensões diferentes**. Nenhuma delas isoladamente é suficiente para decidir merge.

### 3.2 O corpus client é híbrido

O client oficial disponível não é simplesmente “igual ao Summit” ou “igual ao PT_EU”. Nos primeiros censos de paths comuns e conteúdo idêntico, ele mostrou parentesco relevante com ambos. Isso levou à política atual: official é baseline de linhagem, mas não é tratado como fonte universalmente completa ou como vencedor cego.

### 3.3 O primeiro censo server estava contaminado por layout de pacote

O PT_EU Server vem com prefixes como `game-server/` e `login-server/`, enquanto Summit/ExMachina começam diretamente em namespaces como `GameServer/`, `char/` e `Field/`. Sem normalização, todos os 8.833 ficheiros do PT_EU apareciam falsamente como exclusivos.

A normalização server passou a tratar `game-server/` como packaging e a manter `login-server/` separado até existir contrato seguro.

### 3.4 O Summit Server tem grande volume de estado runtime

Foi observado que `LogItemData/` responde por aproximadamente 124 mil ficheiros `.itm` de tamanho fixo no corpus examinado. Estes ficheiros não devem ser usados como catálogo de assets ou definições estáticas.

Política adotada: logs, userdata, warehouse, dumps, runtime state, temporários e tooling podem ser preservados para investigação, mas não entram automaticamente no overlay distribuível.

### 3.5 “Asset presente” não significa “feature implementada”

Assassin e Shaman foram a prova mais importante. O client Summit contém a grande maioria — e depois todos os assets conhecidos/certificados do contrato atual — mas o runtime continua bloqueado por source/registry.

Isso levou à separação formal entre:

```text
ASSET_PRESENCE
CONTRACT_DISCOVERY
RUNTIME_MIGRATION
ENTITY_COMPLETENESS
```

Um audit nunca deve promover uma classe para COMPLETE apenas porque todos os ficheiros que o scanner conhece estão presentes.

### 3.6 O áudio das novas classes pode ser provado pelo source

A referência EU contém ranges/tabelas de sound IDs para Assassin e Shaman. O audit evoluiu de apenas 7 calls diretas descobertas para uma família source-backed de 51 WAVs:

- Assassin: 17 WAVs;
- Shaman: 34 WAVs.

No run físico 0.14.1, os 51 estavam presentes no cliente Summit.

### 3.7 Motion roots de Assassin/Shaman foram provados fisicamente

O source reference fornece configs de body/head; os INX foram resolvidos no target e os `LinkFile` foram verificados pelo link code/SpeedSum, não por nome.

Resultados físicos:

- Assassin: `M6Bip.inx` -> `m6.smb`, 17 records `SKILL`, SMB validation PASS;
- Shaman: `M7Bip.inx` -> `m7.smb`, 18 records `SKILL`, SMB validation PASS.

Isto estabeleceu a cadeia:

```text
PLAYER_CLASS
 -> body/head config
 -> INX config
 -> verified LinkFile
 -> motion root INX
 -> MotionInfo
 -> paired SMB
```

### 3.8 A seleção da animação de skill depende da registry, não da ordem dos motions

O runtime usa `MotionInfo.SkillCodeList[]` como índice em `SkillDataCode[]` e compara com o play skill code ativo. Portanto não é seguro mapear a primeira skill para o primeiro motion, etc.

A ferramenta passou a extrair `SkillCodeList`, `JobCodeBit`, `EventFrame`, `ItemCodeList` e demais campos relevantes do `smMOTIONINFO`.

### 3.9 O problema atual de Assassin/Shaman é principalmente runtime

O run físico 0.16.0 do agregador chegou a:

```text
planned assets:             2080
KEEP_TARGET:                1669
RECOVER:                     255
RECOVER_PREFERRED_VARIANT:    44
OPTIONAL_MISSING:            112
core unresolved:               0
materialized recoveries:      299
archived reference variants:   88
runtime_ready:              false
```

Os únicos blockers de runtime reportados foram Assassin e Shaman:

- `RUNTIME_DISABLED_BY_MAX_JOBNUM`;
- `CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES`.

Ou seja: o core físico do superset de classes pode ficar pronto antes do runtime das duas classes.

### 3.10 Variantes cosméticas não devem bloquear o core

O primeiro agregador tratava 44 conflitos e 112 ausências de INX como blockers. O run real mostrou que eram variantes de body/head/costume/seasonal e não requisitos mínimos da classe.

A partir de 0.16.0:

- variantes divergentes usam donor priority no overlay;
- todas as versões são preservadas em `reference_variants/`;
- gaps opcionais ficam em `optional_gaps.tsv`;
- somente core unresolved bloqueia o staging.

### 3.11 O melhor modelo é “Vault/Catalog/Build”, não merge destrutivo

Mesmo sem um object store dedicado completo, toda a arquitetura foi alinhada a esta separação conceitual:

```text
SOURCE CORPUS / REFERENCES
        |
        v
CATALOG + PROVENANCE + CONTRACTS
        |
        v
STAGING BUILD / OVERLAY
```

Nenhum donor deve ser destruído, e nenhum target deve ser sobrescrito como efeito colateral de um audit.

## 4. Evolução implementada na aplicação

### 0.14.0 — Source Contracts

Criada a fundação:

- `source_catalog.py`;
- `source_evidence.py`;
- `contract_graph.py`;
- `source_contract_census.py`;
- `skill_contract_census.py`;
- configuração de source current/reference e donors;
- audit Assassin/Shaman na GUI/CLI.

O Fix136 deixou de ser apenas um “fix” conceitual e passou a servir como fonte de regras para skills/assets.

### 0.14.1 — Contract Coverage

Correções:

- completeness deixou de significar apenas “todos os assets conhecidos presentes”;
- scanner ativo passou a excluir `old_src_antes_do_porte`, builds, deps e tooling;
- famílias completas de áudio Assassin/Shaman foram incorporadas;
- handlers passaram a reconhecer diferentes spellings de skill IDs.

### 0.14.2 — Motion Contracts

Adicionado:

- `player_class_motion_contract.py`;
- class config -> INX -> verified LinkFile -> MotionInfo -> SMB;
- validação INX/SMB;
- fail-closed para skill-specific motion assignment.

### 0.14.3 — Skill Motion Registry

Adicionado:

- extração física de `SkillCodeList`;
- parser de registry current/reference;
- deteção de incompatibilidade entre índices usados pelos INX e a registry Summit;
- distinção de passivas sem motion obrigatório.

### 0.15.0 — Aggregation MVP

Adicionado primeiro planner/materializer:

- contracts das 10 classes;
- donor priority;
- SHA-256 dedupe;
- staging somente em `pt_build`;
- manifest/provenance/conflicts/missing;
- GUI e CLI.

### 0.16.0 — Superset Player-Class Aggregator

Corrigido o modelo de variantes:

- core vs optional;
- `RECOVER_PREFERRED_VARIANT`;
- `reference_variants/`;
- optional gaps não bloqueiam classe;
- runtime blockers separados de asset readiness.

### 0.17.0 — Full Summit Superset

Adicionado:

- `client-superset`;
- `server-superset`;
- `summit-superset` combinado;
- normalização de namespaces server;
- exclusão de runtime state/tooling;
- `reports_bundle.zip` pequeno para feedback;
- mesmo backend usado por CLI, HTTP e GUI.

### 0.17.1 — Documentation Handoff

Esta release não altera a política de escrita nem os writers. Consolida todo o contexto técnico necessário para integrar/manter a aplicação sem depender do histórico do chat.

## 5. Arquitetura atual relevante

### Camada source/evidence

- `app/pt_asset_tool/source_catalog.py`
- `app/pt_asset_tool/source_evidence.py`
- `app/pt_asset_tool/source_contract_census.py`

Responsabilidade: ler source current/reference read-only e produzir evidência normalizada.

### Camada contracts

- `app/pt_asset_tool/contract_graph.py`
- `app/pt_asset_tool/skill_contract_census.py`
- `app/pt_asset_tool/player_class_motion_contract.py`
- `app/pt_asset_tool/entity_catalog.py`
- `app/pt_asset_tool/server_bundle_census.py`
- `app/pt_asset_tool/server_field_census.py`
- `app/pt_asset_tool/server_item_census.py`

Responsabilidade: representar dependências e evidência por entidade.

### Camada resolver/aggregation

- `app/pt_asset_tool/resolver.py`
- `app/pt_asset_tool/aggregation.py`
- `app/pt_asset_tool/superset_aggregation.py`
- `app/pt_asset_tool/build_provenance.py`

Responsabilidade: escolher fontes, preservar variantes, materializar overlay e validar staging.

### Superfícies de aplicação

- `app/pt_asset.py`
- `app/pt_asset_tool/cli.py`
- `app/pt_asset_tool/ui_app.py`
- `app/pt_asset_tool/ui_static/index.html`
- `app/pt_asset_tool/ui_static/app.js`

CLI, API HTTP e GUI devem chamar as mesmas funções de backend. Evitar implementar lógica de negócio diretamente em JS ou handlers HTTP.

## 6. Estados e semântica que devem ser preservados

### Asset resolution

- `PRESENT_TARGET`
- `RECOVERABLE_REFERENCE`
- `CONFLICT`
- `MISSING_UNKNOWN`

### Aggregation actions

- `KEEP_TARGET`
- `RECOVER`
- `RECOVER_DEDUPED`
- `RECOVER_PREFERRED_VARIANT`
- `OPTIONAL_MISSING`
- `ARCHIVE_REFERENCE_ONLY`
- `EXCLUDE_NON_DEPLOYABLE`
- `TARGET_CASE_COLLISION`
- `DONOR_CASE_COLLISION`
- `SOURCE_FILE_MISSING`

### Readiness

Asset readiness e runtime readiness são independentes.

Exemplo válido:

```text
aggregate_state = CORE_READY_STAGING_WITH_OPTIONAL_GAPS
runtime_ready   = false
```

Não fundir estes dois sinais num único booleano de “complete”.

## 7. Política de proveniência

Para qualquer asset recuperado deve ser possível responder:

- path lógico/canónico;
- entidade e role;
- source escolhido;
- path físico original;
- hash SHA-256;
- donor candidates;
- número de conteúdos distintos;
- ação do planner;
- destination staging;
- hash pós-cópia;
- evidência do contrato quando aplicável.

Mesmo quando o donor prioritário é escolhido, variantes divergentes devem permanecer auditáveis.

## 8. Política de segurança

Continuar obrigatório:

- audit não escreve em client/server/source;
- aggregation escreve apenas em `app/pt_build`;
- target existente vence no superset genérico;
- case collision é fail-closed;
- path traversal é rejeitado;
- staging é re-hasheado;
- authoring/archives/unknown não são promovidos automaticamente ao runtime;
- server runtime state não entra no overlay;
- geração e publish são fases separadas do audit/agregação.

## 9. O que ainda falta para o objetivo final

### P0 — fechar runtime Assassin/Shaman

1. Migration Planner de job slots/`MAX_JOBNUM`.
2. Migration Planner de `SkillDataCode[]` e índices `SkillCodeList`.
3. Traçar/portar handlers client/server que faltam.
4. Confirmar criação, login, save/relog, packet handling e restrictions.
5. Executar smoke runtime real das duas classes.

Ver `BUGS_ASSASSIN_SHAMAN_2026-09-06.md`.

### P1 — Item Contract Provider completo

Fechar a cadeia:

```text
OpenItem CODE
 -> client/server item catalog
 -> DorpItem
 -> model
 -> textures
 -> inventory/shop icon
 -> restrictions/specs
 -> drops
 -> NPC shops
 -> quests/events
```

Não assumir igualdade entre `OpenItem/<CODE>` e nome visual sem evidência do catálogo.

### P1 — Field/Map Contract Provider completo

Fechar:

```text
authoring ASE/MAX
 -> client SMD
 -> textures/minimap/title
 -> server SPP/SPM/SPC
 -> NPC/monster/spawn references
```

`SPP/SPM/SPC` devem ter `required` determinado por conteúdo/runtime, não por simetria de filenames.

### P1 — Skills/effects/audio closure mais profunda

- ligar todos os calls/handlers/delegates de skills;
- resolver `.part` transitivamente;
- ligar sound IDs a WAVs;
- capturar animation events quando existirem;
- diferenciar class audio de skill-specific audio.

### P2 — Generator contracts

Adicionar estado `GENERATABLE` somente quando existir writer certificado e inputs suficientes.

Cada gerador deve declarar:

- inputs obrigatórios;
- outputs;
- invariantes;
- validação pós-write;
- source/runtime evidence;
- versão do generator.

### P2 — Publish/rollback formal

O agregador atual é staging-only. Uma futura fase de aplicação deve ser separada:

```text
PLAN
 -> STAGE
 -> VERIFY
 -> DIFF
 -> APPLY TRANSACTION
 -> POST-VERIFY
 -> ROLLBACK MANIFEST
```

Nunca reaproveitar diretamente o materializer de staging como writer de produção.

### P2 — Master catalog persistente

Migrar progressivamente para catálogo persistente por conteúdo/entidade, idealmente SQLite, com:

- sources;
- files/hashes;
- canonical paths;
- entities;
- contract edges;
- evidence;
- generated artifacts;
- build membership;
- conflicts;
- validation history.

### P3 — UX

- dashboard por entidade;
- completeness matrix;
- filtros `recoverable/generatable/conflict/unknown`;
- diff de variantes;
- botão “build staging” por entidade;
- visualização da proveniência e das razões do planner.

## 10. Definition of Done do agregador

O agregador pode ser considerado “fechado” quando:

1. client + server inventory têm namespace normalizado e filtros certificados;
2. todas as ações de cópia têm proveniência e hash;
3. variants nunca são perdidas;
4. core vs optional é explícito;
5. ITEM/FIELD/MONSTER/NPC/PLAYER_CLASS/SKILL têm providers;
6. re-audit do staging é automático;
7. qualquer missing é classificado em `recoverable`, `generatable`, `optional`, `unknown` ou `conflict`;
8. publicação é transacional e reversível;
9. smoke runtime valida pelo menos player creation/login/combat/map load/item load;
10. nenhuma decisão depende de “copiar porque o nome parece igual”.

## 11. Comandos principais atuais

```bash
cd app
python3 pt_asset.py audit source-contracts
python3 pt_asset.py audit player-class-contracts
python3 pt_asset.py aggregate player-classes
python3 pt_asset.py aggregate client-superset
python3 pt_asset.py aggregate server-superset
python3 pt_asset.py aggregate summit-superset
```

O run combinado recomendado para integração é `aggregate summit-superset`.

## 12. Regra de manutenção

Qualquer nova inferência deve entrar na aplicação como:

```text
provider/parser
 -> normalized evidence
 -> ContractGraph edge
 -> confidence/required semantics
 -> resolver
 -> planner
 -> validation
```

Evitar hardcodes isolados no agregador. O materializer não deve “aprender” regras de jogo; ele apenas executa planos produzidos pelos contracts.
