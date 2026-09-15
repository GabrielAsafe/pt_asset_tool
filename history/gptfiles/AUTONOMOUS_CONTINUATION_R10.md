# Continuação autónoma — R10 — 2026-09-02

Esta continuação usa os testes manuais executados no snapshot R9 no client real e no Blender real. Nenhum resultado desta etapa promove writer, produção ou deploy no client.

## Evidência manual recebida

Os logs foram congelados em:

- `evidence/manual_r9_test_2026-09-02_part1.txt`
- `evidence/manual_r9_test_2026-09-02_part2.txt`

Resultados confirmados:

1. `status`/`smoke` inicialmente não encontravam o client pelo app-level discovery, enquanto `doctor` encontrava o caminho histórico real. Isso revelou uma inconsistência entre `app_config.resolve_client_root()` e `Settings.discover()`.
2. `import char/npc/Bcn02/Bcn02.smd --no-open` falhou corretamente com `AMBIGUOUS_MODEL_INFO_CONFIG`.
3. Seleção explícita de `Bcn02.inx` + `lod=default` importou com `selected_context` verificado e hashes físicos de INX/SMB.
4. Reutilização do workspace com `Bcn02f.inx` sem `--reset` falhou corretamente com `EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH`.
5. O `--reset` com `Bcn02f.inx` revelou uma falha real: o INX pede nós de LOD (`hart`, `T-npc-12-H02`) ausentes do SMD associado. O erro só aparecia tarde, dentro do Blender, depois de o workspace já ter sido removido.
6. `profiles authoring-plan priestess_c01_m5 --lod default` retornou `READY`, exact registry context match e client/write false.
7. `import ... --profile priestess_c01_m5 --lod default` criou workspace/provenance válidos e abriu no Blender. O utilizador relatou visualmente que “estava tudo correto”. Esta observação é preliminar e não é promovida a certificação runtime/visual formal.
8. `build --plan` permaneceu fail-closed para produção, embora o authoring plan exponha objetos elegíveis ao candidate writer.

## Nova análise do audit real multi-INX

As 106 rows / 258 choices do audit real R9 foram cruzadas com os NodeName do SMD canónico. Resultado congelado em:

`evidence/rigid_model_info_real_lod_coverage_r10.summary.json`

```text
rows verificadas                     106
choices INX verificadas              258
assets com nó LOD ausente              2
choices com nó LOD ausente             2
```

Casos afetados:

- `char/npc/Bcn02/Bcn02.smd` + `Bcn02f.inx`
  - HIGH: faltam `hart`, `T-npc-12-H02`
  - DEFAULT: falta `hart`
- `char/tmABCD/tmbC03.smd` + `C004.inx`
  - HIGH: falta `TshC03`
  - DEFAULT: falta `TsmC03`
  - LOW: falta `TslC03`

A política continua conservadora: isso não afirma que o jogo rejeita esses INX; afirma apenas que o generic Blender importer atual não consegue materializar fielmente um nó que não existe no SMD associado.

## Implementado em R10

### 1. Preflight de cobertura INX LOD → SMD NodeName

`pt_asset_tool/rigid_model_info.py` agora expõe cobertura por LOD usando NodeName serializado, preservando semântica case-insensitive e chunks duplicados.

Cada cobertura informa:

- nós pedidos pelo INX;
- nós ausentes do SMD;
- quantidade de chunks SMD efetivamente selecionáveis;
- estado `PASS` / `FAIL` / `UNKNOWN`.

O audit `rigid-model-info-contexts` passa a incluir `lod_node_coverage` por choice e contagens de contexts incompatíveis com o generic importer.

### 2. Generic import falha antes do Blender

Antes de iniciar Blender, rigid import agora recusa contextos com:

`MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES`

Isso substitui a falha tardia observada no teste manual de `Bcn02f.inx` por um erro host-side explícito e auditável.

### 3. `--reset` não destrói workspace antes do preflight

Para rigid assets, um reset agora resolve e valida o novo INX/LOD **antes** de apagar o workspace existente.

Se o contexto pedido for incompatível, o `.blend` anterior permanece intacto. Isso fecha uma lacuna de preservação de edição artística descoberta diretamente no teste manual R9.

### 4. Profile authoring também expõe cobertura

`profiles authoring-plan` inclui `lod_node_coverage`. Um profile cujo contexto exato peça nós ausentes do SMD fica bloqueado com `PROFILE_LOD_REFERENCES_MISSING_SMD_NODES`.

### 5. UI/choice metadata enriquecido

As opções rigid model-info usadas pela UI passam a carregar cobertura por LOD para permitir apresentação explícita de contextos importáveis vs fail-closed.

### 6. Descoberta de client consistente entre status/smoke e doctor

`app_config` agora inclui os mesmos layouts históricos de home/Desktop já suportados pelo fallback de `Settings.discover()`.

No ambiente real reportado, isso cobre:

`~/Área de Trabalho/summit/Summit Tale Client Full/cliente`

Também foi incluído `~/Desktop/summit/...` para a variante não localizada.

## Validação R10

```text
58 PASS / 0 FAIL   dev tests reproduzíveis sem fixture_client
175 PASS / 1 SKIP  suíte histórica/maintained
106 rows / 258 choices do audit real cruzadas com SMD NodeName
2 choices incompatíveis detectadas e documentadas
compileall          PASS
node --check        PASS
bash -n             PASS
certified hashes    unchanged
```

Os quatro writers certificados continuam byte-for-byte nos hashes congelados. O symlink test-only `payload -> .` usado pela suíte histórica foi removido ao final.

`CURRENT_READINESS.json` não foi regenerado neste ambiente porque o client real não está montado aqui. A matriz R9 continua válida quanto a maturidade/blockers; R10 não promove nenhuma área nem remove blockers, e a evidência nova fica separada em `evidence/`.

## Estado de confiança após R10

- Multi-INX ambiguity guard: evidência real PASS.
- Selected-context physical identity: evidência real PASS em `Bcn02.inx` e profile Priestess.
- Workspace context mismatch guard: evidência real PASS.
- Missing-LOD-node preflight: implementado a partir de uma falha Blender real; precisa de rerun manual R10 para confirmar a nova mensagem host-side e preservação do workspace.
- Priestess profile import: observação visual preliminar positiva; ainda não é Blender visual certification formal.
- Rigid saved-Blender candidate: continua candidate-only; ainda precisa de uma edição controlada + `build --candidate --object ...` no Blender real.
- Runtime/game acceptance: pendente.
- Production/deploy apply: bloqueado.

## Próximo teste manual recomendado

1. Repetir `Bcn02f.inx --reset`: agora deve falhar **antes do Blender** com `MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES` e preservar o workspace anterior.
2. Executar `status` e `smoke` novamente: `status` deve resolver o mesmo client que `doctor` encontra; `smoke` deve deixar de falhar apenas por `client_root_resolved=false`.
3. No workspace Priestess já validado visualmente, escolher um único objeto elegível, fazer uma alteração geométrica mínima e controlada no Blender, salvar e executar `build --candidate --object <nome>`.
4. Validar o output candidate/provenance; não executar deploy/apply.
