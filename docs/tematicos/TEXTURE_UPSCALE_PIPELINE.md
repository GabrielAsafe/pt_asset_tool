# Texture Enhance / Upscale — pipeline seguro

O PT Asset Tool possui um pipeline de **enhance + upscale** para texturas físicas do client. Ele cria **cópias** na workspace dedicada `pt_build/texture_upscale/` (ou noutra árvore explicitamente indicada). O estágio `run` nunca escreve no client; publicação individual ou em lote só acontece por comandos separados com confirmação explícita, backup e verificação de hash. O original continua sendo a referência e o manifest regista backend, perfil de qualidade, hashes e métricas antes/depois.

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
10. `--include-ui` é uma autorização explícita para testar esses paths; continua sem autorizar deploy no client;
11. runs longos gravam checkpoints atômicos no manifest; `texture-upscale resume` reutiliza candidates já verificados por SHA-256;
12. `publish-batch` faz preflight de **todos** os source/candidate hashes antes da primeira escrita; falha durante o lote dispara rollback automático do que já foi aplicado;
13. `restore-batch` também faz preflight completo de drift/backups antes da primeira restauração.

O projeto contém uma pasta `pt_build/texture_upscale/` dedicada a este workflow; `runs/` e `transactions/` são runtime e ficam ignorados pelo Git.

Cada execução automática da UI é criada sob:

```text
pt_build/texture_upscale/runs/<run-id>/
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
4. clique **Enhance / Upscale textura**;
5. escolha `2`, `3` ou `4`;
6. escolha um perfil: `faithful`, `balanced`, `detail` ou `pixel-art`;
7. escolha `auto`, `lanczos` ou `realesrgan`; `auto` é o padrão seguro e usa AI apenas quando o perfil/ambiente justificam, com fallback para Lanczos;
8. se o asset estiver num path UI/atlas, a GUI exige confirmação explícita;
9. acompanhe a tarefa em **Tarefas & Console**;
10. abra o manifest/output informado no console sob `pt_build/texture_upscale/runs/...`;
11. compare visualmente o original e o output e valide in-game antes de qualquer promoção externa.

A ação da GUI processa somente o asset selecionado. Depois que o candidate termina, o detalhe do asset é atualizado e passa a expor **Enviar enhancement ao cliente**. A publicação exige o arm de client, valida que o ficheiro fonte não mudou desde a geração do candidate, cria backup verificado e só então faz a substituição atômica. Quando a publicação termina, aparece **Desfazer enhancement**; esse rollback só executa se o client ainda contiver exatamente o hash publicado.

As transações ficam sob:

```text
pt_build/texture_upscale/transactions/<asset-key>/<transaction-id>/
├── backup/<client-relative-path>
└── transaction.json
```

CLI equivalente:

```bash
python3 pt_asset.py texture-upscale publish \
  --include-exact 'Image/Character/hero.tga' \
  --confirm 'APPLY CLIENT ENHANCEMENT'

python3 pt_asset.py texture-upscale restore \
  --include-exact 'Image/Character/hero.tga' \
  --confirm 'RESTORE CLIENT ENHANCEMENT'
```


## Enhancement global / lote completo

A aba **Cliente / Asset Enrichment** possui quatro ações globais:

- **Enhance todas as texturas (AI)** — executa Real-ESRGAN `detail` para BMP/TGA/PNG/JPG/JPEG e inclui deliberadamente UI/atlases para o teste global;
- **Retomar último run** — lê o manifest checkpointado, reutiliza candidates cujo source/output SHA-256 ainda confere e reprocessa somente falhas/pendentes;
- **Publicar lote no cliente** — valida todos os hashes antes da primeira escrita, cria backup/transação por asset e mantém um `pt_build/texture_upscale/batches/<batch-id>/batch.json`;
- **Desfazer lote publicado** — recusa o lote inteiro se qualquer ficheiro tiver drift ou backup inválido; quando começa, restaura as transações do lote de forma controlada.

CLI equivalente:

```bash
python3 pt_asset.py texture-upscale run --all --include-ui \
  --scale 4 --backend realesrgan --profile detail --gpu 0 --model realesrgan-x4plus

# se o run for interrompido
python3 pt_asset.py texture-upscale resume

python3 pt_asset.py texture-upscale publish-batch \
  --confirm 'APPLY CLIENT ENHANCEMENT BATCH'

python3 pt_asset.py texture-upscale restore-batch \
  --confirm 'RESTORE CLIENT ENHANCEMENT BATCH'
```

`batch-status` mostra o último run, o último lote e se existe rollback global disponível.

> Nota operacional: upscale 4x aumenta a área da imagem em 16x. Em BMP/TGA sem compressão, o espaço de staging pode crescer aproximadamente nessa ordem; a publicação ainda adiciona backups do tamanho dos originais. Para o client completo, confirme espaço em disco antes de iniciar.

## Perfis de qualidade

- `faithful` — resize de alta qualidade sem sharpening adicional; indicado quando preservar a aparência é mais importante do que ganhar microcontraste.
- `balanced` — sharpening leve após o resize; é o perfil recomendado como ponto de partida.
- `detail` — sharpening mais forte e, com `--backend auto`, tenta Real-ESRGAN quando disponível antes de recorrer a Lanczos.
- `pixel-art` — usa nearest-neighbour para preservar grelha/pixels; Real-ESRGAN é recusado neste perfil.

O alpha é preservado. Para TGA/BMP protegidos, o writer mantém o modo de proteção compatível já suportado pelo pipeline. O manifest regista uma métrica de detalhe antes/depois (`detail_metric_before`, `detail_metric_after`, `detail_gain_ratio`) apenas como evidência comparativa — ela **não substitui validação visual**.

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
  --backend lanczos \
  --profile balanced
```

Sem `--output-root`, a execução cria automaticamente uma árvore única em `pt_build/texture_upscale/runs/`. `run` nunca assume "todas as texturas": use `--all` somente quando essa intenção for explícita.

## Enhance CLI — backend automático

```bash
python3 pt_asset.py texture-upscale run \
  --include 'Image/Character/hero.tga' \
  --scale 4 \
  --backend auto \
  --profile balanced
```

`auto` evita exigir AI: no perfil `detail` tenta Real-ESRGAN quando disponível; nos restantes casos usa o backend determinístico apropriado.

## Upscale CLI — Real-ESRGAN

Com `realesrgan-ncnn-vulkan` disponível no `PATH`:

```bash
python3 pt_asset.py texture-upscale run \
  --include 'Image/Character/hero.tga' \
  --scale 4 \
  --backend realesrgan \
  --profile detail
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
- backend efetivamente usado, escala e perfil de qualidade;
- path e SHA-256 do output;
- dimensões do output;
- prova `source_unchanged`;
- status/reason;
- métrica comparativa de detalhe antes/depois;
- tempo de execução.

No nível do report há também `source_write_attempted=false` e `source_client_modified=false` quando a prova de imutabilidade passa.

## Testemunho da decisão de backend

`texture-upscale run` regista o backend efetivamente usado e o motivo da seleção. Em `--backend auto`:

- `faithful` e `balanced` usam deliberadamente Lanczos determinístico (`AUTO_CONSERVATIVE_PROFILE_LANCZOS`);
- `detail` usa `realesrgan-ncnn-vulkan` quando disponível e, caso contrário, regista `AUTO_DETAIL_REALESRGAN_UNAVAILABLE_FALLBACK_LANCZOS` com o erro de descoberta;
- `pixel-art` usa nearest-neighbour.

Use `python3 pt_asset.py texture-upscale capabilities` para verificar os backends antes de um lote. `PASS` significa que o output de staging foi criado e verificado; não implica que AI tenha sido usada. Confira `ai_enhancement_used`, `enhancement_class` e `backend_decision`.

<!-- PT_TEXTURE_RUNTIME_CANONICAL_2026-09-25 -->

## Preservação antes de clean/release

O fato de `app/pt_build/texture_upscale/` ser runtime gerado não torna transações/manifests automaticamente descartáveis. Antes de uma consolidação/clean que remova `pt_build`, arquive/exporte qualquer run, transaction, batch ou manifest necessário para auditoria, comparação ou rollback futuro.

Nunca apague esse estado assumindo que existe uma migração: primeiro confirme o destino e hashes da cópia.
