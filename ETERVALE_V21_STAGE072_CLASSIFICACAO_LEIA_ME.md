# V21 — Pincel semântico de classificação Stage 0.72 para Blender

Este pacote **acrescenta** ao Asset Tool o protótipo do Environment Modernizer, mantendo V12–V20.

## Instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -n "$HOME/Transferências/ETERVALE_V21_STAGE072_CLASSIFICACAO_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v21_semantic.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v21_semantic.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_semantic_v21.py
```

Se `SOURCE_FILE_CONFLICT`, **não** uses `--force`: preserva a instalação atual e investiga o conflito. A instalação cria ficheiros novos, com SHA-256 e backups transacionais.

## Primeiro mapa

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

Blender: **N → Etervale → Classificação V21**. Categoria **Árvore** → Seleção **Raio + material** → **Ativar pincel** → clicar/arrastar sobre as copas → soltar. Pressiona **Esc** para desativar o pincel. Na lista, ajusta posição, escala, rotação ou nota. **Fecha o Blender**: o JSON está guardado independentemente da cópia temporária do `.blend`.

### Reabrir, inspecionar e sequenciar

```bash
python3 app/pt_stage072_semantic_paint.py --list
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd --dry-run
python3 app/pt_stage072_semantic_paint.py --all --limit 3
```

Resultados: `app/pt_build/etervale/stage072_semantic_v21/maps/*.json` e `*.materials.json`.

**Limites:** as classes são anotações/propostas, não detectores automáticos perfeitos; não há importação Poly Haven nem publicação, alteração de SMD, colisões, UVs ou renderer. A validação gráfica real do pincel em Blender 5.2 terá de ser feita na tua máquina.

Ver documento `docs/etervale/V21_STAGE072_PINCEL_SEMANTICO.md`.
