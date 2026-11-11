# Etervale V13 — Auditoria Stage0.72 de TODOS os mapas

## Escopo e decisão técnica

A V12 foi aprovada na máquina Etervale para `Field/Ricarten/village-2.smd`: orientação `GAME_Y_UP_LEFT_HANDED_TO_BLENDER_Z_UP_RIGHT_HANDED`, Paint com 262 imagens privadas e uma face indisponível (`field/ricarten/tem_wall04.bmp`). O V13 transforma essas evidências num processo **por todos os mapas** sem abrir uma janela Blender para cada ficheiro.

**Os Stage 0.72** são todos os ficheiros `.smd` sob `assets/` cujo cabeçalho físico é `SMD Stage data Ver 0.72`, independentemente do nome da pasta. Outros formatos de mapas (ASE, SPM/SPP/SPC ou SMD Model0.62) têm validadores próprios e não são falsamente incluídos aqui.

O V13 **não altera** os ficheiros do jogo, bases de dados nem os writers/UVs/face winding certificados. A auditoria guarda apenas JSON/CSV/logs e, se `--blender` for pedido, workspaces temporários sob `pt_build`.

## Comando 1: validação imediata de todos os Stage (sem Blender)

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_stage072_batch_audit.py
```

Percorre cada mapa, mostra `[1/N]`, `[2/N]`... e produz por mapa:

- Parse físico e área/texlinks Stage 0.72: contagem de vértices, faces, materiais, luzes e UV layers.
- Prova do perfil de eixos V12 (troca Y/Z, determinante −1), bounds e escala de pré-visualização **estática, sem abrir o Blender**.
- Referências às texturas de materiais usados e animados, com preferência pelo caminho com capitalização exata. Nomes ausentes, inválidos e colisões de maiúsculas/minúsculas **não são resolvidos arbitrariamente**.
- Candidatura ao Stage 0 Texture Paint. `tem_wall04.bmp` é marcada como **exceção documentada exclusivamente em Ricarten e no stage 0**, não como textura recuperada.
- Resultado `PASS_STATIC`, `PASS_STATIC_WITH_EXCEPTION`, `REVIEW_REQUIRED` ou `FAIL_PARSE_OR_SOURCE`; um erro não interrompe os mapas seguintes.

A leitura do código da view **não é equivalente a uma janela Blender aberta**. O relatório conserva `not_runtime_visual_certified: true` e `not_paint_ui_certified: true`.

## Comando 2: validar cada Stage no Blender em background

**Somente quando o outro lote SMD/Blender acabar**, executar:

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

Para cada mapa compatível com o parse, em série:

1. Executa a importação Stage072 existente no Blender, com overlay privado de texturas e validação de transporte (vértices, faces, UVs, cores, luzes).
2. Reabre o `.blend` gerado em background e executa a criação do **proxy visual V12**: swap Y/Z, escala/origem, mesh privado e proxies de luzes. Compara posições do proxy com a fórmula e confirma que a mesh fonte permanece intacta. Não grava o `.blend` após esta inspeção.
3. Assinala separadamente `PASS_BLENDER_TRANSPORT_AND_VIEW`, `FAIL_BLENDER_RUNTIME`, `BLOCKED_TEXTURE_COLLISION` ou `FAIL_BLENDER_TIMEOUT`.

Esta verificação é mais cara: o processo cria um `.blend` privado por mapa; o espaço em disco pode crescer substancialmente. O processamento é sequencial e o subprocesso é limitado a 360 segundos por mapa. Não inicia nem interfere com o processo SMD Preview já em execução.

**Não inclui Texture Paint GUI em lote**: abrir, duplicar e guardar as texturas privadas de todos os mapas criaria centenas ou milhares de pastas de edição e consumiria muito espaço. O estado `paint_policy` indica elegibilidade estática. O teste efetivo de pintura já passou para Ricarten; deve ser repetido por amostragem para outros perfis.

## Checkpoints e ficheiros gerados

Diretório padrão: `app/pt_build/etervale/stage072_all_maps/`.

- `stage_0_checkpoint.jsonl`: grava cada mapa imediatamente; permite continuar após interrupções. Se a origem não mudou, o resultado é reutilizado. Se acrescentares `--blender`, os mapas que só tinham validação estática são complementados com prova Blender.
- `stage_0_summary.json`: resultados completos e estado consolidado.
- `stage_0_maps.csv`: uma linha por mapa com `parse`, `view_policy`, `paint_policy`, `blender`, contagens e os estados de dependências.
- `blender_tasks/<hash>/worker.log` + `view_result.json` + `03_view_check.log`: diagnóstico individual do subprocesso.
- `preview_work/`: blend previews e relatórios de transporte existentes, em espaço separado.

`--fresh` refaz o scan e substitui o checkpoint; mantém workspaces `.blend` para inspeção manual. `--limit 3` verifica apenas os três primeiros mapas para ensaio. `--stage 1` faz auditoria de elegibilidade de pintura para a camada UV 1; o default é 0.

## Interpretação do status

| Status | Significado |
|---|---|
| `PASS_STATIC` | Stage reconhecido, sem dependências inesperadas; eixos e Paint analisados sem Blender |
| `PASS_STATIC_WITH_EXCEPTION` | Ausência Ricarten conhecida, **não** resolvida; as outras verificações estáticas passaram |
| `REVIEW_REQUIRED` | Dependências ausentes, referências inválidas ou colisões; mapa individual para triagem |
| `FAIL_PARSE_OR_SOURCE` | Erro no parsing/leitura do Stage |
| `PASS_BLENDER_TRANSPORT_AND_VIEW` | Blender confirmou transporte e proxy de visualização em background; **não** certidão de qualidade visual em jogo |
| `FAIL_BLENDER_RUNTIME` | Um dos passos Blender falhou; consultar log por mapa |
| `BLOCKED_TEXTURE_COLLISION` | Colisão de paths, sem resolução arbitrária |

O exit code 3 indica falhas/review presentes; **não significa que o auditor tenha parado**. Se forem 100 mapas, a listagem e os relatórios devem conter 100 linhas mesmo com alguns bloqueios.

## Limites de prova

- A verificação de eixos executa o próprio helper V12 no Blender em modo `--background`, mas não pode certificar a apresentação na viewport com o artista presente.
- `paint_policy` não prova imagens decodificáveis em Blender nem que um novo Texture Paint abre em modo correto. Em `--blender`, o importador detecta falhas de load de imagens efetivamente existentes; o modo Texture Paint continua a exigir teste visual por amostragem.
- Não faz roundtrip de geometria para todos os mapas, porque essa prova é mais dispendiosa e altera intencionalmente uma cópia do Stage. O teste Ricarten `stage072-geometry-roundtrip` permanece a prova atual da implementação do writer; outro lote pode ser planejado especificamente para essa certificação.
- Um mapa que tenha outras texturas realmente ausentes não é reclassificado como PASS. Não se inventam, renomeiam ou substituem texturas.
- O auditor ainda não pode apresentar o número real de mapas nem declarar PASS da coleção Etervale sem ser executado no computador onde todos os assets existem.
