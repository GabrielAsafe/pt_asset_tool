# Texture Upscale — pipeline seguro

O PT Asset Tool possui um pipeline de upscale para texturas físicas do client. Ele cria **cópias** em `pt_build` (ou noutra árvore explicitamente indicada) e nunca publica diretamente no client.

Formatos suportados:

- TGA, incluindo a família de header protegido suportada pelo runtime;
- BMP, incluindo BMP protegido;
- PNG;
- JPG/JPEG.

## Dependências

O backend Lanczos requer **Pillow**. Esta dependência é opcional para o resto da aplicação: catálogo, inspeção, server/enrichment e outras funcionalidades continuam disponíveis sem ela.

O backend AI requer adicionalmente `realesrgan-ncnn-vulkan`. A aplicação detecta a disponibilidade separadamente. Ausência do Real-ESRGAN não torna a aplicação indisponível; apenas desativa esse backend.

Consulte:

```bash
cd app
python3 pt_asset.py status
```

em `optional_capabilities.texture_upscale`.

## Safety boundary

O pipeline aplica estas regras:

1. `client_root` é sempre fonte read-only;
2. output e manifest são rejeitados quando resolvem para dentro do client;
3. outputs existentes não são substituídos por padrão;
4. `--overwrite` é necessário para substituir um output já existente;
5. bytes são codificados e validados antes da publicação;
6. publicação usa ficheiro temporário completo + operação atômica;
7. o SHA-256 da fonte é conferido novamente após a operação;
8. `run` exige `--include`, `--include-exact` ou `--all`, evitando processar todo o client por acidente;
9. paths típicos de UI/atlas/login/font/cursor são bloqueados por padrão devido ao risco de consumidores com recortes em pixels;
10. `--include-ui` é uma autorização explícita para testar esses paths; continua sem autorizar deploy no client.

Cada execução automática da UI é criada sob:

```text
app/pt_build/texture_upscale/runs/<run-id>/
├── overlay/
└── manifest.json
```

## Classes de risco

O manifest classifica cada entrada como:

- `UI_ATLAS_RISK` — path com alto risco de recortes/source rectangles em pixels;
- `THREE_D_TEXTURE_CANDIDATE` — path tipicamente associado a character/field/effect/map/terrain;
- `UNKNOWN_USAGE_RISK` — uso não provado automaticamente.

`THREE_D_TEXTURE_CANDIDATE` não significa autorização de produção. O resultado precisa de validação visual/in-game antes de qualquer promoção externa.

## Usar pela GUI

1. abra **Catálogo**;
2. selecione BMP/TGA/PNG/JPG/JPEG;
3. arme **workspace/build**;
4. clique **Upscale textura**;
5. escolha `2`, `3` ou `4`;
6. escolha `lanczos` ou `realesrgan`;
7. se o asset estiver num path UI/atlas, a GUI exige confirmação explícita;
8. acompanhe a tarefa em **Tarefas & Console**;
9. abra o manifest/output informado no console sob `pt_build/texture_upscale/runs/...`;
10. valide o resultado antes de o promover manualmente para qualquer ambiente externo.

A ação da GUI processa somente o asset selecionado.

## Scan CLI

O `client_root` é opcional; quando omitido, usa a configuração/discovery normal do PT Asset Tool.

```bash
cd app
python3 pt_asset.py texture-upscale scan
```

O manifest vai para `app/pt_build/texture_upscale/scans/`.

Para limitar o scan:

```bash
python3 pt_asset.py texture-upscale scan \
  --include 'Image/Character/*.tga' \
  --exclude '*/Login/*'
```

## Upscale CLI — Lanczos

```bash
cd app
python3 pt_asset.py texture-upscale run \
  --include 'Image/Character/hero.tga' \
  --scale 4 \
  --backend lanczos
```

Sem `--output-root`, a execução cria automaticamente uma árvore única em `pt_build/texture_upscale/runs/`. `run` nunca assume "todas as texturas": use `--all` somente quando essa intenção for explícita.

## Upscale CLI — Real-ESRGAN

Com `realesrgan-ncnn-vulkan` disponível no `PATH`:

```bash
python3 pt_asset.py texture-upscale run \
  --include 'Image/Character/hero.tga' \
  --scale 4 \
  --backend realesrgan
```

Também é possível informar explicitamente o executável:

```bash
python3 pt_asset.py texture-upscale run \
  --output-root /caminho/fora/do/client/upscaled_overlay \
  --scale 4 \
  --backend realesrgan \
  --realesrgan /caminho/realesrgan-ncnn-vulkan \
  --model realesrgan-x4plus \
  --tile 256 \
  --gpu 0
```

## UI/atlas de risco

Por padrão, paths conhecidos de UI/login/font/cursor são reportados como `skipped_ui_pixel_crop_risk`.

Para um teste controlado:

```bash
python3 pt_asset.py texture-upscale run \
  --include 'game/Login/button.png' \
  --scale 2 \
  --backend lanczos \
  --include-ui
```

Isso apenas permite criar a cópia. Não significa que o consumidor do jogo esteja preparado para uma textura redimensionada.

## Output existente

Por padrão:

```text
output já existe -> failed / não substituído
```

Só use:

```bash
--overwrite
```

quando a substituição de **output/manifest de staging**, nunca do client, for deliberada. Manifests explicitamente indicados também não são sobrescritos por padrão.

## Manifest

O JSON inclui, por asset:

- path source;
- formato/protection mode;
- width/height originais;
- alpha;
- SHA-256 da fonte;
- classe de risco;
- backend/escala;
- path e SHA-256 do output;
- dimensões do output;
- prova `source_unchanged`;
- status/reason;
- tempo de execução.

No nível do report há também `source_write_attempted=false` e `source_client_modified=false` quando a prova de imutabilidade passa.
