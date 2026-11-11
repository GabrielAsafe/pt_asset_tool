# Etervale V23 — Árvores como objetos de inspeção e substituição GLB (preview)

**Escopo:** `Field/forest/fore-1.smd` e outros Stage 0.72 já importados pelo pipeline V12–V22. Não altera cliente, SMD, textura, writer, colisão, runtime ou checkpoint. Não publica no jogo.

## Por que a hierarquia Blender tem uma malha única?

`PT_STAGE072_VIEW_STAGE` é o proxy de visualização V19 do Stage 0.72. `PT_STAGE072_MAT_*` são *material slots*, não objetos individuais. Não se deve separar a malha original por material: o mesmo material pode aparecer em centenas de árvores e em elementos distintos, e a separação por material não reconstrói a identidade de cada árvore.

V23 usa os **índices das faces** já propostos pela V22, examina faces verticais perto da posição da copa para propor um tronco e gera objetos independentes em `PT_V23_ARVORES_INSPECAO_SO_COPIA`. É apenas uma nova malha **em memória** na sessão Blender; o proxy de origem continua intacto.

## Fluxo

1. Abre o mesmo launcher `python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd`.
2. `N > Etervale > Classificação V21 > V23 · Árvores completas e GLB`.
3. Clica **1. Reconstruir árvores**. V23 lê o JSON V22 já guardado. Cada proposta inclui `foliage_faces`, `trunk_faces`, um ponto de implantação estimado e um estado. A associação de tronco é **heurística**; `LEAVES_ONLY_REVIEW` e `TRUNK_CANDIDATE_REVIEW` não são provas de uma árvore completa.
4. Clica **2. Criar objetos no Outliner**. Abre a coleção `PT_V23_ARVORES_INSPECAO_SO_COPIA`. A árvore escolhida na lista é mostrada; as restantes ficam ocultas para não poluir a vista. A malha Stage original não é separada nem editada; os objetos de inspeção têm materiais, UVs e cores copiados.
5. Revê uma árvore e clica **Aprovar** (ou **Rever/Rejeitar**) na V23. Não é aprovação para publicação no jogo.
6. Descarrega um modelo 3D estático autorizado em formato `.glb` da tua biblioteca. No campo **Modelo GLB**, escolhe o ficheiro no disco. Clica **Prévia árvore selecionada**. A ferramenta normaliza o modelo (centro XY + base Z), ajusta altura aproximada e instancia-o na posição estimada.
7. Opcionalmente, ativa **Esconder original no preview**: a V23 cria **uma cópia** da malha Stage sem as faces da árvore selecionada, oculta o proxy integral original apenas na viewport e mostra o GLB por cima. **Restaurar original** desfaz esta comparação sem alterar dados persistentes do Stage.
8. **Prévia aprovadas** mostra até 25 árvores por operação, evitando importar centenas de árvores pesadas e respetivas texturas de uma só vez.

## Dados e proteção

O plano V23 fica ao lado dos dados V22:

`app/pt_build/etervale/stage072_semantic_v21/maps/<id>.v23_trees.json`

A identidade continua vinculada a `asset`, `source_sha256`, `source_face_count` e `source_vertex_count`. `publish_enabled=false`, `accepted_for_runtime=false` sempre. Estados de revisão e ajustes existentes sobrevivem a nova reconstrução quando os IDs coincidem.

A deteção é cautelosa: exclui materiais com indícios arquitetónicos ou de colisão; exige agrupamento de faces verticais conectadas para apontar um tronco; não assume que toda a vegetação é árvore. A base é uma estimativa de chão, **não contacto certificado nem teste da colisão**.

As instâncias GLB só existem durante a sessão temporária. É obrigatório testar visualmente escala, textura, rotação, implantação e se os agrupamentos de folhas e tronco realmente pertencem à mesma árvore. A publicação no cliente C# exigirá formato de colocação e integração específica — **esta V23 não exporta nem publica**.

## Limites

- Formato externo: GLB estático, máx. 150 MB, 700 mil vértices, 128 meshes, sem armatures nem shape keys. São guardrails para o piloto e não recomendações de desempenho para o jogo.
- Até 25 instâncias por pré-visualização.
- A V23 não inclui nem descarrega modelos da Poly Haven; utiliza um `.glb` que o utilizador escolheu.
- Não faz reconstrução real de troncos ausentes nem garante que propostas V22 correspondem 1:1 a árvores físicas.
- As UVs/colors e materiais são copiados nos objetos de inspeção, mas a ordem correta dos objetos depende da validação no Blender real.
- A aprovação V23 não modifica as decisões V22 e não publica no jogo.

## Confirmação em Blender 5.2 real

Esperados no terminal:

- `PT_V23=READY ...`
- `PT_V23_TREES=PASS trees=N trunk_candidates=M leaves_only=...`
- `PT_V23_SEPARATE=PASS objects=N source_mesh_unchanged=true`
- `PT_V23_PREVIEW=PASS instances=1 ... game_assets_modified=false`

Se aparecer erro, enviar a linha e traceback; **não aprovar em massa** e não modificar SMD/texlinks para o contornar.
