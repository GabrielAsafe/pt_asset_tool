# V29 — Ensaio global: todas as árvores com tronco, LOD0 alto

A V29 é um patch **incremental sobre V28.1** e **não publica nada no jogo**.

## Instalação

Fechar o Blender antes de instalar.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V29_TESTE_GLOBAL_ARVORES_LOD0_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v29_lod0_global.py --project-root "$PWD" --dry-run
```

Se o `--dry-run` indicar que não existem conflitos:

```bash
python3 patches/aplicar_etervale_v29_lod0_global.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_environment_v29_batch.py
```

Se houver `SOURCE_FILE_CONFLICT`, **não** usar `--force` nem sobrescrever o ficheiro manualmente; enviar o resultado, pois há modificações locais não previstas.

## Teste de substituição visual em lote

```bash
python3 app/pt_environment.py --list-lods
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

No painel **N → Etervale → Modernizar ambiente**:

1. Escolher `island_tree_01_1k.blend.zip` em **Árvore 3D**.
2. Deixar **Ocultar árvores antigas (só preview)** ativo.
3. Clicar em **Testar todas: LOD0 alto**. O botão força LOD0, independentemente do seletor de LOD usado nos testes individuais.
4. Confirmar no Outliner a coleção `PT_V29_ARVORES_LOD0_TODAS_PREVIEW` com aproximadamente 56 instâncias.
5. Inspecionar escala, implantação e aspeto. Se o Blender ficar lento, mudar para modo Solid ou utilizar **Restaurar árvores antigas**.
6. **Restaurar árvores antigas** remove as instâncias e o efeito de ocultação, sem alterar as propostas V24/V25 ou as aprovações V26.

Saída esperada para o `fore-1.smd` com os dados anteriores:

```text
PT_V29_BATCH=PASS instances=56 lod=LOD0 library=1 original_faces_hidden=3711 excluded_foliage_only=43 source_unchanged=true game_unchanged=true publish=false
```

As **43 propostas sem tronco** ficam intocadas: podem conter arbustos, folhas avulsas ou copas ainda não associadas. Nenhuma aprovação individual é exigida ou criada. Estes objetos **não estão certificados para o runtime**.

## Atenção ao desempenho

O LOD0 preparado tem 102.933 faces. **56 instâncias partilham a mesma malha em memória**, mas, se todas estiverem visíveis, a GPU pode ter de desenhar cerca de 5,76 milhões de faces, além do terreno. Isso é apenas uma prova visual, não significa que o cliente MonoGame vá manter um FPS adequado.

O efeito temporário de ocultação usa **Geometry Nodes e um atributo FACE no proxy visual existente**; não cria uma segunda malha inteira de Stage, nem remove faces do SMD. O código foi testado em Python com os dados reais; a operação Geometry Nodes no Blender 5.2 deve ser confirmada no teu computador.

## Segurança e recuperação

- O instalador exige os hashes-base V28.1; faz backup automático e é idempotente.
- O modelo original e a cache LOD0 continuam inalterados.
- O ficheiro SMD, o cliente do jogo, as UVs e as colisões originais não são reescritos.
- O registo do ensaio é escrito apenas no diretório de trabalho `app/pt_build/.../*.v29_batch_preview.json`.
- Não ativar publicação a partir destes dados. `publish_enabled=false` e `runtime_certified=false`.
