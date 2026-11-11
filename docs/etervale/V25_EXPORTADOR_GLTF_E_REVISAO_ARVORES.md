# Etervale V25 — Verificação do glTF nativo + revisão segura de copas/troncos

## Evidência do exportador original

Fonte consultada: `Etervale-main(2).zip` (snapshot disponibilizado, não prova da revisão mais recente instalada):

- `tools/PristonTale.GltfExport/Program.cs`: aceita um arquivo `.smd` de stage ou modelo, `.smb`, `.inx`, saída `.glb/.gltf`, opções `--recenter`, `--scale` e `--flip-v`.
- `tools/PristonTale.GltfExport/GltfSceneExport.cs`, `BuildStage` (linhas 65–153): lê **faces do stage**, escolhe `MeshFor(material)`, gera malhas com nomes `stage0`, `stage1`... e chama `scene.AddRigidMesh(mesh, root)`. A distribuição depende de materiais e do limite de superfícies por malha (`MaxSurfacesPerMesh=200`), **não de objetos árvore/arbusto/rocha**. Não retém um ID por árvore.
- `BuildModel` (a partir da linha 155): percorre `model.Objects` e constrói um `RigidMesh` por objeto real, conservando nós de modelo. A separação nativa é útil para `.smd` de modelo, não para elementos embebidos no SMD do terreno.
- `Client/PristonTale.Gameplay/World/GameScene.Fields.cs` (linhas 141–149): carrega o `StageSmd` e uma lista de `StageObjectSmds` separadamente para o renderer. O exportador de um único Stage não incorpora automaticamente os objetos separados dessa lista.

**Conclusão:** o glTF nativo não substitui os agrupamentos V22–V24 para vegetação embebida na malha Stage. Uma futura exportação semântica pode reutilizar o pipeline glTF, mas deverá receber *grupos explícitos de faces*, preservando a origem e os índices, e só depois de validar materiais, geometria e coordenadas. Esta V25 não altera código do exportador nem exporta novos glTF.

## V25 — objetivo

Analisar as **41 associações** já propostas pela V24 no mapa `Field/forest/fore-1.smd`:

- 16 recebem prioridade `HIGH_REVIEW`, por compatibilidade de posição, altura, largura e distância do tronco concorrente;
- 25 continuam `MANUAL_REVIEW`;
- todos começam `PENDING`, sem fusão automática, mesmo que a pontuação seja alta.

A pontuação de 0 a 100 **não é uma probabilidade calibrada nem prova botânica/colisão**. Serve para ordenar o trabalho de inspeção. Troncos são hipóteses, terreno é estimado, e o eixo original do jogo é Y-up; no proxy V19 do Blender é Z-up.

## Procedimento no Blender

1. Abrir `python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd`.
2. Em `N > Etervale > V25 · Rever associações copa/tronco`, selecionar `1. Analisar sugestões V24` (reutiliza o estado persistente, caso exista).
3. Escolher um par e clicar `2. Isolar par (copa + tronco)`. O stage original fica **temporariamente oculto** e são mostradas duas cópias independentes, com UVs e materiais.
4. Inspecionar visualmente e escolher `Aprovar ligação`, `Rejeitar`, ou `Deixar para revisão`. O estado fica em JSON próprio, com lock de SHA e *fingerprint* V24.
5. Opcional: `Aprovar N prioritárias (confirmar)` exige confirmação explícita; não use sem rever a amostra.
6. `Restaurar mapa e remover par` recompõe a visibilidade da malha original.
7. `3. Criar grupos V25 no Outliner` gera cópias só para inspeção. Os objetos começam ocultos para evitar geometria sobreposta; mostrá-los seletivamente no Outliner.

**Nunca usar os botões de deteção V22** para reconstruir estas associações. Não modificar manualmente o JSON V24 durante uma revisão V25 aberta: alterações V24 invalidam o fingerprint e bloqueiam a reutilização para evitar aplicar decisões a faces erradas.

## Segurança e ficheiros

- V22, V23, V24, SMD, texturas, colisões, runtime e exportador glTF **não são alterados**.
- Novo JSON: `app/pt_build/etervale/stage072_semantic_v21/maps/<id>.v25_review.json`. Apenas decisões/ponderações, não meshes.
- A fusão é virtual, feita por índices de faces em cópias de visualização. Verificam-se cobertura exata, ausência de sobreposições, IDs de origem e ausência de `accepted_for_runtime`.
- A aprovação de uma **ligação copa-tronco** não equivale à aprovação de toda a árvore nem certifica publicação no jogo.
- Saída esperada: `PT_V25_BUILD=PASS matches=41 high_review=16` e, após criar cópias, `PT_V25_SEPARATE=PASS objects=<até 99> approved_links=<N>`.

## Testes

Teste automático `app/dev_tests/test_etervale_stage072_tree_review_v25.py`: algoritmo, aprovação explícita, preservação das faces e da V24, rejeição de fingerprint alterado, prevenção de publicação, e integração estática Blender. A parte real do Blender 5.2 requer validação na máquina do projeto.
