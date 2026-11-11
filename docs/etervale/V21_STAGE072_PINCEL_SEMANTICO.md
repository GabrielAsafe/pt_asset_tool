# Etervale V21 — Environment Modernizer: classificação semântica no Blender

**Estado:** protótipo de anotação, não substituição nem publicação de assets. Compatível com os 58 Stage 0.72 transportados e abertos com a V19/V20. O cliente Etervale não é modificado.

## Objetivo

Marcar visualmente os elementos nos mapas com um **pincel semântico**: Árvore, Arbusto, Fogo, Pedra, Solo, Parede, Edifício, Água, Outro ou Possível Colisão. Cada traço cria uma *região* com índices de faces originais, nomes de materiais, posição-proposta no sistema original do jogo, escala, rotação, nota e referência opcional a um futuro asset 3D.

O Blender é aberto sobre uma **cópia temporária do preview V19**, com a geometria e os materiais intactos. A ferramenta só escreve anotações JSON em `app/pt_build/etervale/stage072_semantic_v21/maps/`. Estas sobrevivem ao fecho da janela e podem ser retomadas.

## Uso rápido

```
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender, abre a barra lateral com **N → Etervale → Classificação V21**:

1. Escolhe **Categoria** (ex.: Árvore) e **Seleção**: `Face`, `Ilha do material` ou `Raio + material` (normalmente o melhor para árvores em planos soltos). Ajusta o raio, inicialmente 1,8 unidades do mapa normalizado.
2. Clica em **Ativar pincel**. Clica ou arrasta sobre a árvore; ao soltar, o traço cria uma região. **Esc / botão direito** termina o pincel e devolve a navegação normal.
3. As marcações aparecem em marcadores coloridos. Na lista de regiões, altera **categoria**, **nota**, **asset 3D futuro** (texto, não importado), **ajuste XYZ de jogo**, **rotação** e **escala**. As modificações são guardadas automaticamente.
4. Seleciona **Apagar** como categoria para limpar um conjunto de faces; ou apaga uma região inteira na lista. Fecha o Blender; o ficheiro JSON persiste.
5. **Sugestões materiais** exporta um `.materials.json` com pré-classificações por nome. São apenas sugestões, não são aplicadas automaticamente.

**Importante:** quando o pincel está ativo, as teclas e a seleção do Blender podem ser capturadas; pressiona **Esc** para navegar normalmente e depois ativa o pincel outra vez.

## Modos de seleção

- **Face**: apenas o triângulo sob o cursor, para correções finas.
- **Ilha do material**: faces conectadas por arestas que partilham material, até limite de segurança. Não atravessa desconexões.
- **Raio + material**: encontra faces num raio 3D a partir do ponto clicado, mas só do **mesmo material**. Ajuda a agrupar planos desconectados das copas sem englobar o solo de outro material. O raio é do proxy V19 (aprox. 100 unidades para o maior eixo do mapa), **não metros do jogo**.

Uma árvore com materiais separados para **folhas e tronco** poderá precisar de dois traços; associar automaticamente todas as partes da árvore e projetar a base ao chão é uma melhoria posterior. Faces parcialmente coincidentes, transparências e seleção em profundidade também podem exigir correção manual.

## Propostas de posição / coordenadas

A V19 usa `(X,Y,Z) jogo -> (X,Z,Y) Blender`, com `view=(game-center)*view_scale`. A V21 converte o centro horizontal e o limite vertical inferior da seleção **de volta ao sistema Y-up do jogo**. Isto é um *anchor candidato*: a copa de uma árvore isolada pode ficar acima do ponto em que o tronco encontra o solo. O campo `Ajuste XYZ (jogo)` permite corrigir a proposta.

A V21 **não consegue ainda inserir o novo asset no jogo**, nem substituir automaticamente instâncias. O nome de um `.glb` ou `.fbx` pode ser anotado para o pipeline futuro, mas não é carregado/publicado nesta versão. `accepted_for_runtime` é sempre falso.

## Referências WALL, fogo e colisão

Uma textura chamada `WALL` não prova parede de colisão: V21 dá sugestão `PAREDE / REVER_WALL`. A categoria `Possível Colisão` é um rótulo de investigação e **nunca** autoriza apagar ou ocultar polígonos originais.

A classificação `FOGO` é uma etiqueta da região visual; **não** substitui um PNG ou TGA por partículas VFX. Essa substituição requer correspondência entre cena, posição dos emissores, runtime e orçamento de luzes.

## Segurança e evidência

- A seleção só atua nos **proxies V19** já validados, nunca nos objetos fonte certificados.
- O documento inclui `source_sha256`, número de vértices e faces, categorias, identificadores de face e coordenadas Y-up para evitar aplicar marcações a versões diferentes.
- O documento tem `publish_enabled=false`, `not_game_runtime_certified=true`; a validação recusa `accepted_for_runtime=true`.
- Escrita atómica via ficheiro temporário + `os.replace` para evitar JSON parcialmente escrito.
- Reabrir um mapa carrega as classificações; sobreposições entre traços transferem a posse das faces para o último traço.
- `stage_0_summary.json`, o `.blend` validado, o SMD, UVs, colisões, texturas e diretórios do cliente nunca são escritos.
- Se a fonte mudar, o launcher recusa abrir a anotação sobre uma geometria com hash/topologia diferente.
- A V21 não é uma prova de funcionamento no Blender 5.2 real: há testes Python offline e inspeção dos APIs, mas **sem Blender instalado neste ambiente**.

## Comandos

```
# Listar todos os mapas e contagens das classificações já guardadas
python3 app/pt_stage072_semantic_paint.py --list

# Teste sem abrir Blender
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd --dry-run

# Outro mapa específico
python3 app/pt_stage072_semantic_paint.py --map Field/Ricarten/village-2.smd

# Passar pelos 58 mapas sequencialmente, pulando os que já têm alguma região
python3 app/pt_stage072_semantic_paint.py --all

# Reabrir todos mesmo quando já classificados
python3 app/pt_stage072_semantic_paint.py --all --include-classified
```

A recomendação é começar por `fore-1.smd`, **testar uma árvore, um arbusto, uma pedra e uma fogueira** e inspecionar o JSON gerado. Só depois devemos aumentar a automação para sugestões de posição, agrupamento material + instâncias e importação Poly Haven.

## Critérios para a próxima fase

1. Um clique seleciona exatamente a geometria pretendida.
2. Reabrir o mapa recupera as regiões e a classificação.
3. As posições propostas são estáveis e podem ser ajustadas manualmente.
4. Nenhum SMD/colisão/source `.blend` é alterado.
5. A ferramenta nunca confunde textura `WALL` com colisão aprovada.

Após confirmar, a **V22** pode oferecer detetor de instâncias por material + clusterização espacial e biblioteca 3D importada (Poly Haven/ambientCG), com pré-visualização de substituições, LOD e publicação separada para o renderer Etervale.
