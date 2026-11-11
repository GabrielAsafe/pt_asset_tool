# V23 — Finalizar a etapa das árvores (Blender)

Instalar **sobre V22**. Abre uma nova sessão Blender depois de aplicar.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V23_ARVORES_OBJETOS_GLB_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v23_arvores.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v23_arvores.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_trees_v23.py
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender, abre `N > Etervale > Classificação V21 > V23 · Árvores completas e GLB`.

1. **Reconstruir árvores**: cria o plano separado das propostas V22, tentando encontrar os troncos e as bases.
2. **Criar objetos no Outliner**: a árvore ativa passa a ser selecionável numa coleção de objetos de inspeção. **Não separa a malha Stage original**.
3. Seleciona a primeira árvore, revê e **Aprova** na V23, se estiver correta.
4. Em **Modelo GLB**, escolhe um modelo estático `.glb` que já tens no computador. **Prévia árvore selecionada** coloca esse modelo na posição proposta.
5. Opcional: ativa **Esconder original no preview** para comparar a nova árvore sem a geometria antiga selecionada. **Restaurar original** desfaz o preview.
6. Só após testar uma árvore usa **Prévia aprovadas**, limitado a 25 instâncias por vez.

Se o JSON V22 já contém 103 propostas, **não precisas de repetir a deteção**. Os dados existentes são mantidos; a V23 cria o seu próprio `.v23_trees.json`.

**Segurança:** SMD, modelos, ficheiros do cliente, colisões e writer inalterados. A V23 não publica em runtime. Troncos e posições são hipóteses para aprovação humana. Modelos externos têm de ser selecionados pelo utilizador; nada é descarregado pelo patch.

Se houver `SOURCE_FILE_CONFLICT`, não uses `--force`. Envia o dry-run e o SHA para decidirmos como fazer merge.

Documentação: `docs/etervale/V23_ARVORES_OBJETOS_PREVIEW_GLB.md`.
