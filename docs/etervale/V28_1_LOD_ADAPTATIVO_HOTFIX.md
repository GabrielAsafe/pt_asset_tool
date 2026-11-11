# Etervale V28.1 — hotfix de LOD adaptativo

## Erro real a corrigir

O Blender Flatpak 5.2 processou `island_tree_01_1k.blend.zip`, mas V28
interrompeu no LOD0 após uma só passagem:

```
ValueError: V28_LOD_NAO_ATINGE_ORCAMENTO:LOD0:190310/120000
```

O fator do modificador Decimate funciona **por malha** e não garante que o total
de polígonos após avaliação seja igual ao orçamento de toda a árvore. Modelos
com folhas em muitos componentes podem conservar mais polígonos que o previsto.

## Ajuste implementado

- A preparação continua isolada num Blender `--background`, sem Stage e com
  modelo-fonte apenas em leitura.
- Cada LOD (`LOD0=120000`, `LOD1=35000`, `LOD2=7000`) é gerado a partir de cópias
  privadas da fonte, para evitar sucessivas reduções a partir de outros LODs.
- Após cada passagem, **conta as faces efetivas** e recalcula o fator para a
  passagem seguinte. Máximo de **sete passagens por LOD**.
- Pequenas peças de até 12 faces não são destruídas deliberadamente para
  atingir uma contagem: podem ser cartões de folhas.
- Preserva camadas de dados/UV e slots de material ao produzir malhas
  avaliadas do modificador.
- Se o LOD ficar acima do objetivo mas **no máximo em 150%** do orçamento,
  passa para preview com `quality=OVER_TARGET_REVIEW` (nunca publicação).
- Acima de 150%, mantém a falha segura, com diagnóstico de passagens e sem
  criar uma cache incompleta. Nunca apaga folhas ou tronco arbitrariamente.
- Os ficheiros `.blend.zip` em `AssetsForAutomaticSubstitution` ficam intactos.
- Caches V28 já válidas (`r1`) continuam reconhecidas, sem regeneração.
- As classificações V21–V27 e o SMD não são tocados pelo worker.

## Aplicação

Fechar Blender interativo. Instalar o hotfix incremental V28.1. Executar:

```
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_environment.py --prepare-model island_tree_01_1k.blend.zip
python3 app/pt_environment.py --list-lods
```

Em caso de falha para um modelo extremamente fragmentado, procurar o código
`V28_LOD_NAO_ATINGE_ORCAMENTO` e o registo `passes=`. Não aumentar cegamente
limites de entrada nem publicar LODs de Blender no motor do jogo.

## Validação

Testes Python simulam o orçamento e o protocolo worker/manifesto. Não substituem
um teste real do `Decimate` do Blender 5.2 com o `.blend.zip` do utilizador,
que não foi disponibilizado para este teste. Os limites de publicação do
renderer MonoGame continuam por definir; estes são apenas LODs de preview.
