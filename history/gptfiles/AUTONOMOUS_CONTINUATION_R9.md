# Continuação autónoma — R9 — 2026-09-02

Este documento sucede `AUTONOMOUS_CONTINUATION_R8.md`. O ponto multi-INX/`selected_context` fechado em R8 foi exercitado com o audit real fornecido e usado para avançar Profiles/LOD sem promover writers.

## Evidência real recebida e congelada

Audit: `evidence/rigid_model_info_contexts_real_2026-09-02.json`

SHA-256: `598769d132e0f46f69166f55c3da16b3b27c236a4de7bad21a79eb0dde41c6a9`

Resultados declarados pelo audit:

```text
rigid assets                 1952
single config                1762
multi config                  106
multi semanticamente igual     51
multi ambíguo                   55
sem model-info utilizável       84
```

As 106 rows multi-INX foram reclassificadas pela implementação R9 e houve **106/106 concordância** com o estado do audit. A decomposição adicional mostra:

```text
AMBIGUOUS_MODEL_INFO_CONFIG = 55
  LOD_GROUPS diverge         = 55
  SKELETON diverge           = 0
```

Portanto, neste corpus real, a ambiguidade multi-INX observada é de composição/LOD, não de troca de armature. Isso não permite escolher automaticamente uma variante: os 55 casos continuam a exigir `--model-info` explícito.

## Implementado em R9

1. `pt_asset_tool/rigid_model_info.py`
   - centraliza normalização e assinatura semântica de config rigid;
   - classifica `SINGLE_CONFIG`, `SEMANTICALLY_EQUIVALENT`, `AMBIGUOUS_MODEL_INFO_CONFIG` e `NO_USABLE_MODEL_INFO`;
   - separa dimensões de ambiguidade `SKELETON` / `LOD_GROUPS`;
   - gera `semantic_context_id` independente do nome do INX;
   - mantém audit read-only e sem autorização de client write.

2. Profile candidate discovery mais rigoroso
   - cada candidate recebe estado multi-INX, dimensões de ambiguidade, `semantic_context_id` e lista de INX semanticamente equivalentes;
   - associação a profile canónico continua presa ao asset exato;
   - basename de INX só pode resolver identidade se for único entre os INX associados ao asset exato;
   - discovery continua sem autorizar authoring/writer.

3. Profile-driven exact import context
   - novo módulo `pt_asset_tool/profile_authoring.py`;
   - novo comando:

```bash
python3 pt_asset.py profiles authoring-plan <profile_id> --lod auto|high|default|low
```

   - exige profile verification + target SMD exato + INX resolvido + skeleton + LOD groups + uma única configuração registry compatível;
   - `writer_authorized=false`, `production_authorized=false`, `client_write_authorized=false` permanecem explícitos.

4. Generic import por profile

```bash
python3 pt_asset.py import <asset> --profile <profile_id> --lod default --no-open
```

   - `--profile` e `--model-info` são mutuamente exclusivos;
   - o profile só escolhe contexto de import Blender;
   - `selected_context.selection_basis` persiste `profile_id`, `profile_version` e target exato;
   - build candidate continua a confiar nos hashes/INX/skeleton/LOD físicos do `selected_context`, não no nome do profile como autoridade.

5. Reuse de workspace rigid ficou context-bound
   - workspace rigid existente precisa de manifest/contexto verificável;
   - pedir outro `--model-info`, outro LOD explícito ou outro profile não reutiliza silenciosamente o `.blend`;
   - nesses casos o comando falha fechado e exige `--reset`.

6. `development-readiness`
   - passa a calcular no registry atual as contagens single/multi/equivalent/ambiguous/no-usable;
   - expõe dimensões de ambiguidade;
   - Profiles/LOD agora registra `profile_driven_import_context_wired=true` sem promover generic build.

## Política mantida

- Nenhum `deploy apply` foi criado.
- Nenhum client write foi habilitado.
- Nenhum writer candidate foi promovido.
- Mixed-Physique continua fail-closed.
- O audit real é evidência de seleção de contexto, não certificação Blender/runtime.
- Os quatro writers certificados não foram modificados.

## Validação R9

```text
54 PASS / 0 FAIL   dev tests reproduzíveis sem fixture_client
175 PASS / 1 SKIP  suíte histórica/maintained
106 / 106          rows do audit real reclassificadas sem divergência
compileall          PASS
node --check        PASS
bash -n             PASS
CLI parser/version  PASS (0.12.0)
```

A suíte histórica usa apenas durante o teste um symlink `payload -> .`, removido imediatamente depois. O `fixture_client` continua ausente do snapshot, portanto testes que exigem essa fixture externa permanecem não reproduzíveis neste pacote.

## Próximo ponto técnico

O caminho mais seguro agora é usar o contexto real já classificado para **planejar execução Blender/runtime**, não ampliar parsing:

1. executar `profiles authoring-plan` e `import --profile` nos profiles canónicos no client real;
2. para os 55 assets multi-INX ambíguos, selecionar representatives por variante de LOD e usar `--model-info` explícito;
3. executar candidate rigid/static/Stage no Blender real com captura de report/provenance;
4. executar a fila `animation-certification-plan` em player/NPC/monster;
5. somente depois considerar profile-driven candidate build além do import;
6. manter production promotion e deploy apply bloqueados até runtime evidence por família.
