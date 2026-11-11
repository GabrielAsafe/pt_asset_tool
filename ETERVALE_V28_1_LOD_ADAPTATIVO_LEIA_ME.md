# ETERVALE V28.1 — LOD ADAPTATIVO (HOTFIX)

Corrige o erro observado na preparação de `island_tree_01_1k.blend.zip`:
`V28_LOD_NAO_ATINGE_ORCAMENTO:LOD0:190310/120000`.

A V28.1 mede as faces efetivamente produzidas pelo Blender e, se necessário,
repete a simplificação até 7 vezes. Mantém um limite de segurança de 150%
do orçamento por LOD. Não elimina objetos/folhas para forçar resultados.

## Instalar em cima da V28 (fecha o Blender)

```sh
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V28_1_LOD_ADAPTATIVO_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v28_1_lod_adaptativo.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v28_1_lod_adaptativo.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_environment_v28_1_adaptive.py
```

O instalador verifica os hashes da V28, recusa alterações locais inesperadas
(`SOURCE_FILE_CONFLICT`) e guarda backup antes de substituir ficheiros.

## Repetir o modelo que falhou

```sh
python3 app/pt_environment.py --prepare-model island_tree_01_1k.blend.zip
python3 app/pt_environment.py --list-lods
```

Se o Blender Flatpak não for encontrado:

```sh
python3 app/pt_environment.py --prepare-model island_tree_01_1k.blend.zip \
  --blender-command 'flatpak run org.blender.Blender'
```

Esperado: `PT_V28_PREPARE=PREPARADO` e três níveis `LOD0`, `LOD1`, `LOD2`
com contagem de faces, `quality` e `passes`. Quando `quality=OVER_TARGET_REVIEW`,
é apenas um preview acima do objetivo, ainda dentro do teto de segurança.

Se aparecer novamente `V28_LOD_NAO_ATINGE_ORCAMENTO` após 7 passagens,
o modelo é demasiado fragmentado para esta simplificação com preservação de
UVs: enviar o novo log para uma estratégia de otimização específica.

## Segurança

Não altera `AssetsForAutomaticSubstitution`, SMD, cliente, colisões, texturas
originais ou JSON V21–V27. Os resultados ficam em `app/pt_build` e são
exclusivamente destinados à pré-visualização no Blender.

Blender Flatpak 5.2 com o teu ficheiro real não pôde ser executado neste ambiente.
A correção passou nos testes Python, mas exige confirmação com o teu modelo.
