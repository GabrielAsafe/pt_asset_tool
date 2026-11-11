# ETERVALE V31 — Selecionar e substituir as folhas que sobraram

Hotfix incremental sobre **V30**. Fechar o Blender antes de aplicar.

## Instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V31_SELECAO_FOLHAS_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v31_residuais.py --project-root "$PWD" --dry-run
```

Se o dry-run terminar sem `SOURCE_FILE_CONFLICT`:

```bash
python3 patches/aplicar_etervale_v31_residuais.py --project-root "$PWD"
PYTHONPATH=app python3 -m pytest -q app/dev_tests/test_etervale_environment_v31_residual.py
```

## Testar no Blender

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

1. Em **N → Etervale → Modernizar ambiente**, executar primeiro **V30 → Testar todos grupos LOD0 (rever)**, com *Ocultar árvores antigas* ligado.
2. Abrir **V31 · Selecionar folhas restantes**.
3. Clicar **1. Clicar na face restante**, e clicar numa folha antiga **dentro da janela 3D**.
4. Experimentar **Ilha do material**, **Árvore local** (raio 3), **Textura inteira** ou **Folhagem inteira**, e premir **2. Mostrar seleção** para comparar.
5. Se apenas as faces certas estiverem destacadas, clicar **3. Ocultar selecionadas (reversível)** e confirmar. A V30 mantém as instâncias novas já colocadas.
6. Se a região for realmente outra árvore que não recebeu modelo 3D, é possível usar **Árvore extra LOD0 aqui**. A localização e o apoio na parede são aproximados: verificar e ajustar manualmente.
7. Para desfazer só a correção, **Reverter máscaras extra V31**; para desligar todas as instâncias, **Restaurar árvores antigas**.

O JSON V31 mantém as faces extras e é reaplicado quando repetes V30. A operação **não altera o jogo** nem os SMD, e não cria aprovações para runtime. Os 1.565 suspeitos do V30 podem incluir arbustos ou outras superfícies; não ocultar tudo sem inspecionar.

Log pretendido após clicar numa face e confirmar:

```text
PT_V31_PICK=PASS seed=... scope=ARVORE_LOCAL faces=... publish=false
PT_V31_MASK=PASS added=... saved_extra=... source_unchanged=true game_unchanged=true publish=false
```

Se houver `SOURCE_FILE_CONFLICT`, não usar `unzip` para forçar alterações no código — manda o log do instalador. Este hotfix foi gerado sobre o script V30 original, sem alterações locais.

Detalhes: `docs/etervale/V31_SELECAO_FOLHAGEM_RESIDUAL.md`.
