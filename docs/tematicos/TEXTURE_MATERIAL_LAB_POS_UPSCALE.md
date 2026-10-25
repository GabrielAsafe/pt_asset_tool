# PT Asset Tool — Material Lab após upscale (Fases 3–6)

**Este fluxo NÃO repete o upscale.** As imagens existentes são tratadas como fonte à resolução final. O objetivo é restauro 1×, mapas de materiais para authoring offline, inspeção de malhas e revisão manual. Toda a escrita fica na workspace. Nem a exportação de normal/parallax para o cliente nem alterações de shaders/meshes estão certificadas neste pacote.

## 1. Preparação e execução

A partir da pasta `app/`:

```bash
# Primeiro, ver capacidades e dependências; não escreve texturas.
python pt_asset.py texture-material capabilities

# Testa UMA textura já ampliada, sem novo upscale, com limpeza leve:
python pt_asset.py texture-material run \
  --input-root /caminho/para/as/texturas-ja-upscaled \
  --include-exact 'Image/Field/stone.tga' \
  --denoise light --maps from-diffuse

# Ou trabalha por lote após validar a amostra. Processa apenas formatos
# reconhecidos pelo projeto, com UI e normal/height excluídos por defeito.
python pt_asset.py texture-material run \
  --input-root /caminho/para/as/texturas-ja-upscaled \
  --all --denoise medium --maps from-diffuse \
  --mesh-root /caminho/para/modelos-original-client
```

Em cada execução, cria-se uma pasta exclusiva em `app/pt_build/texture_material/runs/run_*/` com `manifest.json`, `overlay/` (cópias de texturas codificadas no formato de origem), `maps/` (PNG de normal/height/preview offline), `previews/` e `review_001.html` (eventualmente mais páginas). Nenhuma textura recebe um fator de escala superior a **1×**. O manifesto grava SHA-256, dimensões, risco, alterações RGB, material atribuído, modelo usado, falhas, tipo de mapa, aprovação pendente e ausência de escrita na origem.

**ATENÇÃO:** um DEDXT 1× foi treinado para artefactos específicos de texturas de jogos e nem sempre reverte efeitos de uma ampliação IA anterior; o fluxo ideal para o máximo de qualidade seria DEDXT antes do upscale, mas isso implicaria repetir o trabalho. Por isso o padrão aqui é `--denoise off`, com teste visual local antes de usar `light`, `medium` ou IA.

## 2. AI real: modelos especializados, sem pesos incluídos

Use modelos 1× de restauro DXT como [DEDXT](https://openmodeldb.info/models/1x-DEDXT), e **não** modelos fotográficos 4×. O motor de restauro integrado suporta:

- `spandrel`: `.pth` suportados pelo [Spandrel](https://github.com/chaiNNer-org/spandrel), em subprocesso, por mosaicos, exigindo 1×, SHA-256 dos pesos e instalação opcional de PyTorch 2.6+ (`pip install 'torch>=2.6' spandrel packaging`). A arquitetura do modelo é reconhecida pelo Spandrel; nem todos os pesos têm suporte. Execute pesos de terceiros apenas num ambiente isolado de confiança.
- `external`: executável/CLI de restauro especializado ou cadeia do chaiNNer já preparada, com `argv` como lista de argumentos, **sem shell**. O executável recebe caminhos `{input}`, `{output}`, `{model}` e TEM de criar output PNG de dimensão idêntica; recusamos o resultado se fizer upscale. A versão CLI do chaiNNer pode mudar, por isso a configuração específica depende da versão instalada.

Copie `docs/tematicos/texture_model_profiles.example.json` e substitua o nome/caminho do peso e o seu SHA-256 real. Exemplos de modelos e características estão em OpenModelDB; o pacote não descarrega nem inclui pesos.

```bash
sha256sum /caminho/modelos/1x_DEDXT.pth
python pt_asset.py texture-material run \
  --input-root /caminho/texturas-ja-upscaled \
  --include-exact 'Image/Field/stone.tga' \
  --denoise ai --model-config /caminho/models.json --maps from-diffuse
```

O mapeamento de materiais por palavras-chave é apenas uma **proposta heurística**; para rigor use `material_overrides` em configuração. O pipeline nunca interpreta automaticamente uma máscara, uma cor escura ou a transparência como relevo real. O alpha das texturas RGBA e a cor-chave preta dos BMP são preservados.

## 3. Normal maps, height maps e parallax

`--maps from-diffuse` estima altura via luminância e gera duas variantes de normais (DirectX e OpenGL com verde invertido), mais um preview de deslocamento oblíquo. É **estimativa**, não bake geométrico. Fendas escurecidas pela iluminação podem ficar falsas. A opção recomendada quando existir height pintado à mão é:

```bash
python pt_asset.py texture-material run \
  --input-root /caminho/texturas-ja-upscaled \
  --include-exact 'Image/Field/stone.png' \
  --maps from-height --height-root /caminho/height-autorais
```

Procura `stone_height.png`, `stone_h.png`, `stone.height.png`, etc., no mesmo subcaminho; os mapas de altura precisam de dimensão **idêntica** à textura atual. O preview `parallax_demo` desloca pixels apenas para avaliação artística; **não é efeito 3D em jogo**. Os mapas gerados não são colocados automaticamente na overlay do cliente. Em PT DX8/DX9 fixed-function não basta entregar um ficheiro `_n` ou `_height` para obter normal/parallax; é preciso programar e testar suporte de material/shader no cliente específico.

## 4. Mesh fixes

```bash
python pt_asset.py texture-material mesh-audit --mesh-root /caminho/cliente/Image --output /tmp/mesh_review.json
```

Os `.smd` Model 0.62 suportados são inspecionados sem escrita e produzem contagens de faces, vértices, objetos e texlinks e sugestões de revisão. Outras variantes ficam `UNSUPPORTED_OR_INVALID_SMD` até usar o respetivo parser certificado do projeto. Não se afirma ter corrigido UVs, costuras, sombras ou topologia só por fazer esse inventário.

Para modelos já importados na workspace do Blender, a ferramenta adicional `texture_mesh_fix_blender.py` aplica, **num `.blend` novo**, normalização de orientação de faces ou smooth-shading sem alterar posições, UVs ou topologia:

```bash
blender --background --disable-autoexec \
  --python pt_asset_tool/texture_mesh_fix_blender.py -- \
  --input /caminho/original_workspace.blend \
  --output /caminho/staging/model_lighting.blend \
  --mode recalc-normals
```

Requer Blender; a execução não foi comprovada nesta distribuição. A saída tem um manifesto `.meshfix.json` e **não** é uma malha SMD publicada. Para exportar/aplicar no jogo, use apenas o caminho de exportação, comparação, validação e rollback já certificado do PT Asset Tool. Bevels, subdivisões, remesh ou UV unwrap podem quebrar animações e índices e não estão automatizados.

## 5. Aprovação humana e verificação

Abra `review_001.html` no browser. Compare antes/depois e aceda aos mapas offline. Marque `Aprovar` ou `Rejeitar`, exporte `material-reviews.json`; cada página exporta as próprias decisões. Depois:

```bash
python pt_asset.py texture-material review-import \
  --manifest /caminho/pt_build/texture_material/runs/run_XXX/manifest.json \
  --decisions /caminho/material-reviews.json

python pt_asset.py texture-material audit \
  --manifest /caminho/pt_build/texture_material/runs/run_XXX/manifest.json
```

A aprovação está ligada ao SHA-256 do output e deixa de ser válida se o ficheiro mudar; os mapas também são verificados por hash. Contudo, a verificação continua a retornar `client_publish_authorized: false`, mesmo após aprovar todas as imagens. Isto é intencional: **aprovação visual não prova suporte de shader/parallax nem compatibilidade de malha no motor**. A publicação deverá ser desbloqueada num contrato de renderer e num teste real do cliente, inexistentes nos ficheiros fornecidos.

## 6. Auditoria reforçada, métricas e bundle de candidatos

Os runs agora gravam `quality` por textura (percentagem de pixels RGB alterados,
erro absoluto médio, preservação do alpha, diferença entre bordas) e um
`preview_difference` visual com regiões alteradas realçadas. São testemunhos
de comparação, não um classificador de qualidade nem uma prova de costuras.

`texture-material audit` volta a verificar **todos os hashes de entrada**,
os hashes do overlay e de todos os mapas, o estado de execução, as aprovações,
e bloqueia candidatas alteradas desde o processamento. Quando a auditoria
retorna `offline_candidate_ready: true` podes usar **exclusivamente para testes**:

```bash
python pt_asset.py texture-material export-approved \
  --manifest /CAMINHO/run_XXX/manifest.json \
  --output-root /CAMINHO_EXTERNO/pacote_teste_01
```

A pasta de saída tem de ser nova e fora do projeto/cliente/origens. Contém
`candidates/`, `maps/` e `OFFLINE_REVIEW_BUNDLE.json`. Não há integração
com slots/shaders do cliente, e continua a declarar
`may_publish_to_client: false`. Se a origem já não estiver acessível, o
pipeline falha fechado; mantém uma cópia das texturas já ampliadas até
terminares a auditoria. Ver também
`MATERIAL_LAB_GUIA_FINAL_PATCH_CUMULATIVO.md`.

## 7. Estados efetivos e limitações

| Área | Preparado no código | O que falta para funcionar no jogo |
| --- | --- | --- |
| Limpeza de artefactos DXT via IA | Adaptador real 1×, verificações por hash/dimensão, roteamento por material | Instalar pesos e dependências compatíveis; validar qualidade no conteúdo real |
| Modelos de IA por material | Configuração e presets/overrides seguros | Selecionar e avaliar pesos adequados |
| Normal maps | Geração offline DX/GL e correção de normais nomeadas | Autorizar slots/shaders no cliente e verificar orientação |
| Height/Parallax | Height e demonstração offline; fontes de height autorais | Implementar e certificar shaders/materiais do motor; não existe aqui geometria falsa em runtime |
| Mesh fixes | Auditoria SMD, correção conservadora de iluminação em `.blend` separado | Blender disponível, revisão, exportação certificada para formatos PT, teste real |
| Curadoria manual | Galeria antes/depois e importação de decisões ligadas a hash | Aprovar visualmente cada textura em execução real |

**Não usar a ação antiga de upscale em lote para este objetivo.** Enquanto o pipeline não for comprovado com o cliente e pesos reais, preserve a instalação e as texturas já upscaled.
