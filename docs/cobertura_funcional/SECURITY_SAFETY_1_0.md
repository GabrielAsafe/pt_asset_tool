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

`deploy plan/prepare/verify/simulate/state/restore-plan` trabalha com provenance, backup/staged transaction e simulação sob `pt_build`. Não existe apply geral do client exposto pelo caminho certificado da distribuição 1.0.

## Server

O server é read-only. Field Metadata Editor gera drafts em `pt_build`, nunca edita SPM/SPP/SPC no server root.

## UI safety arm

Armar a GUI habilita ações de workspace/build, não client/server writes. O backend continua aplicando todos os guards.

## Auditoria

Antes de distribuir uma árvore modificada:

```bash
./VERIFY_PACKAGE.sh
cd app
python3 -m pytest -q dev_tests/test_registry_bootstrap_fresh.py
./RUN_REGRESSION_FOCUSED.sh
```
