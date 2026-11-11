
# Projeto: Pipeline de Modernização Gráfica — Priston Tale + Blender

## Objetivo

Desenvolver uma pipeline automatizada e reproduzível para modernizar os assets gráficos do Priston Tale utilizando Blender, chaiNNer, Real-ESRGAN e ferramentas de processamento de materiais.

O objetivo não é apenas aumentar a resolução das texturas. É investigar se os formatos de assets e o motor gráfico conseguem armazenar, interpretar e renderizar materiais modernos, incluindo Normal, Height, Ambient Occlusion, Roughness, Metallic, Specular e outros mapas PBR.

## 1. Auditoria dos assets e do renderer

- [ ] Identificar os formatos utilizados pelo Priston Tale: SMD, SMB, BMP, TGA, INX e outros.
- [ ] Investigar a estrutura interna dos ficheiros de modelos e materiais.
- [ ] Identificar como os modelos referenciam as texturas.
- [ ] Identificar como são armazenados os UV Maps.
- [ ] Identificar a API gráfica, a versão do Direct3D e as capacidades do renderer.
- [ ] Identificar os shaders e os sistemas de iluminação existentes.
- [ ] Verificar o suporte a texturas de múltiplos canais.
- [ ] Verificar as limitações de resolução, memória e formatos de textura.
- [ ] Identificar o que pode ser alterado apenas nos assets e o que requer alterações ao código do cliente.

### Questões fundamentais

Para cada propriedade gráfica, responder separadamente:

1. O Blender consegue criar e armazenar essa informação?
2. O formato do asset exportado consegue preservá-la?
3. O carregador de assets do Priston Tale consegue recuperá-la?
4. O material e o shader do motor conseguem utilizá-la?
5. O renderer consegue apresentar o efeito visual corretamente?
6. É possível acrescentar suporte sem alterar o formato original do asset?

Importante: guardar os valores nos canais de uma imagem não significa que o motor os interprete como propriedades de material.

## 2. Preparação de texturas

- [ ] Extrair e descodificar as imagens originais.
- [ ] Converter BMP/TGA para PNG ou TIFF durante o processamento.
- [ ] Preservar nomes, caminhos e referências.
- [ ] Analisar os canais RGB e Alpha.
- [ ] Identificar profundidade de bits e espaços de cor.
- [ ] Distinguir imagens sRGB de mapas de dados lineares.
- [ ] Identificar texturas diffuse, máscaras, sprites, interfaces e outros tipos.
- [ ] Detetar texturas repetíveis, atlas e texturas com transparência.
- [ ] Identificar artefactos de compressão e ruído.
- [ ] Preservar backups e metadados originais.

## 3. chaiNNer — processamento automatizado

- [ ] Criar workflows de processamento em lote.
- [ ] Preparar imagens antes do upscale.
- [ ] Implementar denoise e remoção de artefactos.
- [ ] Separar processamento de imagens coloridas e mapas de dados.
- [ ] Preservar os canais Alpha.
- [ ] Controlar nitidez, contraste e resolução.
- [ ] Implementar operações de canais e composição de imagens.
- [ ] Preparar pipelines diferentes conforme os tipos de textura.
- [ ] Automatizar os outputs e a organização dos ficheiros.
- [ ] Registar erros, parâmetros utilizados e versões produzidas.

## 4. Real-ESRGAN — super-resolução

- [ ] Testar diferentes modelos de super-resolução.
- [ ] Comparar escalas 2x e 4x.
- [ ] Avaliar resultados em madeira, metal, pedra, terreno, tecidos e personagens.
- [ ] Preservar os detalhes artísticos originais.
- [ ] Evitar artefactos e detalhes artificiais da IA.
- [ ] Preservar a repetição perfeita das texturas tileable.
- [ ] Verificar alinhamento com os UVs existentes.
- [ ] Evitar aplicar modelos de upscale fotográfico indiscriminadamente a normal maps, máscaras e height maps.
- [ ] Gerar versões otimizadas para as limitações reais do cliente.
- [ ] Comparar o resultado no Blender e no Priston Tale.

## 5. Blender — geometria, UV Maps e materiais

### 5.1. Geometria e UV Mapping

- [ ] Importar os modelos do Priston Tale.
- [ ] Preservar os vértices, faces e topologia.
- [ ] Preservar os UV Maps originais.
- [ ] Verificar UV islands, seams e sobreposições.
- [ ] Avaliar Texel Density.
- [ ] Verificar orientação e escala dos modelos.
- [ ] Verificar normais geométricas e smoothing.
- [ ] Garantir que as novas texturas permanecem alinhadas com os UVs.
- [ ] Verificar suporte a múltiplos UV Maps e materiais.
- [ ] Determinar quando é necessário fazer UV Unwrapping novamente.

### 5.2. Mapas PBR a estudar e implementar

| Mapa | Conceito teórico | Aplicação |
|---|---|---|
| Albedo / Base Color | Cor e refletância de base | Cor do material |
| Diffuse | Cor da componente difusa | Cor no workflow especular |
| Normal | Vetores e orientação da superfície | Relevo aparente |
| Height | Campo escalar de altura | Parallax e deslocamento |
| Ambient Occlusion | Visibilidade e oclusão | Sombreamento em cavidades |
| Roughness | Distribuição das microfacetas | Dispersão dos reflexos |
| Metallic | Condutores e dielétricos | Comportamento metálico |
| Specular | Refletância e resposta angular | Intensidade/cor dos reflexos |
| Glossiness | Concentração dos reflexos | Superfícies lisas ou rugosas |
| Emissive | Emissão de luz | Brilho aparente |
| Opacity / Alpha | Transparência | Áreas translúcidas e recortadas |

Para cada mapa:

- [ ] Aprender o respetivo fundamento físico ou matemático.
- [ ] Configurar a propriedade correspondente no Blender.
- [ ] Identificar os canais e espaços de cor corretos.
- [ ] Verificar se pode ser exportado.
- [ ] Verificar se o formato de asset consegue armazenar uma referência ou os dados necessários.
- [ ] Verificar se o renderer do Priston Tale consegue utilizá-lo.
- [ ] Definir alternativas de baking ou adaptação quando não existir suporte nativo.

### 5.3. Metallic / Roughness Workflow

Investigar a criação de materiais com:

**Base Color + Metallic + Roughness + Normal + AO**

- [ ] Configurar materiais no Principled BSDF do Blender.
- [ ] Entender o papel do mapa Metallic.
- [ ] Entender o funcionamento do Roughness.
- [ ] Estudar Fresnel e a teoria das microfacetas.
- [ ] Verificar a representação de metais e não metais.
- [ ] Investigar se o formato dos assets suporta os parâmetros necessários.
- [ ] Investigar se o renderer suporta shaders baseados em Metallic/Roughness.
- [ ] Determinar se é necessário criar shaders ou estruturas de materiais adicionais.
- [ ] Validar os reflexos em diferentes condições de iluminação.

### 5.4. Specular / Glossiness Workflow

Investigar a criação de materiais com:

**Diffuse + Specular + Glossiness + Normal**

- [ ] Configurar um material de referência no Blender.
- [ ] Entender a diferença entre Specular e Metallic.
- [ ] Investigar como Glossiness controla os reflexos.
- [ ] Analisar a relação aproximada Glossiness = 1 − Roughness.
- [ ] Verificar as diferenças de interpretação entre os dois workflows.
- [ ] Investigar conversões entre Metallic/Roughness e Specular/Glossiness.
- [ ] Determinar qual workflow é mais próximo das capacidades originais do Priston Tale.
- [ ] Determinar se algum deles pode ser implementado no renderer.
- [ ] Criar testes comparativos de materiais.

Nota: a inversão simples entre Roughness e Glossiness nem sempre reproduz exatamente o mesmo material em shaders diferentes.

### 5.5. Height Maps — representação matemática

Um Height Map pode ser representado por uma função escalar:

**h(u,v)**

Em que:

- `u` e `v` representam coordenadas da textura.
- `h` representa a altura relativa da superfície.

Investigar:

- [ ] Como representar funções de altura em imagens.
- [ ] Como interpretar os valores de píxeis como alturas.
- [ ] Como utilizar mapas de 8 e 16 bits.
- [ ] Como gerar height maps procedurais no Blender.
- [ ] Como calcular gradientes e diferenças de altura.
- [ ] Como aplicar Bump Mapping.
- [ ] Como aplicar Parallax Mapping.
- [ ] Como aplicar Displacement Mapping.
- [ ] Distinguir o parallax visual da alteração real de geometria.
- [ ] Verificar se o renderer suporta cada um desses métodos.
- [ ] Investigar modificações necessárias caso não exista suporte.

### 5.6. Normal Maps — representação matemática

Um Normal Map associa a cada posição da textura um vetor tridimensional:

**N = (Nx, Ny, Nz)**

Os componentes representam a orientação da superfície.

Investigar:

- [ ] Vetores tridimensionais.
- [ ] Normalização de vetores.
- [ ] Tangent Space e Object Space.
- [ ] Como codificar vetores nos canais RGB.
- [ ] Como descodificar os valores RGB para vetores.
- [ ] Como calcular normais a partir de height maps.
- [ ] Gradientes e derivadas parciais de funções de altura.
- [ ] Tangentes, bitangentes e convenções dos eixos.
- [ ] Diferenças entre normal maps DirectX e OpenGL.
- [ ] Como configurar o nó Normal Map no Blender.
- [ ] Como fazer baking de normal maps.
- [ ] Como exportar os dados preservando os vetores.
- [ ] Verificar se o renderer interpreta normal maps.
- [ ] Identificar o que seria necessário para implementar normal mapping no motor.

Uma aproximação de normal derivada de um campo de altura, num sistema de coordenadas tangente apropriado, é proporcional a:

**N ∝ (−s ∂h/∂u, −s ∂h/∂v, 1)**

Onde `s` controla a intensidade do relevo. O vetor resultante precisa de ser normalizado e ajustado à convenção de coordenadas utilizada.

## 6. Compatibilidade real entre Blender, assets e renderer

Construir uma matriz experimental de compatibilidade.

| Propriedade | Blender | Asset exportado | Loader | Renderer |
|---|---|---|---|---|
| Base Color | Testar | Verificar | Verificar | Verificar |
| Normal | Testar | Verificar | Verificar | Verificar |
| Height | Testar | Verificar | Verificar | Verificar |
| AO | Testar | Verificar | Verificar | Verificar |
| Roughness | Testar | Verificar | Verificar | Verificar |
| Metallic | Testar | Verificar | Verificar | Verificar |
| Specular | Testar | Verificar | Verificar | Verificar |
| Glossiness | Testar | Verificar | Verificar | Verificar |
| Emissive | Testar | Verificar | Verificar | Verificar |
| Alpha | Testar | Verificar | Verificar | Verificar |

Classificar cada propriedade depois dos testes como:

- Suportada nativamente.
- Suportada mediante conversão.
- Possível através de shader personalizado.
- Exige alterações ao carregador ou formato de material.
- Exige alterações significativas ao renderer.
- Não suportada na configuração analisada.

Investigar também se é viável armazenar mapas adicionais como ficheiros externos, através de convenções de nomes ou de um manifesto de materiais, em vez de modificar diretamente os formatos SMD/SMB.

### Testes de ida e volta

Para cada propriedade:

- [ ] Criar um material controlado no Blender.
- [ ] Exportar o asset.
- [ ] Reimportar o asset e verificar os dados preservados.
- [ ] Carregar o asset no Priston Tale.
- [ ] Confirmar que os dados são realmente utilizados.
- [ ] Variar a iluminação e a posição da câmara.
- [ ] Comparar os resultados visuais.
- [ ] Documentar as diferenças entre Blender e jogo.

## 7. Shaders e fundamentos de renderização

Investigar os seguintes temas:

- [ ] Pipeline gráfica do Direct3D utilizado pelo cliente.
- [ ] Iluminação por vértices e por píxeis.
- [ ] Vertex Shaders e Pixel Shaders, quando suportados.
- [ ] Transformações de coordenadas.
- [ ] Modelos de iluminação Lambert, Phong e Blinn-Phong.
- [ ] BRDF — Bidirectional Reflectance Distribution Function.
- [ ] Reflexão difusa e especular.
- [ ] Fresnel.
- [ ] Conservação de energia.
- [ ] Teoria das microfacetas.
- [ ] Normal Mapping.
- [ ] Parallax Mapping.
- [ ] Transparência e Alpha Blending.
- [ ] Gamma Correction e espaços de cor.
- [ ] Limitações do hardware e da API gráfica.

Objetivo: determinar que funcionalidades podem ser reproduzidas com o renderer existente e quais requerem uma atualização da implementação gráfica.

## 8. Channel Packing e formatos de textura

- [ ] Investigar a possibilidade de guardar vários mapas nos canais RGBA.
- [ ] Definir uma convenção de canais para os materiais.
- [ ] Verificar suporte a canais Alpha e formatos de imagem.
- [ ] Investigar limites de profundidade de bits.
- [ ] Comparar formatos sem perdas e formatos comprimidos.
- [ ] Verificar suporte a mipmaps e filtragem anisotrópica.
- [ ] Investigar como o carregador lê texturas adicionais.
- [ ] Determinar se é necessário modificar os shaders para descodificar canais empacotados.
- [ ] Criar um conversor que preserve os dados dos mapas.
- [ ] Validar se os valores permanecem corretos após exportação.

## 9. Exportação e integração

- [ ] Implementar exportação e conversão para os formatos do jogo.
- [ ] Preservar geometria e UVs.
- [ ] Preservar materiais e referências às texturas.
- [ ] Verificar rigging e animações quando aplicável.
- [ ] Investigar SMD, SMB e INX.
- [ ] Testar integração com PT Asset Tool e outras ferramentas compatíveis.
- [ ] Definir uma estratégia para propriedades que não cabem no formato original.
- [ ] Validar carregamento e renderização no cliente.
- [ ] Preparar fallback para materiais tradicionais.

## 10. Validação e desempenho

- [ ] Comparar assets originais e modernizados.
- [ ] Verificar aparência sob diferentes iluminações.
- [ ] Medir FPS e VRAM.
- [ ] Verificar efeitos de distância e mipmaps.
- [ ] Avaliar o custo de shaders mais complexos.
- [ ] Identificar problemas de transparência.
- [ ] Detetar texturas ausentes ou incorretas.
- [ ] Verificar costuras, UVs e distorções.
- [ ] Construir uma cena de testes com materiais de referência.
- [ ] Implementar testes de regressão.
- [ ] Manter um mecanismo de rollback.

## 11. Arquitetura da pipeline final

Asset original do Priston Tale

→ Extração e descodificação

→ Análise de imagens e materiais

→ Pré-processamento no chaiNNer

→ Upscale com Real-ESRGAN

→ Importação e validação no Blender

→ Preparação dos mapas PBR

→ Conversão para workflow compatível

→ Exportação de geometria, texturas e metadados

→ Adaptação ao formato de materiais do Priston Tale

→ Carregamento pelo cliente

→ Renderização e validação em jogo

→ Otimização e testes de desempenho

Cada etapa deve ser modular, automatizável e reutilizável.

## 12. Entregáveis

1. Inventário dos formatos e das propriedades gráficas do Priston Tale.
2. Matriz de compatibilidade entre Blender, assets, carregador e renderer.
3. Material-base Metallic/Roughness no Blender.
4. Material-base Specular/Glossiness no Blender.
5. Exemplos funcionais de Albedo, Normal, Height, AO, Roughness e Metallic.
6. Scripts de conversão, normalização e channel packing.
7. Workflow chaiNNer reutilizável.
8. Estratégia de upscale com Real-ESRGAN.
9. Exportador ou sistema de metadados de materiais compatível com o jogo.
10. Protótipo de integração gráfica dentro do Priston Tale.
11. Documentação dos shaders e das modificações necessárias.
12. Pipeline de produção em lote com testes automatizados.

## 13. Primeiros experimentos obrigatórios

Antes de desenvolver o sistema completo, executar estes testes:

**Experimento A — Textura**

Substituir uma textura existente por uma versão melhorada. Confirmar resolução máxima, Alpha, filtragem e apresentação visual.

**Experimento B — Material Blender**

Criar um material com Base Color, Metallic, Roughness, Normal e Height. Exportar o modelo e verificar quais os dados realmente preservados.

**Experimento C — Reflexos**

Criar uma cena de teste com metal e pedra, variando Metallic, Roughness, Specular e Glossiness. Determinar quais os efeitos que o renderer consegue apresentar.

**Experimento D — Normal e Height**

Criar uma superfície plana com um normal map e um height map. Testar se o motor consegue mostrar relevo sem modificar a geometria.

**Experimento E — Material estendido**

Investigar a implementação de um shader ou de um sistema externo de definição de materiais para suportar as propriedades atualmente ausentes.

## Instrução para o próximo chat

Quero desenvolver esta pipeline começando por uma auditoria real do formato de assets, do carregador de materiais e do renderer do Priston Tale.

A prioridade é descobrir, com evidência técnica, quais os dados que posso produzir no Blender, quais conseguem ser exportados e quais podem ser efetivamente renderizados pelo cliente.

Não assumir que uma propriedade PBR do Blender existe automaticamente no jogo. Tratar armazenamento, exportação, carregamento e renderização como problemas separados.

Depois, construir os protótipos de forma incremental, começando pelas capacidades existentes e avançando para shaders e materiais modernos.

