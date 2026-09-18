# PT Asset Tool R14 1.0.0 — Modelo de Segurança e Autoridade

## Estado da distribuição

- automatic gate: `PASS`;
- automatic blockers: `0`;
- package: safety-locked;
- `production_authorized=false`;
- `client_write_authorized=false`;
- `server_write_authorized=false`;
- `WRITER_PROMOTION_AND_PUBLISH_RESTORE`: gate operacional externo.

## Zonas de escrita

### Permitida pela operação normal

- `app/pt_build/**`;
- configuração local da ferramenta;
- journal de certificação da própria ferramenta quando a ação explicitamente o requer.

### Não permitida automaticamente

- client Summit;
- server Summit;
- source C/C++;
- donor roots.

## Fail-closed

Quando a ferramenta não consegue provar identidade, layout, binding, lineage, hash, context ou writer applicability, deve emitir REVIEW/BLOCKED/UNRESOLVED e não escolher “a opção mais provável”.

## Recovery

Recovery geral exige CLOSED reachability bundle e expected roots. Um arquivo parecido, mesmo casefold-exact em donor, é evidência diagnóstica até satisfazer a política de recovery. Basename-only nunca é suficiente.

## Writers

Um writer pode estar certificado para determinado formato/asset/canal sem que isso autorize publish. Há duas autorizações diferentes:

1. **writer authorization** — o algoritmo pode produzir um artefacto no escopo provado;
2. **publish authorization** — o artefacto pode substituir bytes no target.

A versão 1.0 inclui a primeira para escopos certificados e mantém a segunda bloqueada.

## Deploy

`deploy plan/prepare/verify/simulate/state/restore-plan` continua como contrato legacy read-only no client. Escrita real só existe no fluxo estreito `deploy workspace-*`, originado de workspace `generic_import` verificado, com confirmação literal, backup SHA-256 do bundle completo, drift gate, staged artifacts sob `pt_build`, replace atómico, post-write verification e rollback integral em falha.

## Server

O server é read-only. Field Metadata Editor gera drafts em `pt_build`, nunca edita SPM/SPP/SPC no server root.

## UI safety arm

`ARM BUILD WRITES` habilita somente workspace/build. Client write requer separadamente `ARM CLIENT DEPLOY`, consumido após uma única tarefa de publicar/restaurar bundle. O server continua sem write. O backend aplica os guards mesmo quando a UI está armada.

## Auditoria

Antes de distribuir uma árvore modificada:

```bash
./VERIFY_PACKAGE.sh
cd app
python3 -m pytest -q dev_tests/test_registry_bootstrap_fresh.py
./RUN_REGRESSION_FOCUSED.sh
```
