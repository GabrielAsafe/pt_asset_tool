# Etervale V29 — Ensaio global das árvores com LOD0

## Intenção

Instanciar visualmente `island_tree_01_1k.blend.zip`, LOD0, em todos os grupos do Stage `Field/forest/fore-1.smd` que possuam **tronco candidato**. Com os dados V24 fornecidos: 56 grupos com tronco, 43 sem tronco, 3.711 faces selecionadas nos 56 grupos. A correspondência é heurística, **não certificada** para o runtime.

## Funcionamento

- Botão no painel único **Etervale · Modernizar ambiente**: `Testar todas: LOD0 alto`.
- Não exige aprovações individuais; **não cria novas aprovações**. `pt_v26_scale` aplica escala relativa global.
- Exige cache SHA-256 válida do LOD0 preparada pela V28/V28.1, antes de alterar a cena.
- Carrega **uma** biblioteca privada com o modelo LOD0 e cria até 100 instâncias de coleção, uma por grupo com tronco. A mesma malha é partilhada, em vez de 56 cópias.
- A opção `Ocultar árvores antigas (só preview)` usa um atributo booleano temporário por FACE e um modificador **Geometry Nodes/Delete Geometry** aplicado ao proxy visual V19. Não cria uma segunda malha completa do mapa. O objeto source do Stage, SMD, UVs/colisões e modelos da pasta de downloads permanecem inalterados.
- `Restaurar árvores antigas` ou `Restaurar vista` remove as instâncias, o modificador e o atributo da prévia.
- Guarda apenas um registo de execução em `app/pt_build/.../*.v29_batch_preview.json`, sem estado de publicação ou aprovação.

## Limites e riscos

1. As 43 propostas só com folhagem permanecem visíveis e precisam de análise: parte pode ser arbustos ou folhas associadas a outra árvore.
2. 56 instâncias de um LOD0 com 102.933 faces representam **~5,76 milhões de faces desenhadas** se todas estiverem visíveis. Instanciar poupa memória, mas não garante FPS; testar em Material Preview ou Solid antes de renderizar.
3. O posicionamento usa a base proposta no JSON, não um contacto com terreno validado por colisão.
4. O Geometry Nodes requer Blender 5.2. O teste Python não executa o Blender do utilizador; deve validar os resultados na sua instalação.
5. Não exporta para o cliente Etervale e não altera dados originais. **Não usar o resultado para publicação do jogo.**

## Uso

```bash
python3 app/pt_environment.py --list-lods
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

No painel, escolher `island_tree_01_1k.blend.zip`, deixar `Ocultar árvores antigas (só preview)` ligado, carregar em `Testar todas: LOD0 alto`. Confirmar:

```text
PT_V29_BATCH=PASS instances=56 lod=LOD0 library=1 original_faces_hidden=3711 excluded_foliage_only=43 source_unchanged=true game_unchanged=true publish=false
```

Se o viewport ficar lento, usar `Restaurar árvores antigas` e testar LOD1 com um grupo menor; os LODs preparados continuam intactos.
