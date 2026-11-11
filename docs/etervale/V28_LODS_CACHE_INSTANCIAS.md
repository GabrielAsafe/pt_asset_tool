# Etervale V28 — preparação isolada de árvores, LOD e instâncias

## Estado e limites

Implementação **pré-visualização Blender**, sobre a V27; não publica para o jogo.
`Field/forest/fore-1.smd`, texturas, UV, colisões, arquivos baixados e JSONs
V21–V27 são somente leitura. As aprovações de preview continuam no JSON V26.
O importador glTF C# do runtime **não foi modificado**; LODs não são
integrados no MonoGame nesta versão. LODs são bibliotecas Blender `.blend`
para prévia, não artefactos de exportação do cliente.

## Fluxo recomendado

1. Coloca os arquivos Poly Haven originais em `AssetsForAutomaticSubstitution`.
2. Fecha o Blender interativo para libertar memória, principalmente nos modelos pesados.
3. Prepara *um* modelo em background (fora da cena Stage):
   `python3 app/pt_environment.py --prepare-model island_tree_01_1k.blend.zip`
4. Verifica o estado: `python3 app/pt_environment.py --list-lods`.
5. Abre `python3 app/pt_environment.py --map Field/forest/fore-1.smd`.
6. N → Etervale → Modernizar ambiente: escolhe árvore, modelo, LOD (LOD1
   recomendado), **Comparar modelo novo**, ajusta a escala, **Aprovar substituição**.
7. Com pelo menos uma árvore aprovada, escolhe **Instanciar árvores aprovadas**.
   Todas as árvores que partilham o mesmo modelo usam uma biblioteca de malhas.
   O limite por operação é de 100 árvores aprovadas.

Para um teste sem alterações ou antes de instalar:
`python3 app/pt_environment.py --prepare-model island_tree_01_1k.blend.zip --dry-run`

Para preparar todos os modelos de árvore encontrados:
`python3 app/pt_environment.py --prepare-all-models`. Este comando pode
consumir bastante tempo e recursos em modelos difíceis e regista erros
individuais sem apagar os preparos já válidos.

Caso o Flatpak não seja detetado automaticamente, passa:
`--blender-command 'flatpak run org.blender.Blender'`.
Não executar o comando de preparação **dentro** do Blender Flatpak; executar
no terminal normal com o Python do projecto.

## Layout do cache

`app/pt_build/etervale/environment_v28/prepared_models/<sha256>-r1/`

- `LOD0.blend`: até aproximadamente 120 000 faces (inspeção próxima).
- `LOD1.blend`: até aproximadamente 35 000 faces (prévia padrão).
- `LOD2.blend`: até aproximadamente 7 000 faces (prévia distante).
- `manifest.json`: SHA-256 do arquivo de origem, hash por LOD, contagens
  de vértices/faces, dimensões, ausência de texturas e restrições de publicação.

Os limites de faces permitem até 1,5× o alvo devido a topologias com ilhas
pequenas que o modificador Decimate não consegue reduzir de forma adequada.
Se não conseguir cumprir o limite, **não publica** cache parcial e reporta
`V28_LOD_NAO_ATINGE_ORCAMENTO`. Isso é intencional: não apagar folhas
aleatoriamente nem corromper UVs. Nenhuma garantia visual de LOD sem inspeção.

Há um limite de entrada do worker de 8 milhões de vértices, 10 milhões de
faces e 256 objetos para reduzir o risco de esgotamento de memória. O
processo isolado **pode ainda falhar** em máquinas com pouca RAM. Falhas
parciais removem o diretório temporário. O cache já concluído não é alterado.

## Proteção

- Arquivos `.blend.zip` passam pelo extrator seguro da V26, com verificação
  de caminhos, número de entradas, dimensão descomprimida e ficheiros especiais.
- O `.blend` é carregado em `bpy.data.libraries.load` (não abre uma cena
  descarregada nem executa handlers do .blend diretamente). Os GLB usam o
  importador nativo do Blender. Apenas malhas estáticas; sem armatures.
- A geometria é normalizada para base Z=0 numa **cópia temporária**, com
  decimação por LOD. Dependências de materiais/UVs são preservadas na medida
  suportada pelo Blender, mas imagens externas em falta são indicadas.
- Os ficheiros de cache são verificados por hash antes de serem carregados.
  Um cache parcial ou modificado exige intervenção; nunca é sobrescrito em silêncio.
- A lista de árvores continua a usar a âncora proposta pela V24/V25, ainda
  **não certificada em relação ao chão real ou à colisão do cliente**.
- Não existem ações de substituição nativa de SMD, glTF de produção, exportação,
  nem publicação. `publish_enabled=false` e `game_assets_modified=false`.
- A cena com instâncias **não elimina as folhas originais**. É uma comparação
  visual; uma substituição definitiva exigirá máscara e integração no renderer.

## Logs esperados

Preparação CLI (na máquina do utilizador):

```text
PT_V28_WORKER=START source=island_tree_01_1k.blend.zip background=true
PT_V28_PREPARE=PREPARADO model=island_tree_01_1k.blend.zip path=...
  LOD0: ... faces, ... vertices
  LOD1: ... faces, ... vertices
  LOD2: ... faces, ... vertices
```

No Blender:

```text
PT_V28_PREVIEW=PASS group=... model=island_tree_01_1k.blend.zip lod=LOD1 source_unchanged=true publish=false
PT_V28_BATCH=PASS instances=... shared_libraries=... source_unchanged=true publish=false
```

## Testes

`python3 -m pytest -q app/dev_tests/test_etervale_environment_v28.py`

Os testes de protocolo simulam o processo Blender para verificar cache,
segurança de hash, erro e limpeza. Necessitam do teste manual na instalação
Flatpak 5.2 para confirmar compatibilidade das bibliotecas `.blend` geradas
por `bpy.data.libraries.write`, materiais e UVs após Decimate.
