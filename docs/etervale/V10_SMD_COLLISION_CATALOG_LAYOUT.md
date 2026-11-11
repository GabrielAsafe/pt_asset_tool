# Etervale V10 — Lote SMD e altura sincronizada do catálogo

## 1. Colisões físicas Linux durante previews

A source real contém duas texturas distintas cuja grafia difere pela capitalização:

- `assets/char/npcXms/Bonbori/bonbori.tga`
- `assets/char/npcxms/Bonbori/bonbori.tga`

A referência lógica `Char/NpcXms/Bonbori/bonbori.tga` não encontra um caminho com capitalização exata. O resolvedor rigoroso aborta corretamente com `case-insensitive client path collision without exact-case match`.

**Correção V10:** capturar **somente** esta colisão conhecida por asset, marcar o modelo como `BLOCKED` com detalhe das duas alternativas, persistir essa informação em `app/pt_build/previews/smd_catalog/batch_state.json` e continuar o lote. O resultado final é `COMPLETE_WITH_BLOCKED`/`SMD_PREVIEW_BATCH=PARTIAL_BLOCKED`, não `PASS` puro. Com referência de capitalização exata, uma das duas texturas pode ser resolvida sem bloqueio. Nenhum caminho ambíguo é escolhido automaticamente e nenhum ficheiro do jogo é editado. Erros inesperados de programação não são convertidos silenciosamente em sucesso.

A UI apresenta contador `CASE COLLISION N` e as primeiras 4 ocorrências em *Diagnóstico do lote e erros*. O estado global de READY ainda vem do índice SMD persistido. Uma colisão bloqueada não é apresentada falsamente como READY.

**Resolução definitiva:** decidir qual das duas texturas se destina ao modelo e ajustar a referência no asset candidato em staging, validando com o leitor C# e com o jogo. Não apagar ou renomear as duas texturas automaticamente.

## 2. Catalog e Detail com altura comum

Antes, `.table-wrap` e `.gallery` limitavam o scroll a `53vh`, enquanto `.detail-panel` usava `72vh`. Em desktop, a V10 mede o topo efetivo da grelha e utiliza o viewport restante: ambos os painéis recebem a mesma altura através de CSS Grid. `table-wrap`, `gallery` e `detail-panel` têm scroll interno. Ao mudar zoom/tamanho de janela a medida é recalculada. Na vista estreita (<1181px) os painéis empilham e recebem scroll próprio, porque não existe espaço suficiente para duas colunas legíveis.

## Validação de instalação

- Pacote incremental para **V9 já instalada**. Instalador verifica SHA-256 das versões de origem; ficheiros alterados pelo utilizador são recusados com `LOCAL_FILE_CONFLICT`.
- Faz backup de cada arquivo modificado; o ZIP só toca no PT Asset Tool.
- Regressão Python direcionada P0/P1/V5–V10: **142 passed** em ambiente reconstruído.
- Chromium com HTML/CSS reais em 1920×1080, 1440×900, 1250×800, 1100×800, 800×800 e 390×844: duas colunas com altura igual no desktop; scroll de conteúdo interno; sem scroll horizontal.
- Teste de um índice físico sintético contendo duas texturas com diferentes capitalizações: 1 SMD `BLOCKED`, 1 SMD `READY`, sem modificações nos arquivos do cliente.
- O teste de milhares de SMD com Blender real depende da execução na máquina Etervale; V10 não certifica o runtime gráfico.
