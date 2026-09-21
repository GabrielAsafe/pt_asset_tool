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
