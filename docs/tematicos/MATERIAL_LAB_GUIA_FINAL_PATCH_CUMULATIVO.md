# PT Asset Tool — Material Lab: guia de instalação e utilização (patch cumulativo)

**Âmbito e limitação real:** Este patch cumulativo aplica-se ao ZIP base original `pt_asset_tool-main1(2).zip`, não exige patches intermédios e **NÃO volta a fazer upscale**. Implementa preparação/restauro 1×, mapas de materiais **offline**, análise de meshes, diagnóstico visual e aprovação ligada a hashes. Não inclui pesos de IA nem código-fonte/contratos do shader do teu cliente Priston Tale. A execução real de normal/parallax e correções de meshes dentro do motor continua **NÃO CERTIFICADA**. Nunca aplicar estes mapas ou meshes diretamente no cliente só porque foram gerados. O fluxo de publicação do Material Lab continua fechado por defeito.

## A. Instalar patch cumulativo numa cópia limpa (recomendado)

1. Faz backup do projeto e, separadamente, do cliente/jogo e das texturas já ampliadas. Não coloques o cliente dentro da pasta do patch.
2. Extrai a **versão base original** para uma pasta de trabalho, ficando `.../pt_asset_tool-main/README.md` e `.../pt_asset_tool-main/app/pt_asset.py`.
3. Extrai o `pt_asset_tool_PATCH_CUMULATIVO.zip` para outra pasta. Evita misturar diretamente os conteúdos.
4. Executa num terminal a partir da pasta do instalador (requer Python 3):

```bash
python install_patch.py --target '/CAMINHO/pt_asset_tool-main' --check
python install_patch.py --target '/CAMINHO/pt_asset_tool-main' --apply
```

Em Windows (PowerShell), substitui caminhos e usa `py -3 install_patch.py ...`. O instalador verifica **SHA-256 de cada ficheiro original alterado** e recusa versões inesperadas ou ficheiros já alterados. Faz backup dos ficheiros substituídos numa pasta irmã com instruções de reversão, antes de modificar. Não aplica alterações ao cliente ou às texturas. Se o projeto tiver modificações tuas, não forces: recupera a base limpa e compara primeiro.

5. Verifica a instalação a partir da raiz do projeto:

```bash
bash VERIFY_PACKAGE.sh
cd app
python -m pip install -r requirements.txt
python pt_asset.py texture-material capabilities
python -m pytest -q dev_tests/test_texture_material_pipeline.py dev_tests/test_texture_material_finalization.py
```

O `bash` é necessário para o script de verificação, mesmo em Windows (Git Bash ou WSL). Os testes exigem `python -m pip install -r requirements-dev.txt`. A interface gráfica/web existente continua a funcionar; o Material Lab aparece na zona **Client / Enrichment → Texture Enhancement → Material Lab** e apresenta um link para a galeria após o trabalho.

**Alternativa para quem usa Git:** O ficheiro `.patch` acompanha a mesma diferença cumulativa relativamente à base. Na raiz do projeto base, `git apply --check /CAMINHO/pt_asset_tool_PATCH_CUMULATIVO.patch` e, se passar, `git apply /CAMINHO/pt_asset_tool_PATCH_CUMULATIVO.patch`. O instalador com hashes/backups é mais seguro quando a pasta não é um repositório Git.

## B. Nunca confundir restauro com upscale

- `texture-upscale` / Real-ESRGAN 4×: **não executar novamente** nas texturas já tratadas.
- `texture-material run`: lê as imagens já ampliadas, trabalha **1×** e produz candidatos numa workspace nova.
- `--denoise off` (padrão): mantém os bytes originais no candidato. Serve para preparar mapas/comparação.
- `--denoise light|medium`: limpeza conservadora de RGB, **não é IA** e pode apagar detalhes; compara antes de aceitar.
- `--denoise ai`: modelo especializado **1×** por material. Sem pesos válidos e configuração, falha de forma explícita; não muda silenciosamente para outro modelo.
- `--maps from-diffuse`: altura estimada por luminância e normais DX/GL; **aproximação artística**.
- `--maps from-height`: prefere heights feitos/retocados manualmente (mesma resolução).

## C. Fazer UMA amostra primeiro, sem tocar no jogo

A partir de `app/` (usa aspas em caminhos com espaços):

```bash
python pt_asset.py texture-material run \
  --input-root '/CAMINHO/texturas_ja_upscaled' \
  --include-exact 'Image/Field/stone.tga' \
  --denoise light --maps from-diffuse
```

Substitui `Image/Field/stone.tga` por um caminho **existente, relativo** à tua pasta de entrada. O programa imprime o caminho exato do `manifest.json` e da `review_001.html`. Se a pasta das texturas é a do cliente, o programa só **lê**, não publica ou substitui imagens. Para máxima segurança usa uma cópia das texturas numa pasta separada.

Abre `review_001.html` no browser, examina antes/depois, mapa de diferenças (vermelho = magnitude da alteração), mapas de altura e normais. Os indicadores `pixel_change_percent`, `rgb_mean_absolute_error_255` e diferenças entre bordas são úteis para encontrar casos problemáticos, mas **não são medidores automáticos de qualidade**; as métricas RGB são amostradas até 768 px para poupar RAM; bordas diferentes não significam costura visível quando a textura não é repetível (*tileable*).

### Tratamento em lote (apenas depois de validar a amostra)

```bash
python pt_asset.py texture-material run \
  --input-root '/CAMINHO/texturas_ja_upscaled' \
  --all --denoise off --maps from-diffuse
```

Por defeito o pipeline exclui suspeitas de normal/height e UI/atlas (estes últimos têm risco elevado de transparência e coordenadas de sprite). As opções `--include-ui` e `--include-technical` só devem ser usadas conscientemente e em lotes controlados. **Nunca uses `--all` como primeira experiência numa instalação real.** Verifica o espaço livre antes de processar milhares de ficheiros.

### IA DEDXT 1× (opcional, exige pesos separados)

O [DEDXT 1×](https://openmodeldb.info/models/1x-DEDXT) é um modelo ESRGAN de restauro de compressão DXT. O patch não o inclui. Instala num ambiente Python confiável:

```bash
python -m pip install 'torch>=2.6' spandrel packaging
```

Configura `docs/tematicos/texture_model_profiles.example.json` numa cópia `models.json` com caminho verdadeiro do `.pth` e hash SHA-256 calculado localmente:

```bash
sha256sum '/CAMINHO/1x_DEDXT.pth'
python pt_asset.py texture-material capabilities --model-config '/CAMINHO/models.json'
python pt_asset.py texture-material run \
  --input-root '/CAMINHO/texturas_ja_upscaled' \
  --include-exact 'Image/Field/stone.tga' \
  --denoise ai --model-config '/CAMINHO/models.json' --maps from-diffuse
```

No Windows calcula o hash com `Get-FileHash 'C:\\CAMINHO\\1x_DEDXT.pth' -Algorithm SHA256`. O `.pth` deve ser obtido de fonte considerada fiável; carregar pesos externos de PyTorch pode representar risco. **DEDXT foi treinado para remover blocos DXT, não garante melhoria em imagens que já passaram por 4× IA**. A seleção por material usa heurísticas e overrides configuráveis; valida individualmente.

## D. Aprovação, auditoria e exportação offline

Na galeria, escolhe `Aprovar`/`Rejeitar` para cada imagem e clica `Exportar decisões desta página (JSON)`. Se há muitas páginas, importa cada JSON separadamente (o sistema agrega por nome e hash):

```bash
python pt_asset.py texture-material review-import \
  --manifest '/CAMINHO/run_.../manifest.json' \
  --decisions '/CAMINHO/material-reviews.json'

python pt_asset.py texture-material audit \
  --manifest '/CAMINHO/run_.../manifest.json'
```

A auditoria exige: run completo sem falhas, ficheiros de origem ainda idênticos, candidatos e mapas com SHA-256 válido e **todas** as candidatas aprovadas. Se mudar a fonte depois do processamento, as aprovações deixam de desbloquear a exportação. Se a pasta de origem já não existir, a auditoria bloqueia até estar disponível novamente.

Quando `offline_candidate_ready` for `true`, podes criar um conjunto **separado para testes de integração**:

```bash
python pt_asset.py texture-material export-approved \
  --manifest '/CAMINHO/run_.../manifest.json' \
  --output-root '/CAMINHO/EXTERNO/material_lab_revisao_01'
```

`--output-root` tem de ser uma pasta nova **fora do projeto, das origens e do run**, e não deve apontar para a instalação do cliente. A saída contém `candidates/` (ficheiros no formato de origem), `maps/` (mapas offline) e `OFFLINE_REVIEW_BUNDLE.json` com hashes. **Não é um pacote aplicável automaticamente ao jogo**: os ficheiros de mapas têm nomes de trabalho, não slots certificados de material.

### Reverter o patch

Segue as instruções geradas pelo instalador na pasta de backup. Exemplo:

```bash
python install_patch.py --target '/CAMINHO/pt_asset_tool-main' \
  --rollback '/CAMINHO/.pt_asset_tool_patch_backups/backup_...'
```

Reversão recusa ficheiros editados depois da aplicação, para não destruir alterações do utilizador. Os teus ficheiros do jogo continuam fora deste fluxo.

## E. Meshes, normal maps e parallax em tempo real

```bash
python pt_asset.py texture-material mesh-audit \
  --mesh-root '/CAMINHO/cliente/Image' \
  --output '/CAMINHO_EXTERNO/relatorio_meshes.json'
```

O relatório observa a estrutura SMD que o parser suporta; **não altera nem corrige automaticamente a geometria do cliente**. É possível preparar ajustes de iluminação numa cópia `.blend` com Blender, segundo `TEXTURE_MATERIAL_LAB_POS_UPSCALE.md`.

**Gates de integração ainda por satisfazer antes de um “100% no jogo”:**

1. **Pesos testados**: possuir `.pth`/modelo real, hash verificado e comparação lado a lado em texturas reais já ampliadas, com aprovação artística.
2. **Shader e material do cliente**: acesso ao código/renderizador, identificar API (DX8/DX9), normal convention e slots/múltiplas texturas; implementar amostragem de height/normal e testar sob luz dinâmica e câmaras oblíquas.
3. **Meshes**: paridade de import/export, tangent space, UV, skins/animações e compatibilidade de SMD 0.62/0.72, com teste dentro do motor e rollback real.
4. **Aceitação in-game**: capturas A/B da mesma cena, luz e distância; verificar costuras, brilho, transparência, performance/VRAM, DX mode e fallback; autorizar separadamente qualquer publicação.

Não foram fornecidos pesos, texturas já ampliadas para avaliação artística, fontes do renderizador ou uma instalação executável do cliente para testes. Portanto **as ferramentas offline estão implementadas; os efeitos de parallax/normal/mesh no runtime NÃO foram entregues nem certificados**. O programa mantém `client_publish_authorized: false` e não inventa compatibilidade.

## F. Problemas comuns

| Mensagem | Como resolver |
|---|---|
| `AI_MODEL_NOT_CONFIGURED` | Indica `--model-config` e material/modelo compatíveis (1×). |
| `MODEL_SHA256_MISMATCH` | Recalcula o SHA-256 e confirma que o peso veio da fonte pretendida; não desativa a verificação. |
| `AI_RESTORER_CHANGED_DIMENSIONS` | Modelo 2×/4× ou comando errado; usa exclusivamente 1×. |
| `SOURCE_CHANGED_SINCE_RUN` | Origem já não corresponde ao manifesto; cria novo run com a origem atual e volta a aprovar. |
| `MATERIAL_MAP_DRIFT` | O PNG gerado foi modificado; executa de novo para gerar hash/proveniência atual. |
| `AWAITING_OR_REJECTED_REVIEW` | Falta aprovação, ou houve rejeição; revê visualmente antes de exportar. |
| `AUDIT_BLOCKED_EXPORT` | Há fonte alterada, falha no run, mapas alterados ou revisões por concluir. |
| `REVIEW_EXPORT_MUST_BE_DISJOINT` | Escolhe pasta externa ao projeto/cliente/run, ainda não existente. |
| `RUN_DESTINATION_ALREADY_EXISTS` | Escolhe novo `--output-root`; runs são imutáveis, não sobrescritos. |
| `OUTPUT_MUST_BE_DISJOINT_FROM_INPUT` | Nunca apontes a saída para a pasta de texturas de entrada. |

Ver também `docs/tematicos/TEXTURE_UPSCALE_PIPELINE.md`, `docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md` e `docs/en/topics/TEXTURE_MATERIAL_LAB_POST_UPSCALE.md`.
