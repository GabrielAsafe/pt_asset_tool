# PT Asset Tool — DEDXT 1× via NCNN/Vulkan (patch aditivo)

Este patch foi preparado a partir dos **6 ficheiros Python fornecidos pelo utilizador**. Não inclui nem altera o `.pth`, os pesos `.param/.bin`, as texturas do cliente, o motor gráfico ou o shader. Acrescenta `engine: "ncnn_vulkan"` ao Material Lab e cria `app/pt_asset_tool/texture_ncnn_runner.py`, mantendo `spandrel` e `external`.

## Instalação no Fedora do utilizador

1. Guardar **apenas** `PT_ASSET_GPU_NCNN_V1.patch` na pasta `~/Transferências` (ou ajustar o caminho abaixo). O patch já acrescenta os outros dois ficheiros ao repositório.
2. No terminal:

```bash
cd ~/Transferências/pt_asset_tool
# Verifique que é o mesmo checkout, sem alterações inesperadas:
git apply --check ~/Transferências/PT_ASSET_GPU_NCNN_V1.patch
git apply ~/Transferências/PT_ASSET_GPU_NCNN_V1.patch
# Cria configuração SHA-256 usando os modelos convertidos já existentes:
bash PT_ASSET_GPU_GERAR_CONFIG.sh
```

3. Fazer diagnóstico (o primeiro comando é somente leitura):

```bash
cd ~/Transferências/pt_asset_tool/app
export PYTHONDONTWRITEBYTECODE=1
CONFIG="$HOME/Transferências/modelos/dedxt_ncnn/dedxt_gpu_material_lab.json"
python3 pt_asset.py texture-material capabilities --model-config "$CONFIG"
```

4. Primeiro teste ponta-a-ponta: **uma textura**, sem novo upscale, fora do cliente:

```bash
CLIENT="$HOME/Área de Trabalho/summit/cliente"
OUTPUT="$HOME/Transferências/material_lab_gpu_integrado_$(date +%Y%m%d_%H%M%S)"
python3 pt_asset.py texture-material run \
    --input-root "$CLIENT" \
    --output-root "$OUTPUT" \
    --model-config "$CONFIG" \
    --profile safe-game-v1 \
    --maps off \
    --include-exact 'Field/Boss/stone_01.bmp' \
    --checkpoint-every 1
printf 'GALERIA: %s/review_001.html\n' "$OUTPUT"
```

Aguardar `"staged": 1` e código de saída zero. Abrir a galeria por `python3 -m http.server 8123 --bind 127.0.0.1 --directory "$OUTPUT"` e, noutro separador, `http://127.0.0.1:8123/review_001.html`. Não distribuir automaticamente: a aprovação manual mantém-se obrigatória. Depois pode escolher novas paredes/chão aprováveis com `--include-exact` repetido.

## Proteções

- Modelo `.param` e `.bin` verificados por SHA-256 tanto no pipeline como no runner.
- Usa o Python 3.11 interno do chaiNNer e **apenas** o runtime `ncnn==1.0.20261020` fornecido pelo utilizador na pasta `runtime_ncnn_20261020`, sem modificar o Python do PT Asset Tool.
- Bloqueia o dispositivo de software `llvmpipe`; requer GPU Vulkan efetiva. Mantém dimensão 1×, RGB e canais alpha/colorkey sob os guardas originais do Material Lab.
- Processa tiles de 256 com halo de 24 e preenchimento reflect (reproduz o piloto visualmente aprovado). Imagem de entrada somente leitura; output entregue ao pipeline como PNG temporário para ser codificado pelo codec já existente.
- Cache opcional `~/Transferências/material_lab_gpu_tile_cache` fora do cliente, com assinatura da entrada, pesos, parâmetros, runtime e identificador GPU. Reutiliza tiles apenas se o SHA-256 e as dimensões de cada ficheiro corresponderem. O cache **não** faz parte do lote aprovado nem do cliente.
- A etapa `audit`/`review-import` e a galeria são as existentes; não são contornadas. Mapas e parallax continuam sem certificação de runtime.

## Verificação e reversão

O pacote contém testes locais `tests/test_texture_ncnn_runner.py` e `tests/test_texture_ncnn_pipeline.py` que usam NCNN simulado (não uma GPU real). Os testes **não** substituem o ensaio no Fedora/RX 6600 nem o conjunto completo de testes do repositório original.

```bash
cd ~/Transferências/pt_asset_tool
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_texture_ncnn_runner.py tests/test_texture_ncnn_pipeline.py
# Quando aplicável, execute também os testes originais do projeto.
```

Para desfazer **apenas** este patch, caso não tenha feito outras alterações nesses ficheiros:

```bash
cd ~/Transferências/pt_asset_tool
git apply --check -R ~/Transferências/PT_ASSET_GPU_NCNN_V1.patch
git apply -R ~/Transferências/PT_ASSET_GPU_NCNN_V1.patch
```

A pasta de cache e a configuração gerada ficam intactas quando se remove o patch; remova-as manualmente **apenas depois de confirmar que já não precisa delas**.

## Limitações

A arquitetura ESRGAN 1× e o teste piloto GPU 2048×2048 foram confirmados na máquina do utilizador antes do patch, mas esta versão integrada não foi executada contra o cliente real neste ambiente. Este patch não garante qualidade uniforme para todas as texturas; mantenha `safe-game-v1`, seleção explícita e aprovação manual. Não ativa shaders, parallax, nem corrige geometria automaticamente.
