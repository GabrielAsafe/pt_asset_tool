# Etervale V20 — revisão visual sequencial dos 58 mapas Stage 0.72

**Compatibilidade:** Asset Tool atualizado até V19, com auditoria V13 concluída (`PASS_BLENDER_TRANSPORT_AND_VIEW=58`).

## Instalar — patch aditivo, sem substituir ficheiros existentes

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -n "$HOME/Transferências/ETERVALE_V20_STAGE072_REVISAO_SEQUENCIAL_2026-11-10.zip" -d .
python3 -m pytest -q app/dev_tests/test_etervale_stage072_review_sequential_v20.py
```

O pacote acrescenta `app/pt_stage072_review_sequencial.py`, um teste de regressão e esta documentação. **Não modifica o parser, os assets, os writers ou o motor.** `unzip -n` não sobrescreve ficheiros existentes.

## Testar a lista sem abrir o Blender

```bash
python3 app/pt_stage072_review_sequencial.py --dry-run --limit 3
```

## Revisão contínua — abres, vês, fechas, abre o próximo

```bash
python3 app/pt_stage072_review_sequencial.py
```

O programa percorre os **58 Stage 0.72** pela ordem do relatório V13. Para cada mapa:

1. Confirma que o SMD original não mudou desde a auditoria.
2. Copia temporariamente para a **mesma pasta** o `.blend` já aprovado (preservando caminhos relativos de texturas).
3. Abre essa cópia no Blender com o **viewer V19**, o mesmo mecanismo de `pt_asset.py view stage072` (eixos e Floating Origin corretos).
4. **Aguarda o processo Blender terminar** quando fechas a janela.
5. Elimina a cópia temporária, regista `VISTO_SEM_AVALIACAO` e **abre o próximo automaticamente**.

Não volta a executar parsing, importação ou transporte no Blender. A sessão utiliza a configuração Blender já resolvida pela Asset Tool, incluindo Flatpak.

## Modo de avaliação registada (opcional)

```bash
python3 app/pt_stage072_review_sequencial.py --avaliar
```

Após fechares cada janela, o terminal pergunta: **a** = aprovado visualmente; **r** = precisa revisão (com nota opcional); **s** = ignorar; **Enter** = apenas visto; **q** = parar. No modo normal **não pergunta nada**, avança imediatamente para o próximo.

### Começar por uma amostra / retomar / reabrir

```bash
python3 app/pt_stage072_review_sequencial.py --limit 3
# Mais tarde, exatamente o mesmo comando sem --limit retoma os restantes:
python3 app/pt_stage072_review_sequencial.py

# Reabrir um mapa, mesmo que já esteja marcado como visto:
python3 app/pt_stage072_review_sequencial.py --reabrir Field/Ricarten/village-2.smd --avaliar
```

Ctrl+C interrompe sem apagar as avaliações já gravadas. Se o Blender falhar, o mapa fica como `ERRO_ABERTURA` e não como revisto; poderá ser tentado novamente. O script não pede nem usa `--fresh` e não altera o checkpoint V13.

## Relatórios

```text
app/pt_build/etervale/stage072_visual_review/
├── stage_0_events.jsonl
├── stage_0_avaliacoes.csv
└── stage_0_avaliacoes_summary.json
```

**Importante:** `VISTO_SEM_AVALIACAO` apenas significa que a janela Blender foi fechada com êxito. **Não é certificação visual.** Mesmo `APROVADO_VISUALMENTE` é uma classificação humana da viewport, não uma prova de renderização in-game, colisão, animação ou funcionamento de Texture Paint. Mapas com texturas em falta permanecem assinalados no relatório original.

O ficheiro `.blend` original certificado pelo lote **nunca é aberto para edição**, e qualquer `Ctrl+S` feito no Blender atua apenas sobre uma cópia temporária, eliminada ao fechar. Para editar/pintar, continua a utilizar o comando `paint stage072`, que cria um workspace próprio.

## Limitações da verificação offline

A sequência, o bloqueio até ao fecho do processo, os registos e a retoma foram testados com um launcher Blender simulado. **A abertura gráfica real no Flatpak Blender 5.2 tem de ser confirmada no teu ambiente.**
