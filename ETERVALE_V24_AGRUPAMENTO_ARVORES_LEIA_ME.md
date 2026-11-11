# Etervale V24 — Agrupar fragmentos de folhas em árvores

**Requer V23.1 instalada.** Não substitui os JSON V22/V23 nem os assets do jogo. Fecha o Blender antes de instalar.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V24_AGRUPAMENTO_ARVORES_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v24_arvores.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v24_arvores.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_tree_groups_v24.py
```

Se o `--dry-run` indicar `SOURCE_FILE_CONFLICT`, **não usar force**. Comunica o conflito, pois o patch valida SHA-256 antes de modificar. O instalador guarda backup dos ficheiros alterados.

Executar:

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender: `N → Etervale → V24 · Juntar folhas por tronco`, clicar **Agrupar propostas V23**, depois **Criar grupos no Outliner**. Confirmar `PT_V24_GROUP=PASS` e `PT_V24_SEPARATE=PASS`. Selecionar um grupo e observar se possui folhagem/tronco; se indicar uma associação sugerida e for visualmente correta, clicar **Associar à árvore sugerida**; depois recriar os objetos no Outliner. Os 103 objetos V23 permanecem disponíveis mas são ocultados durante a inspeção V24.

**Não clicar V22 Detetar**, porque as 103 propostas já estão recuperadas. Não aprovar grupos em massa sem revisão. Nenhum dos passos escreve no SMD ou no cliente. Uma prévia GLB requer um `.glb` real de árvore, não `village-2.glb`.

A associação automática é conservadora: se a ferramenta deixar folhas soltas, essa é uma decisão explícita de segurança e não uma falha da importação. A inspeção do Blender 5.2 real ainda está pendente.
