# V16 — Stage0.72: JPEG identificado por assinatura e compatibilidade hTexture com revisão

**Base:** Etervale V14 Stage0.72 (V15 foi apenas um script de recolha de evidências).
**Alcance:** ferramentas do `pt_asset_tool`, não o cliente Etervale. Nenhum SMD, textura original, reader C# ou DB é modificado.

## Evidência da V15 recebida

- `Field/forever-fall/mo_g_012_01.bmp`: 3.978 bytes, SHA-256 `9c5128eadc6e57ac5bb27a7fca054d9d7a123f4a312fe0e8b9ea04feff54d02b`, bytes `FF D8 FF E0` e identificador `JFIF`. O problema não é uma variante BMP protegida — os bytes indicam JPEG sob extensão `.bmp`.
- `Field/Boss/dark_boss.smd`: SHA-256 `fff8acbe1cb39f70f376e380a21cfed760557c5af4ee73b2ad2ed26ebc39d706`. O reader físico passou em geometria, ponteiros TexLink e StageArea, mas encontrou `hTexture=0` em faces do material 0 com uma textura declarada. Nos casos amostrados, cada uma dessas faces tem um único TexLink e U/V=(0,0) nos três cantos.
- Reexecução V14 em Blender: 56/58 mapas com transporte e proxy aprovados. As quatro falhas UV de precisão foram resolvidas. Os restantes dois mapas não foram aprovados nessa execução.

## Alterações

### 1. JPEG real com nome `.bmp`

`pt_asset_tool/stage072_preview_jpeg.py` só aceita assinatura **JPEG JFIF** coerente, ficheiro integralmente decodificável em Pillow e dimensões dentro dos limites. Converte **apenas no overlay de preview** para BMP RGB com o mesmo caminho lógico. Valida que cada píxel RGB do BMP coincide com o JPEG decodificado; compara o SHA-256 antes e depois para garantir que a fonte não foi modificada. Classifica no overlay como `JPEG_IN_BMP_PREVIEW_CONVERTED`.

A conversão de formato **não** é realizada nos assets Etervale, nem declara que o motor suporta universalmente JPEG renomeado. BMP protegido normal, BMP ship e TGA continuam nas políticas pré-existentes. JPEG truncado/inválido é bloqueado.

### 2. `dark_boss` — admissão para preview por SHA do ficheiro e invariantes

O reader C# do checkout Etervale (`PristonSmdReader`) preserva `TexturePointer32`; a composição da geometria (`PristonCornerVertex` / `PristonStageLinks.Resolve` / `PristonRenderer.StageGeometry`) utiliza índices TexLink e UVs, sem consumir esse token para construir os vértices. Isto permite verificar um preview do **SMD exato** com `hTexture=0` e UVs nulas, mas não demonstra equivalência com todas as implementações legadas.

A V16 só admite essa exceção quando **todas** as condições seguintes se verificam: SHA-256 exato acima, material 0, `TextureCounter=1`, `AnimTexCounter=0`, profundidade TexLink 1, stage 0, `hTexture=0` e seis coordenadas UV iguais a zero. Qualquer outro erro continua a bloquear. O relatório de parsing regista o número e os exemplos em `source_exact_null_handle_review_count`, e o verificador `htexture_stage_mapping` retorna `PASS_WITH_SOURCE_EXACT_REVIEW`. O resultado global desse mapa é **`REVIEW_REQUIRED`**, mesmo que o proxy headless passe.

Nenhum normalizador ou writer reescreve `hTexture`, texlinks, geometria, UVs, materiais ou StageArea.

### 3. Retoma do batch

`stage072_batch_audit` invalida o checkpoint **apenas** de `dark_boss` se este tiver a antiga falha de parsing. O worker de `pilai` volta a correr caso continue marcado como `FAIL_BLENDER_WORKER`. Os **56 mapas já aprovados no Blender** são reutilizados sem nova renderização, desde que ficheiros e assinaturas permaneçam iguais. Não usar `--fresh`.

## Limites e verificações ainda pendentes

- Validar no **Blender real do utilizador** os dois mapas. Se a textura JPEG original não descodificar com Pillow, continua corretamente bloqueada; o relatório do overlay indicará o erro exato.
- Os 24 ficheiros ausentes, aliases inválidos de SOD/`pilai` e a exceção conhecida `tem_wall04.bmp` não foram criados nem corrigidos pela V16. Permanecem para revisão como anteriormente.
- `dark_boss` poderá apresentar UVs nulas e amostragem do texel `(0,0)` no material 0. Isto é um resultado visual potencialmente distinto do motor original; **não é uma certificação visual do jogo**.
- A política de source SHA reconhece apenas a versão física comprovada em V15. Qualquer alteração do ficheiro desativa a exceção.

## Provas locais

- Testes de conversão com JPEG sintético renomeado `.bmp`, verificação RGB pós-conversão, fonte byte-identical, recusa de truncado e recusa de formatos falsos.
- Testes de corpus com Stage0.72 sintético: exceção por SHA, revisão em vez de PASS, rejeição de UVs não nulas, modelo/material/stage errados.
- SMD físico Ricarten fornecido: mantém `full_parse=PASS` sem exceção (`41.783` vértices, `44.226` faces).
- Testes V12/V13/V14/V16 locais: **23 passed, 2 skipped**. As duas provas de corpus omitidas requerem materiais externos ausentes do ambiente de testes; não constituem certificação de `dark_boss`/`pilai` físicos.

## Execução proposta

```
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

Enviar os dois registos `Field/Boss/dark_boss.smd` e `Field/forever-fall/pilai.smd` e o resumo `blender_counts`, `counts`, `missing_total` e `not_runtime_visual_certified`. O status agregado continuará a requerer revisão enquanto houver referências ausentes/inválidas e a exceção de `dark_boss`.
