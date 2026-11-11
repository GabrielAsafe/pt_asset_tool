# Etervale V14 — Stage072: precisão UV binary32 e diagnóstico residual

## Contexto confirmado

Resultado V13 dos 58 ficheiros Stage072 do cliente Etervale:

- 52/57 mapas tentados com `PASS_BLENDER_TRANSPORT_AND_VIEW`;
- 4 falhas `02_stage072_transport_check.log` exclusivamente com deltas UV de `3.814697265625e-06` e `6.103515625e-05`;
- `Field/forever-fall/pilai.smd`: falha em preparar **um ficheiro já existente** (estado físico/decoder ainda não identificado no resumo);
- `Field/Boss/dark_boss.smd`: fonte com `hTexture=0` em faces que o parser associa a `hTexture` não nulo no material 0;
- 7 mapas com referências ausentes ou serializadas incorretamente, incluindo 21 do mapa de abertura; `tem_wall04.bmp` de Ricarten continua ausente.

## Correção precisa — UVs

O importador Stage072 escreve a coordenada `V_blender = 1.0 - V_smd`. `V_smd` foi serializada como `IEEE-754 binary32`, mas a subtração em Python usa `binary64` e o campo UV Blender persistido é `binary32`.

Em coordenadas tiling grandes e negativas, essa passagem pode mudar o valor em **um ULP**, gerando um falso erro de transporte quando o checker usa um limiar absoluto `2e-6` contra o intermédio binary64.

V14 compara o valor de origem **arredondado ao binary32 final exato** com os dados efetivamente persistidos pelo Blender. Não usa uma nova tolerância. Na verificação UV, qualquer diferença representável em binary32 continua a resultar em `FAIL`. Mantém ainda o erro máximo entre a leitura e o valor intermédio Python como métrica **diagnóstica**, não como critério de aprovação. Preserva os validadores de posições, faces, materiais, cores, luzes e pointers.

Ficheiros envolvidos: `app/pt_asset_tool/stage072_uv_float32.py`, `app/pt_asset_tool/blender/check_stage072_transport.py`.

## `pilai` — diagnóstico sem inventar textura

A rotina de preparação de texturas já distingue `MISSING` / `INVALID_SERIALIZED_REFERENCE` de falhas reais de descodificação de ficheiros presentes. A V14 mantém `hard_preparation_failures` **bloqueante**, mas passa a incluir no erro `logical`, `physical`, `status`, `error`, `log` e `returncode` quando disponíveis. Os relatórios `texture_overlay_report.json` continuam a guardar as entradas completas.

**Não** converter `TGA_DECODE_FAIL` ou `BMP_PROTECTED_DECODE_FAIL` em `MISSING`: seria um falso positivo. Uma entrada como `field/forever-fall/` é uma referência serializada inválida; a existência de uma pasta física não é prova de imagem.

## `dark_boss` — não flexibilizar a leitura sem prova de runtime

Um `hTexture` nulo com material contendo texturas não prova, por si só, que a face é inerte. O parser estrito mantém o erro `STAGE072_PARSER_INCOMPLETE` até analisar material, TextureCounter, estado de renderização e semântica C# para essas faces. V14 não altera `stage072_corpus.py`, não substitui os handles nem descarta faces.

## Diagnóstico read-only imediato

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_stage072_v14_residual_triage.py --project-root "$PWD" \
  --output /tmp/etervale_v14_residual.json
```

Lê os relatórios em `pt_build` para `pilai` e o SMD original de `dark_boss` **sem escrever na source nem alterar os checkpoints**.

## Retomar somente os mapas pendentes

Quando não houver outro Blender em execução:

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

A V13 utiliza checkpoint por assinatura; os 52 mapas com `PASS_BLENDER_TRANSPORT_AND_VIEW` anteriores são reaproveitados e os 5 com `FAIL_BLENDER_WORKER` são reexecutados. `dark_boss` continua marcado como parse FAIL, sem execução Blender até que o seu formato seja estudado.

## Provas e limites

- Testes Python de arredondamento `binary32`, rejeição de alteração de um ULP, valores não finitos, script Blender, preservação do parser/importador e triage de relatórios.
- Regressões V12/V13: sem alterações à geometria, às UVs do ficheiro SMD ou à convenção dos eixos.
- Ambiente da cópia de desenvolvimento: Blender executável indisponível; a execução final com o Etervale instalado deverá ser confirmada no computador do utilizador.
- Resultados com referências ausentes e Textures Paint não ficam automaticamente certificados por uma aprovação de transporte UV.

Nenhuma modificação aos assets originais, schema, readers C# ou jogos Etervale está incluída neste patch.
