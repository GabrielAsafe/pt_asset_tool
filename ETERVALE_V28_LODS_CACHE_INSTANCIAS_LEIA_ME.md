# ETERVALE V28 — LODs em background e árvores instanciadas

Requer a V27 instalada e sem modificações locais nos dois scripts atualizados.
A V28 não contém SMD nem muda o cliente MonoGame. Preserva todos os JSON e backups.

## Instalar

Fecha o Blender e, no terminal:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V28_LODS_CACHE_INSTANCIAS_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v28_lods.py --project-root "$PWD" --dry-run
```

Se não houver `SOURCE_FILE_CONFLICT`:

```bash
python3 patches/aplicar_etervale_v28_lods.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_environment_v28.py
```

## Preparar um modelo pesado antes de abrir o mapa

```bash
python3 app/pt_environment.py --inventory
python3 app/pt_environment.py \
  --prepare-model island_tree_01_1k.blend.zip --dry-run
python3 app/pt_environment.py \
  --prepare-model island_tree_01_1k.blend.zip
python3 app/pt_environment.py --list-lods
```

Se não detetar o Blender Flatpak automaticamente, acrescenta ao comando
`--blender-command 'flatpak run org.blender.Blender'`.

Não introduzir `tree_bark_03_1k.blend.zip` como árvore; é material PBR.
Cada modelo é processado isoladamente, uma única vez por SHA do arquivo, com
LOD0 (perto), LOD1 (médio, padrão) e LOD2 (longe). Em caso de erro o cache
parcial é eliminado e o original baixado mantém-se intacto.

## Blender

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

Em **N → Etervale → Modernizar ambiente**:

1. Selecionar uma árvore existente.
2. Selecionar `island_tree_01_1k.blend.zip` e LOD1.
3. Clicar **2. Comparar modelo novo**.
4. Ajustar escala e **3. Aprovar substituição**.
5. Para várias árvores já aprovadas: **Instanciar árvores aprovadas**.
6. **Restaurar vista** limpa instâncias e bibliotecas temporárias.

Aprovar uma pré-visualização não é publicar no jogo. Nenhuma folha é removida
automaticamente da malha original. Limite de 100 instâncias por operação.

## Onde ficam os LODs

`app/pt_build/etervale/environment_v28/prepared_models/`.

## Diagnóstico

- `V28_MODELO_NAO_PREPARADO`: executar `--prepare-model` com o nome exato.
- `V28_LOD_NAO_ATINGE_ORCAMENTO`: a topologia não permitiu reduzir para o
  número de faces desejado; não usar a fonte pesada na cena principal.
- `V28_CACHE_SHA256_INVALIDO`: cache alterada; preservada para análise.
- `V28_BLENDER_WORKER_FAIL`: erro no processo isolado; rever as últimas linhas.
- `PT_V28_TEXTURES=REVIEW`: material tem imagens externas em falta.

Mais informação: `docs/etervale/V28_LODS_CACHE_INSTANCIAS.md`.
