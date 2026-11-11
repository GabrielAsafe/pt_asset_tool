# ETERVALE V25 — Auditoria do exportador glTF e revisão copa/tronco no Blender

Patch incremental **sobre V24**. Não reinstala V22–V24, não modifica o Etervale original, não substitui árvores, não publica assets.

## Diagnóstico do glTF nativo

Foi examinado o código existente no arquivo `Etervale-main(2).zip`:
`tools/PristonTale.GltfExport/GltfSceneExport.cs` e `Program.cs`.

- **Modelo SMD/SMB:** sim, `BuildModel` tem `model.Objects` e separa os objetos próprios do modelo.
- **Stage SMD 0.72:** não, `BuildStage` agrupa faces por **material** em malhas chamadas `stage0`, `stage1`...; não contém uma árvore por nó.
- O runtime carrega modelos de cenário separados de `StageObjectSmds`, mas exportar um único stage não recria esses objetos externos.

Logo, a V25 continua a usar índices de faces e coordenadas já obtidos pela V22–V24. O futuro exportador de cenas semânticas poderá reutilizar os mecanismos glTF, mas não resolve a classificação automaticamente.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V25_REVISAO_ARVORES_GLTF_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v25_arvores.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v25_arvores.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_tree_review_v25.py
```

Se aparecer `SOURCE_FILE_CONFLICT`, **não forces**; o ficheiro foi alterado localmente e precisa de um merge consciente. O instalador guarda backup de todos os modificados.

## Operação no Blender

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

Em `N > Etervale > V25 · Rever associações copa/tronco`:

1. **Analisar sugestões V24** — usa as 41 sugestões já guardadas; 16 prioritárias e 25 para revisão no conjunto atual.
2. Escolher uma sugestão, clicar **Isolar par (copa + tronco)** e utilizar `Numpad .` sobre o objeto selecionado para o enquadrar.
3. Aprovar/rejeitar/adiar **ligação** individual. Aprovação não prova a árvore inteira nem modifica o jogo.
4. Opcional: botão **Aprovar 16 prioritárias (confirmar)**, só após inspeção de amostra; exige confirmação.
5. **Restaurar mapa e remover par** para ver a cena completa.
6. **Criar grupos V25 no Outliner**: gera objetos privados a partir das associações aprovadas. Por defeito ficam ocultos; mostrar seletivamente.

Não executar `V22 Detetar` para esta revisão. Não editar V24 manualmente depois de iniciar V25. O fingerprint protege contra associações obsoletas.

O novo resultado é `app/pt_build/etervale/stage072_semantic_v21/maps/6cd0d6e8c7586543.v25_review.json`.
O JSON V24 e os SMD permanecem intactos.

## Evidência esperada

```text
PT_V25_BUILD=PASS matches=41 high_review=16 ...
PT_V25_INSPECT=PASS orphan=... target=... source_unchanged=true
PT_V25_DECISION=PASS orphan=... decision=APPROVED ...
PT_V25_SEPARATE=PASS objects=... approved_links=... face_coverage_preserved=true source_mesh_unchanged=true
```

Com as 16 ligações prioritárias aprovadas, `objects=83`. Com nenhuma aprovada, `objects=99`. Esses números são de agrupamentos de inspeção, **não** de árvores certificadas.

## Limitações

Código do exportador analisado a partir de um snapshot fornecido, não de uma consulta ao teu checkout atual. Os testes neste ambiente validam lógica Python, compatibilidade estática e instalação; o painel e as cópias no teu Blender 5.2 precisam de confirmação real.
