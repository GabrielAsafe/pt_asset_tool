# V32 — Uma seleção, dois destinos

**Requer V31.1.** Fechar o Blender antes de instalar. O patch confere os hashes
locais e cria cópias de segurança. Nenhum asset do jogo é modificado.

## Instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V32_FLUXO_CONCISO_ARVORES_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v32_fluxo.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v32_fluxo.py --project-root "$PWD"
PYTHONPATH=app python3 -m pytest -q app/dev_tests/test_etervale_environment_v32_semantic_actions.py
```

Se houver `SOURCE_FILE_CONFLICT`, **não forçar**: os ficheiros locais são diferentes dos
esperados e têm de ser revistos antes de aplicar a atualização.

## No Blender

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

Painel **N > Etervale > Modernizar ambiente**:

1. Escolhe `island_tree_01_1k.blend.zip` (com LOD0 já preparado na V28.1).
2. Prime **Mostrar floresta (LOD0)**, para ativar a máscara base V30.
3. Prime **Clicar no mapa** e escolhe uma árvore ou folhas antigas.
4. Seleciona alcance **Árvore local** e ajusta o raio, se preciso; confirma o destaque.
5. Para folhas soltas, prime **Só ocultar folhas** (não cria árvore).
   Para uma árvore inteira, prime **Substituir árvore** (oculta faces + cria 1 instância LOD0).
   O botão **Desfazer última** reverte apenas a última escolha V32, sem tocar nas antigas V31.
6. As ações ficam guardadas no JSON V31 existente; depois de reabrir e carregar
   a floresta V30, as substituições V32 são reconstruídas como instâncias partilhadas.

O suporte à parede continua experimental; a base calculada para uma nova árvore
requer revisão visual. Seleções amplas de material não podem criar árvores novas.
A V32 limita o ensaio a **12 árvores extras** para reduzir a carga do Blender.
Seleções V31 já ocultadas antes da V32 ficam ocultas, mas não se transformam
automaticamente em árvores porque não tinham essa intenção guardada.

**Ferramentas avançadas** revela os painéis e operações históricos.
**Restaurar cenário** desfaz a vista; não apaga o JSON. Nas ferramentas avançadas
existe **Reverter seleções V31/V32**, que apaga as correções persistidas adicionais.

## Estado e garantias

- Os JSON V21–V30 e o SMD são preservados.
- As máscaras e as árvores extras V32 são persistidas no mesmo documento V31,
  com verificação do SHA-256 do Stage. Cada ação tem `v32_action`.
- O novo modelo vem exclusivamente de um LOD0 previamente preparado; não se importa
  nenhum original milionário para a sessão do mapa.
- A geometria do Stage original, UVs, colisões e cliente não são editados.
- Apenas pré-visualização: `publish_enabled=false`, sem integração com MonoGame.
- Testes Python e integração estática aprovados; Blender 5.2 com GPU real não
  está disponível neste ambiente e deve ser validado no PC do utilizador.
