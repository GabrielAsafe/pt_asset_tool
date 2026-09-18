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

## `deploy` legacy single-file

`plan/prepare/verify/simulate/state/restore-plan` continua sendo o contrato conservador antigo. Ele prepara provenance, backup e simulação em `pt_build`, mas não possui apply real.

## Workspace bundle publish/restore real

A escrita real no client é deliberadamente mais estreita e nasce de um **workspace Blender `generic_import` verificado**:

- `deploy workspace-prepare ASSET` detecta modelo/texturas alterados, inclui INX/SMB como contexto preserve-only e cria backup verificado do bundle inteiro;
- `deploy workspace-publish ASSET --confirm "APPLY CLIENT BUNDLE"` prepara e publica somente entradas `MODIFIED`;
- `--textures-only` pula o writer do modelo e publica apenas texturas realmente alteradas;
- BMP/TGA protegidos são reconstruídos no container runtime original antes do deploy;
- apply exige ausência de drift em todos os ficheiros rastreados;
- cada substituição é atómica e validada por SHA-256;
- falha de escrita ou de validação pós-write restaura automaticamente tudo que já foi escrito;
- `deploy workspace-history ASSET` lista manifests retidos;
- `deploy workspace-restore-latest ASSET --confirm "RESTORE CLIENT BUNDLE"` restaura o último deploy conhecido, recusando drift desconhecido.

A publicação do modelo só entra no bundle quando o writer saved-Blender static/rigid consegue construir um candidate e o verificador existente dá PASS com edição observada. INX/SMB participam do backup e do drift gate, mas são **preserve-only** neste workflow. Outros formatos/famílias continuam fail-closed.

Na GUI, **Publicar no jogo** e **Restaurar último deploy** exigem a autorização one-shot separada `ARM CLIENT DEPLOY`. `ARM BUILD WRITES` por si só não permite client write. O server continua read-only.
