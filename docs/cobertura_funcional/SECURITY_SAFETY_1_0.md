# PT Asset Tool R14 1.0.0 — Modelo de Segurança e Autoridade

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Atualização:** 2026-09-21 — publish capability-scoped de Legacy Authoring/Asset Bundle.

## Princípio

O padrão continua **read-only**. Escrita no target não é um flag global; é uma autorização estreita por pipeline, formato e transação.

## Zonas de escrita

### RO

- client/server census;
- Management Legacy evidence;
- World Closure;
- inspect;
- compare/audits.

### BUILD

- `app/pt_build/**`;
- overlays/manifests;
- workspaces;
- reports/evidence;
- configuração/journal local.

Na GUI, BUILD requer `ARM BUILD WRITES` quando a ação cria artefactos.

### DEPLOY

Só pipelines explicitamente promovidas podem substituir target bytes. Atualmente isso inclui os bundles/capabilities documentados, entre eles Legacy Authoring para ITEM/MONSTER/NPC/SPM/SPP/SPC no escopo provado.

## Fail-closed

Sem identidade, layout, binding, lineage, target único, hash ou writer applicability, a ferramenta retorna REVIEW/BLOCKED/AMBIGUOUS/UNRESOLVED e não escolhe “o mais provável”.

## Writer vs publish

São gates diferentes:

1. writer pode gerar um artefacto válido em `pt_build`;
2. publish pode aplicar aquele artefacto a um target específico.

A presença de writer não concede write genérico.

## Legacy Authoring

### Stage

- exige `server_root`;
- GUI exige `ARM BUILD WRITES`;
- escreve apenas em `pt_build`;
- EDIT pode usar `expected_sha256` para detectar drift desde Inspect.

### Publish

CLI exige:

```text
APPLY ASSET BUNDLE
```

GUI exige `ARM ASSET DEPLOY` e confirmação interativa.

A transação executa:

```text
target evidence/hash
→ drift gate
→ backup
→ atomic replace
→ post-write verification
→ APPLIED_VERIFIED
```

Falha de write/verify provoca rollback.

### Restore

CLI exige:

```text
RESTORE ASSET BUNDLE
```

Restore só usa o backup da transação e recusa drift externo desconhecido.

## Boundaries de conteúdo

Bloqueados:

- novo runtime `sITEM` code;
- userdata/warehouse binários;
- internals não provados do ItemEditor;
- SPP/SPC fora do layout canónico;
- path/definition ambíguo;
- write manual fora da transação como substituto do pipeline.

## Executáveis legacy

Nenhum EXE histórico é executado. Verificar Management significa hash/evidence, não launch.

## Persistência/logs/segurança

DataServer/userdata, warehouse, logs, anti-cheat e estado runtime não passam a ser assets só porque tooling histórico os acessava. Permanecem fora do authoring normal.

## UI arms

- `ARM BUILD WRITES`: pt_build/workspace/stage;
- `ARM ASSET DEPLOY`: Asset Bundle/Legacy Authoring publish/restore;
- `ARM CLIENT DEPLOY`: pipelines específicas de client workspace.

Os arms não desabilitam guards backend.
