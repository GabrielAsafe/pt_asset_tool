# Patch notes v8 — Fix 136 evidence-aware resolver

## Motivo

A execução real v7 auditou 543 assets, encontrou 184 ausentes no target mas recuperáveis nas donors e conseguiu stagear 130. Os 54 restantes eram bloqueios conservadores, não 54 assets sem source.

## Correções

1. **Linhagem do target**
   - mede quais donors reproduzem os SHA-256 dos assets já presentes;
   - só aceita um baseline quando há volume e dominância fortes;
   - usa o baseline apenas para desempatar candidatos de qualidade estrutural compatível.

2. **Mechanician / Mecha**
   - `shared/skill.h`/inventário continua canónico em `Mechanician`;
   - donors físicos podem guardar buttons em `Mecha`;
   - a pesquisa trata isso como alias de path estreito (`ALIAS_EXACT`/`ALIAS_SUFFIX`), não como basename genérico.

3. **PART bundle coherence**
   - refs são resolvidas primeiro relativamente ao `.part` físico;
   - se a ref for solta, o candidato do mesmo donor do pai recebe preferência;
   - colisões de basename privilegiam `Effect/Particle` e proximidade ao pai;
   - o destino é o runtime path físico do donor (com wrappers configurados removidos), evitando destinos errados como `Effect/Particle/Script/flare.tga`.

4. **TGAs basename-only**
   - destino pode ser inferido por peers já existentes da mesma classe/categoria;
   - isto resolve o caso observado `As2_VENOM.tga` para `image/Sinimage/skill/keep/As2_VENOM.tga`.

5. **Ficheiros existentes nunca são substituídos pelo staging**
   - `PRESENT_TARGET_CONFLICT` vira decisão `KEEP_TARGET`;
   - os conflitos continuam visíveis no relatório, mas não contaminam o patch missing-only.

6. **Near-match para verdadeiros missing**
   - novo `fix136_near_matches.csv` sugere filenames semelhantes nas três sources;
   - fuzzy matches nunca recebem `STAGE_SAFE` automaticamente.

## Novos campos de decisão

`fix136_asset_matrix.csv`:

- `runtime_dest`
- `resolution`
- `action` (`KEEP_TARGET`, `STAGE_SAFE`, `REVIEW`, `MISSING`)
- `action_reason`

O `summary.json` separa `informational_review` de `actionable_review` e registra a evidência de `baseline_source`.

## Testes

A suíte cobre:

- suffix matching em root-base;
- normalização de barras EU;
- closure `.part` e staging;
- alias Mechanician/Mecha;
- resolução por target lineage;
- seleção de loose PART resource no subtree `Effect/Particle` com remoção do wrapper `Game/`.
