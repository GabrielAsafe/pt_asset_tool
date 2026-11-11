# Etervale V23.1 — Recuperação das 103 árvores e proteção contra zero-result overwrite

## Incidente observado em Blender 5.2 (10-11-2026)

- O detetor V22 possuía 103 candidatos na floresta, identificados por 3.859 faces diferentes e `source_sha256=df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62`.
- O Blender V23 reconstruiu 103 árvores; 56 receberam troncos candidatos, 47 permaneceram com folhas apenas.
- As regiões de treino V21 tinham sido apagadas intencionalmente. Clicar de novo em **Detetar V22** gerou `proposals=0` e substituiu o JSON não vazio pelo resultado vazio.
- Uma nova sessão V23 consumiu as propostas vazias, recriou `trees=0` e também substituiu o plano de árvores.
- A pré-visualização V23 requer árvore selecionada não rejeitada ou pelo menos uma árvore explicitamente `APPROVED`; reconstrução por si só não aprova nada.

## Medidas corretivas

1. O comando V22 `Detetar` nunca grava resultados vazios. Se já existem candidatos, estes mantêm-se intactos e o operador avisa sobre a ausência de propostas novas.
2. O comando V23 `Reconstruir árvores` também não grava resultados com zero árvores.
3. O painel V23 apresenta a quantidade de aprovações; `Prévia aprovadas` fica desativada com zero aprovações e os erros explicam o motivo.
4. `app/pt_stage072_restore_v23_1.py` permite recuperar *apenas* o JSON original de `fore-1.smd` entregue pelo utilizador, sem Blender e sem publicar alterações. O recuperador exige versão/formato, SHA do mapa, topologia, não-publicação e 103 candidatos. Se o ficheiro instalado já tiver propostas não vazias, não altera nada. Quando o substitui, guarda backup.

## Limites e segurança

- Não apaga, renomeia, processa ou reescreve `Etervale-git/assets`, SMD, previews V19 ou checkpoints V13.
- O treino V21 apagado não é restaurado nem necessário para reconstruir a V23 a partir das 103 propostas V22 recuperadas.
- As 103 propostas representam agrupamentos geométricos, não 103 árvores visualmente certificadas.
- Os 56 troncos são *candidatos*. Não ocultar colisor nem mudar o runtime sem inspeção.
- A restauração não inventa decisões manuais V23 perdidas após a substituição do plano. O plano V23 reconstruído terá de ser revisto.
- A visualização de um GLB local é exclusiva do Blender, não um publish.

## Comandos

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 patches/aplicar_etervale_v23_1_recuperacao.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v23_1_recuperacao.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_v23_1_preservacao.py
python3 app/pt_stage072_restore_v23_1.py --project-root "$PWD" --dry-run
python3 app/pt_stage072_restore_v23_1.py --project-root "$PWD"
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

Na interface Blender: `N > Etervale > V23 · Árvores completas e GLB` → `Reconstruir árvores` (103 esperadas) → `Criar objetos no Outliner` → selecionar uma árvore e verificar copa/tronco → escolher `.glb` local → `Prévia árvore selecionada`. Para `Prévia aprovadas`, usar primeiro `Aprovar` na árvore ou árvores escolhidas.

**Não executar `Detetar V22` novamente enquanto as regiões manuais V21 estiverem vazias.** Se for executado, o novo comportamento devolverá um erro explicativo e preservará os resultados existentes.
