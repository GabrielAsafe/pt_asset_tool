# V26 — Environment Modernizer: interface unificada e modelos locais

## Objetivo

Uma operação simples para modernização visual de árvores em Stage 0.72:

1. `python3 app/pt_environment.py --inventory` identifica os recursos locais.
2. `python3 app/pt_environment.py --map Field/forest/fore-1.smd` abre o Stage V19 já validado.
3. No painel **N → Etervale → Modernizar ambiente**, escolhe uma árvore com tronco.
4. **Isolar árvore** mostra *uma* malha de inspeção (não cria cópia integral do Stage).
5. Escolhe `island_tree_01_1k.blend.zip`, `island_tree_02_1k.blend.zip` ou `pine_sapling_medium_1k.blend.zip` e carrega em **Comparar modelo novo**.
6. Ajusta o fator de escala e, se estiver correto, **Aprovar substituição**; é gravado um JSON privado.
7. **Restaurar vista** remove os objetos temporários da cena, sem alterar geometria certificada ou ficheiros do cliente.

O painel V26 substitui a apresentação dos painéis V21/V22/V23/V24/V25; os validadores e os operadores internos anteriores permanecem para recuperação de dados e diagnósticos. Não apaga JSON ou checkpoints. Não executa deteções V22 automaticamente nem reescreve resultados existentes.

## Biblioteca local

Entrada: `AssetsForAutomaticSubstitution` na raiz do projeto. Os arquivos `.blend.zip` de árvores são descompactados com validação de caminho, tamanho e symlinks em `app/pt_build/etervale/environment_v26/asset_cache/<SHA256>/`. A biblioteca original é somente leitura. O modelo Blender é carregado apenas numa coleção de referência privada e instanciado na posição estimada V24/V25, com normalização para a base no solo e altura da árvore antiga.

Modelos sugeridos no inventário do utilizador:
- `island_tree_01_1k.blend.zip`
- `island_tree_02_1k.blend.zip`
- `pine_sapling_medium_1k.blend.zip`

Modelos de pedra (`boulder_01_1k.blend.zip`) são catalogados, mas ficam fora do seletor de árvores. Texturas como `bark_willow_1k.blend.zip`, `forest_ground_06_1k.blend.zip`, EXR e outros materiais são catalogados, mas **não são aplicados automaticamente** nesta versão.

## Limitações

- Não existe publicação no cliente Etervale nem writer para instâncias modernizadas.
- O isolamento não certifica tronco, raiz, colisão nem aparência do renderer do jogo.
- Os objetos `.blend` externos podem conter texturas relativas indisponíveis: a ferramenta reporta os nomes no terminal, sem inventar materiais.
- O preview coloca a árvore por estimativa da base V24; podem ser necessários ajustes finos de escala/posição.
- Um `.blend.zip` deve conter exatamente um `.blend`; um arquivo ambíguo é rejeitado.
- Esta entrega foi testada offline. Blender 5.2, arquivos reais Poly Haven e aparência final necessitam de validação no computador do utilizador.

## Integridade

- Nenhum script de writer SMD, renderer C#, loader nem checkpoint V13–V25 é modificado.
- Não são criadas cópias completas dos 58 mapas.
- V21–V25 permanecem consultáveis e não são apagados.
- A aprovação grava somente `.v26_environment.json`, `publish_enabled=false`, com hash do asset externo.
