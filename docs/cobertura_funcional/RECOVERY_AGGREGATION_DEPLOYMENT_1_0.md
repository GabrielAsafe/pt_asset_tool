# PT Asset Tool R14 1.0.0 — Aggregation, Recovery, Build e Deploy

## `aggregate`

Os agregadores constroem overlays auditáveis sob `pt_build`; nunca fazem `cp -r` no target.

- `aggregate player-classes`: contratos de classes e variantes/gaps/conflitos;
- `aggregate client-superset`: superset de client donors;
- `aggregate server-superset`: superset server com lifecycle filtering;
- `aggregate summit-superset`: composição recomendada client+server+classes.

Outputs incluem manifests, validation, provenance, recover/variants/gaps/conflicts e overlays separados.

## `recover general-closed-bundles`

Recovery geral é scope-locked. O plano precisa provar bundle CLOSED e roots esperados; donor lineage/hashes são registrados. O comando não deve transformar gaps diagnósticos em cópias automáticas por nome parecido.

## `recover class-ui-alias-only`

Recovery/canonicalização específica da política de UI de classe, com Mechanician como root canónico. É uma superfície separada e estreita; não autoriza recovery geral.

## `build`

- `--plan`: mostra dispatch e razão de autorização/bloqueio;
- `--candidate`: permite rotas de pesquisa explicitamente `pt_build`-only;
- sem writer certificado aplicável, o resultado é fail-closed.

O sidecar de provenance liga source SHA, artefact SHA, adapter e modo candidate/production.

## `deploy`

### plan

Planeja origem/artefact/provenance e verifica se há base para transação. Não escreve client.

### prepare

Cria backup verificado e staged transaction sob `pt_build`. Não substitui target.

### verify

Revalida drift do client e hashes do backup/staged artefact.

### simulate

Executa replace/postwrite/rollback **dentro de pt_build**. `--inject-failure postwrite` testa rollback.

### state

Classifica bytes atuais como original, managed artifact conhecido ou unknown drift.

### restore-plan

Só planeja restore quando o estado é conhecido/gerenciado. Apply permanece bloqueado.

## Publish/restore real

A release 1.0 termina antes deste ponto. `WRITER_PROMOTION_AND_PUBLISH_RESTORE` é um gate operacional externo e deve exigir autorização explícita/revisão humana fora do pacote padrão.
