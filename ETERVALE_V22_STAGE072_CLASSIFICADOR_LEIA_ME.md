# V22 — Detetor geométrico semântico (Blender)

Este pacote deve ser instalado sobre **V21.1**, já usada no teu projeto. Só altera o add-on semântico do Blender e acrescenta lógica de propostas: não mexe nos SMD, clientes, previews V19, JSON V21 existentes nem nas auditorias de 58 mapas.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V22_STAGE072_CLASSIFICADOR_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v22_semantic.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v22_semantic.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_auto_detect_v22.py
```

Não aplicar com `--force`; em caso de `SOURCE_FILE_CONFLICT`, não modificar o ficheiro à mão. O instalador verifica a origem por SHA, cria backup e recusa conflitos.

## Experimentar

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender: `N > Etervale > Classificação V21 > V22 · Detetor automático`.

1. Carrega `Detetar elementos no mapa` (raio inicial **1.5**, máx. **120** propostas).
2. Clica numa proposta da lista: as faces selecionadas aparecem com wireframe laranja; confere se pertencem realmente ao mesmo objeto.
3. Carrega `Aprovar`, `Rejeitar` ou `Precisa de revisão`. Podes mudar a categoria e ajustar a posição nos campos da proposta.
4. Fecha o Blender; o resultado está em `app/pt_build/etervale/stage072_semantic_v21/maps/<id>.v22_proposals.json`.

O JSON V21 original **não é convertido nem apagado**. A V22 guarda propostas noutro ficheiro. Aprovar uma proposta não altera o jogo. As árvores são reconhecidas por pistas de folhagem, altura local e agrupamentos de faces; não por qualquer objeto alto. Pedras e fogos requerem pista de material ou exemplos manuais: a V22 não inventa categorias sem evidência.

Para repetir a deteção com outro raio, fecha o pincel V21 com `Esc` se estiver ativo, modifica o raio e executa novamente. As decisões anteriores são reaproveitadas em casos equivalentes.

Se `PT_V22_DETECT=FAIL`, envia a linha de erro e o traceback. **Blender 5.2 real ainda precisa de validação** nesta versão.
