# Etervale V27 — Texturas por componente e LOD de pré-visualização

## Objetivo

A Stage 0.72 não contém objetos separados por árvore, chão, pedra ou chama. A V27 lê **somente** o proxy V19 já validado e cataloga as faces por **textura** (extraída do material `PT_STAGE072_MAT_####_ficheiro`) e por **continuidade de arestas**. Duas regiões que usam a mesma textura mas não partilham arestas originam componentes separados. Materiais diferentes que apontam ao mesmo ficheiro de imagem podem pertencer à mesma categoria, sem se assumir que são um único objeto.

Os resultados não são exportados para o jogo. A classificação é uma **hipótese** até confirmação explícita do utilizador, guardada apenas para este `asset` e `source_sha256`. Mesmo a categoria SOLO por normais horizontais é apenas uma sugestão: uma superfície de telhado também pode ser horizontal; a categoria FOLHAGEM pode significar árvore **ou arbusto**.

## Fluxo Blender

1. `python3 app/pt_environment.py --map Field/forest/fore-1.smd`
2. Painel `N > Etervale > Etervale · Modernizar ambiente > Texturas e componentes · V27` (subpainel fechado por defeito).
3. `Analisar texturas do Stage`. É criado `*.v27_texture_semantics.json` sob `app/pt_build/etervale/stage072_semantic_v21/maps/` com SHA do SMD.
4. Selecionar textura na lista, conferir `Sugestão` e `component_count`, definir uma categoria e clicar `Confirmar` **somente** após verificar. `Retirar` desfaz uma regra.
5. `Isolar componente` cria uma pequena cópia de inspeção; `Criar objetos desta textura` gera objetos independentes temporários por componente, com limites de segurança. `Restaurar vista` remove apenas esses objetos.

Todas as faces e UVs do proxy permanecem intactas. Em particular, confirmar uma textura como SOLO não remove faces do mapa, não muda colisão, não altera materiais PBR e não modifica um SMD. O material original pode ser partilhado por parede e chão; quando houver uso misto, deixar OUTRO ou usar a revisão por componente numa evolução futura.

## Importação de árvores densas

O seletor de árvores exclui materiais como `tree_bark_03_1k.blend.zip`. Candidatos válidos incluem `island_tree_01`, `island_tree_02`, `pine_sapling_medium`.

O importador `.blend` calcula a complexidade de entrada, recusando > 2.500.000 vértices ou > 3.500.000 faces, assim como modelos animados. Para modelos dentro desses limites mas acima do orçamento de pré-visualização, cria cópias **apenas em memória Blender**, aplica um Decimate em malha avaliada e tenta manter cerca de 300 mil vértices/260 mil polígonos. O modelo descarregado, a cache de origem e o Stage não são alterados. Modelos onde a redução não chegue, falhe ou destrua detalhes devem ser convertidos pelo artista com LOD manual.

**Nota:** a passagem de `tree_bark_03_1k.blend.zip` por V26 para o seletor de árvores foi um erro de classificação do nome. Não implica que o arquivo contenha uma árvore.

## Verificações

- `python3 -m pytest -q app/dev_tests/test_etervale_stage072_texture_v27.py`
- Esperado no Blender: `PT_V27_SCAN=PASS textures=... components=... faces=35519 source_unchanged=true publish=false`.
- Para LOD: `PT_V27_MODEL_LOD=PASS input_vertices=... output_vertices=... preview_only=true`.
- Testar primeiro **uma textura** e **uma árvore**. A execução real do Blender 5.2 e o aspeto visual dos materiais não puderam ser certificados nesta máquina.

## Preservação

`publish_enabled=false`, `game_assets_modified=false`; sem modificação de asset, colisão, UV, SMD ou runtime. O instalador V27 compara SHA-256 dos ficheiros V26, oferece `--dry-run`, faz backups e aborta em conflito sem sobrescrever mudanças locais. O JSON V27 não substitui V22, V23, V24, V25 nem as decisões V26.
