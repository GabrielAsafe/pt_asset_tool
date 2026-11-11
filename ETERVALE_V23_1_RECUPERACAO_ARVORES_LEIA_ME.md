# V23.1 — Recuperação e preservação das árvores

A sessão V23 identificou **103 árvores e 56 possíveis troncos**, mas um clique posterior no detetor V22 sem os exemplos manuais apagados produziu zero propostas e substituiu o JSON. Este hotfix impede a repetição do incidente e inclui a cópia **exata das 103 propostas originais que foram enviadas**.

## Instalação

Fechar Blender primeiro.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V23_1_RECUPERACAO_ARVORES_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v23_1_recuperacao.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v23_1_recuperacao.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_v23_1_preservacao.py
```

## Recuperar as 103 árvores sem Blender

```bash
python3 app/pt_stage072_restore_v23_1.py --project-root "$PWD" --dry-run
python3 app/pt_stage072_restore_v23_1.py --project-root "$PWD"
```

O script preserva dados existentes que não estejam vazios. Se existir um JSON com zero candidatos, cria backup antes de restaurar as 103 propostas. Não modifica os SMD.

## Abrir o mapa e inspecionar

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender: `N > Etervale > V23 · Árvores completas e GLB`: clicar **Reconstruir árvores** e verificar `PT_V23_TREES=PASS trees=103 trunk_candidates=56 leaves_only=47`; depois **Criar objetos no Outliner**. Para uma árvore, selecionar na lista, apontar `Modelo GLB` a um ficheiro local `.glb` e clicar **Prévia árvore selecionada**. O botão **Prévia aprovadas** só fica ativo depois de aprovar uma ou mais árvores. A visualização é uma cópia temporária, sem publish.

**Não clicar novamente em Detetar V22** com os exemplos manuais V21 vazios: agora isso devolve uma mensagem, sem apagar os resultados restaurados.

Testes offline e validação de instalação não são uma certificação visual no Blender do utilizador.
