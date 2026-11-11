# ETERVALE V30 — Folhas residuais e vegetação em paredes

Patch **incremental sobre V29**, para o projeto `~/Transferências/pt_asset_tool`.

## Instalação

Fechar Blender. Copiar o ZIP principal para `~/Transferências`, depois:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V30_FOLHAGEM_PAREDES_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v30_folhagem.py --project-root "$PWD" --dry-run
```

Se o dry-run não mostrar conflitos:

```bash
python3 patches/aplicar_etervale_v30_folhagem.py --project-root "$PWD"
PYTHONPATH=app python3 -m pytest -q app/dev_tests/test_etervale_environment_v30_coverage.py
```

Se ocorrer `SOURCE_FILE_CONFLICT`, não aplicar à força; partilhar o log para compatibilizar as alterações locais.

## Execução

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

Na barra lateral N > Etervale > **Modernizar ambiente**:

- Modelo: `island_tree_01_1k.blend.zip` (LOD0 previamente preparado).
- Selecionar **Ocultar árvores antigas (só preview)**.
- Opcional: **Tentar apoiar na parede**.
- Clicar **Testar todos grupos LOD0 (rever)** (V30).
- Para desfazer: **Restaurar árvores antigas (V29/V30)**.

O botão conservador V29 continua disponível. A V30 inclui os **43 grupos de folhagem** que a V29 não substituía, sem os classificar definitivamente como árvores. Muitos podem ser arbustos ou copas pertencentes a outra árvore.

## Log esperado no `fore-1.smd` com as decisões atuais

```text
PT_V30_BATCH=PASS instances=99 with_trunk=56 foliage_only_unverified=43 wall_candidates_unverified=... original_faces_hidden=4817 residual_material_suspects=... source_unchanged=true game_unchanged=true publish=false
```

**Nem paredes nem folhas residuais são certificadas.** A geometria na parede é uma hipótese da BVH no Blender; o campo `residual_material_suspects` é um diagnóstico, não uma autorização para eliminar faces. A publicação no jogo continua desativada. O projeto original, SMD, materiais, colisões e todos os JSON V22–V29 permanecem intactos.

Informação técnica: `docs/etervale/V30_COBERTURA_FOLHAGEM_PAREDES.md`.
