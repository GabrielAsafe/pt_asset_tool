# Etervale V27 — Classificação por textura e pré-visualização LOD

Incremental sobre V26. **Não modifica SMD, mapas, UVs, colisões, modelos originais nem cliente do jogo.** O instalador valida o SHA-256 dos ficheiros da V26 e faz backup antes de modificar scripts. Nunca forçar SOURCE_FILE_CONFLICT.

## Instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V27_TEXTURAS_LOD_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v27_texturas_lod.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v27_texturas_lod.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_texture_v27.py
```

## Blender

```bash
python3 app/pt_environment.py --inventory
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

Abrir **N → Etervale → Modernizar ambiente → Texturas e componentes · V27**. Clicar **Analisar texturas do Stage**; escolher textura, isolar componente (ou criar objetos temporários por componente), e confirmar SOLO/FOLHAGEM/ARBUSTO/FOGO/PEDRA/PAREDE/AGUA/OUTRO. A confirmação cria só uma regra no JSON `.v27_texture_semantics.json`, sempre associada ao SHA do Stage. Sem publicação. **Nunca aplicar uma categoria a uma textura partilhada por geometrias de tipos diferentes** sem revisão; um uso misto exige revisão por componente futura.

Para comparar uma árvore, usar o painel principal e escolher `island_tree_01`, `island_tree_02` ou `pine_sapling_medium`; `tree_bark_03` deixa de aparecer como árvore, pois é material PBR. Modelos densos até 2,5 milhões de vértices poderão ser reduzidos numa cópia LOD privada; acima desse limite continuarão a ser recusados por segurança.

Ler: `docs/etervale/V27_TEXTURAS_COMPONENTES_E_LOD.md`.
