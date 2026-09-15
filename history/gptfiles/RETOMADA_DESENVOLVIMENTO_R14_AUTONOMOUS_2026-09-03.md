# PT Asset Tool — continuação autónoma R14 (gate externo 2026-09-03)

## Estado desta continuação

Este snapshot continua o handoff `RETOMADA_DESENVOLVIMENTO_R14.md` e preserva os invariantes fail-closed: client read-only, candidates apenas em `pt_build`, nenhuma autorização de produção e `deploy apply` não habilitado.

A tabela antiga do utilizador foi tratada apenas como referência histórica. Em particular, R14 já tinha ROT object-local com rebuild cumulativo de `TmPrevRot` e Stage 0.72 multi-vértice XYZ.

## Endurecimentos realizados

1. **Materiais Model0.62 por família física**
   - a seleção de witnesses passa a cobrir cada família Model0.62 presente no domínio, em vez de permitir dois representatives da mesma família;
   - uma célula MATERIALS só fica verde quando cada família física presente recebeu writer witness executado.

2. **Stage 0.72 corpus-wide**
   - o gate 1.0 exige explicitamente os 63 Stage canónicos em parser físico, StageArea, normais, texturas e materiais;
   - 62/63 ou qualquer subaudit parcial permanece fail-closed mesmo que o subset reporte PASS.

3. **INX/SMB semantic edit corpus**
   - `release-1-auto` usa `motion_pair_limit=0` por defeito;
   - truncar o corpus por `pair_limit` não pode produzir PASS de Release 1.0;
   - o resultado semântico é atribuído por domínio e condiciona o PASS INX/SMB de cada domínio.

4. **Mixed-Physique físico**
   - novo `pt_asset_tool/mixed_real_devtest.py`;
   - todos os Mixed reais presentes são testados, sem sampling;
   - skeleton/model-info é escolhido apenas por contexto determinístico e sempre confirmado por structural gate;
   - o Blender aplica edição automática a targets rigid e static do mesmo container;
   - o candidate é reconstruído sequencialmente pelos adapters rigid/static existentes;
   - verifica modos Physique, bytes não-target, bones, edição observada em todos os targets e reimport;
   - simples presença de uma amostra Mixed já não remove o blocker: ela precisa passar o gate físico.

5. **Sem falso PASS final**
   - `automatic_gate_status=PASS` significa apenas que a automação ficou verde;
   - o estado global fica `BLOCKED_EXTERNAL` enquanto faltarem runtime/game integrado e promoção controlada dos writers/publish-restore;
   - se não existir Mixed real, o primeiro gate externo continua sendo especificamente uma amostra Mixed-Physique autêntica com skeleton/config context quando disponível.

6. **Coverage Mixed por domínio**
   - domínios sem Mixed agora mostram `NOT_PRESENT_IN_CANONICAL_CORPUS`;
   - domínios com Mixed só recebem `PHYSICAL_AUTOMATED_EDIT_BUILD_REIMPORT_PASS` após certificação física;
   - a matriz agora explicita também os gates globais `RUNTIME_GAME_ACCEPTANCE` e `PUBLISH_RESTORE`.

## Validação reproduzida neste ambiente

- SHA-256 do ZIP recebido verificado: `87735cf58b824914f62e0f99630b7a63b6ee6b9c3abd97c5a48915bc26871570`.
- `python3 -m compileall -q .`: PASS.
- suíte diretamente afetada por release/coverage/Mixed: **47 PASS**.
- todos os dev tests sem referência à fixture física, executados em lotes reproduzíveis:
  - **82 PASS**;
  - **58 PASS**;
  - **29 PASS**.
- nenhum FAIL nesses três lotes.
- writers raros certificados mantêm exatamente os quatro SHA-256 do handoff R14.

Os 19 ficheiros de teste que dependem textualmente de `fixture_client` não podem ser executados de forma válida aqui porque o handoff não contém essa fixture. Também não existe client físico `.smd/.smb/.inx` montado neste ambiente; não transformar essa ausência em PASS.

## Coverage offline atual

Gerado em `app/pt_build/devtest/release_1_coverage_autonomous_2026-09-03.json`.

Estado: `PARTIAL`. O documento agora inclui blockers globais explícitos para:

- amostra/certificação física Mixed-Physique enquanto o corpus não possui Mixed real;
- runtime/game integrado;
- promoção dos writers e publish/restore.

Os blockers offline continuam a incluir gates que só podem ser pintados pela execução no client real; não equivalem a features de código ausentes.

## Próximo gate externo — uma única execução

No ambiente que possui o client real e Blender configurado, executar a partir de `app/`:

```bash
python3 pt_asset.py --client-root "/caminho/para/Cliente" validate release-1-auto
```

Não executar microtestes manuais por objeto/vértice/LOD. O runner deve fazer os gates automáticos completos e reportar o próximo bloqueio real.

### Interpretação esperada

- `status=FAIL`: existe um gate automático/physical real a corrigir; usar o relatório em `pt_build/devtest/release_1_auto/result.json`.
- `status=BLOCKED_EXTERNAL`, `external_input_required=true`: os automáticos passaram e falta a amostra Mixed-Physique real/autoritativa.
- `status=BLOCKED_EXTERNAL`, `manual_review_required_now=true`: Mixed físico e automáticos passaram; o próximo gate é somente runtime/game integrado, seguido da promoção controlada/publish-restore.

Nunca considerar este snapshot como produção 1.0 antes desses gates externos.
