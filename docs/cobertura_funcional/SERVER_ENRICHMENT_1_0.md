# PT Asset Tool R14 1.0.0 — Manual Server / Asset Enrichment

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Atualização:** 2026-09-21 — Management Legacy + World Closure + Legacy Authoring.

## Princípio

O server continua read-only por padrão. A descoberta/census não escreve nada. Escrita só existe dentro de pipelines de authoring tipadas, armadas e transacionais.

## Gates

```bash
python3 pt_asset.py --client-root CLIENT --server-root SERVER validate server-environment-auto
python3 pt_asset.py --client-root CLIENT --server-root SERVER validate server-design-auto
```

## Censos

- `audit server-inventory`: árvore e lifecycle;
- `audit server-bundles`: Monster/NPC definitions e model/INX resolution;
- `audit server-fields`: SPM/SPP/SPC companions;
- `audit server-items`: OpenItem/code identity, agora enriquecido com contratos runtime/legacy quando disponíveis.

## Management Legacy

Com Management integration instalada:

```bash
python3 pt_asset.py legacy-management summary
python3 pt_asset.py legacy-management item-code WA121
python3 pt_asset.py audit legacy-management
```

A auditoria correlaciona census/server com runtime/client sem executar EXEs.

## World Closure

A GUI apresenta:

```text
SPM → Monster/NPC → item/OpenItem → sITEM → DorpItem → icon/ASE
```

O objetivo é descobrir dependências e targets de authoring, não classificar toda ausência como bug.

## Legacy Authoring

Kinds:

```text
ITEM MONSTER NPC SPM SPP SPC
```

Fluxo:

```text
Inspect → Edit/Create → Stage → Publish → Verify → Restore
```

`Stage` escreve somente `pt_build`. `Publish` usa Asset Bundle transaction com backup/hash/drift/atomic/post-verify.

### ITEM

OpenItem create/edit para codes runtime já conhecidos. Novo code `sITEM` continua bloqueado.

### MONSTER

Stats/EXP/drops/money/extra drops/dialogs/linked file.

### NPC

Fields/dialogs/shops/linked file.

### SPM

Actors, bosses, hours, MAX_ACTOR_POS/MAX_ACTOR/DELAY.

### SPP

200×12 record editing.

### SPC

100×504 ADD/REPLACE/REMOVE fixed NPC records.

## Asset Enrichment

`audit enrichment-plan` e `audit enrichment-graph` continuam sendo análise de dependência. Legacy Authoring usa a mesma infraestrutura de compiler/deploy quando a edição é autorizada.

## Source contracts / T5

Permanecem read-only evidence gates. PRELOAD não é ACTIVATION e reference-only não é recovery authority.

## Lifecycle excluído

Persistência, logs, anti-cheat/segurança e estado runtime continuam fora do authoring de assets.

<!-- PT_SERVER_ENRICHMENT_OPERATIONAL_GUIDE_V2_2026-09-21 -->

## Runbook operacional da aba Servidor / Asset Enrichment

A ordem recomendada é orientada a tarefas:

```text
1. Raiz do servidor      → Salvar raiz → Validar ambiente
2. Source + donors       → Salvar fontes
3. Bundles server        → Analisar Asset Enrichment
4. Reachability global   → Censo geral (plan-only)
5. REVIEW/BLOCKED        → motivo → o que falta → onde verificar → ação explícita
6. Staging opcional      → Agregar Summit / Field drafts em pt_build
7. Runtime/release       → validação separada; nenhum PASS desta aba autoriza produção
```

### Preflight e freshness

A UI mostra client, server, source atual, source de referência e donors antes do censo. Zero donors é permitido, mas visível. Roots/donors passados manualmente no CLI não são configuração persistente da GUI; use **Salvar fontes** para persistir.

Um relatório só é `FRESH_CONFIG` quando client root, server root, source root, reference source root e os conjuntos de donor roots coincidem com a configuração atual. Alterar donors torna o relatório anterior `STALE_CONFIG`.

Jobs iniciados fora da GUI não têm acompanhamento de PID/progresso pela aplicação web; passam a aparecer quando `pt_build/general_asset_census/result.json` é finalizado.

### REVIEW explicado

As linhas do explorador expõem `review_required`, `review_summary`, `review_reasons[]` e `review_actions[]`. Motivos conhecidos explicam significado, falta e local de verificação. Ações navegam apenas para superfícies seguras e não publicam no servidor. `ZHOON_SHARED_DEFAULT_REVIEW`, em particular, não autoriza criar/copiar `Name/Name.zhoon` por entidade apenas para eliminar REVIEW.
