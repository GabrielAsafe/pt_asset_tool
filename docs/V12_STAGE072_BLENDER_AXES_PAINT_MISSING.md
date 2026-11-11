# Etervale V12 — Stage0.72 Blender: orientação e paint parcial

## Evidência física: Ricarten

Ficheiro de prova: `assets/Field/Ricarten/village-2.smd`, SHA-256 `44a58c6ea44c5537120e2ba6b4d67df47f798faacf31f7d0922fd481825f06aa`.

O parse físico confirmou 41.783 vértices, 44.226 faces, 342 materiais e 79 metadados de luz. No subconjunto de 7.716 triângulos quase horizontais, **7.063** têm normal por winding dirigida a `-Y`; apenas **653** a `+Y`. Como a representação nativa é Y-up/handedness legada mas Blender é Z-up, simplesmente copiar `(x,y,z)` para Blender causa inspeção visual invertida: chão visível do lado oposto à arquitetura.

**Conversão exclusiva do proxy visual:** `(X,Y,Z) -> (X,Z,Y)`; determinante `-1`. Essa reflexão adapta Y-up para Z-up e converte o winding para a orientação Blender, sem reordenar os índices ou UV loops. O mesh original importado/certificado no `.blend` mantém os vértices no espaço do jogo. O preview usa cópia independente `PT_STAGE072_VIEW_STAGE`, já marcada como `view_only`; o writer procura exclusivamente meshes `pt_stage072_source_sha256` e não toma o proxy por source. Metadados de luz deslocam-se pela **mesma** base para permanecerem alinhados. Orientação inicial da viewport parte de Blender +Z, ligeiramente inclinada.

### Paint com a imagem `tem_wall04.bmp` ausente

Em Ricarten, material 173 refere `field\\ricarten\\tem_wall04.bmp`, que não existe no corpus. O comportamento antigo abortava todo o paint por `target_image_none`, apesar de a referência não afetar outras texturas.

A V12 faz uma **exceção estrita somente para esse caminho e stage 0**, validada por `stage072_paint_policy`. O material continua com `image=None`; não há textura artificial nem substituição arbitrária. As faces do material sem imagem são ocultadas **apenas no proxy de pintura** e registadas como `KNOWN_MISSING_UNPAINTABLE_NO_SUBSTITUTE` no `paint_manifest.json`. Nenhuma operação de pintura desse material é autorizada. Erros de outras texturas, imagens privadas ausentes, symlinks ou referências diferentes continuam a provocar falha.

Status esperado: `PT_STAGE072_PAINT=PASS_WITH_KNOWN_MISSING_UNPAINTABLE` e no manifest `private_image_validation_status=PASS_WITH_KNOWN_MISSING_UNPAINTABLE`, `private_image_validation_pass=false`, `source_texture_dependencies_complete=false`.

## Instalação

Patch incremental, com dry-run, SHA-256, backup e recusa de conflitos. Altera somente:
- `app/pt_asset_tool/blender/open_stage072_preview.py`
- `app/pt_asset_tool/blender/open_stage072_paint.py`

Cria helpers puros e testes; não altera `import_stage072.py`, `stage072_geometry.py`, os SMD originais, texturas cliente, `Etervale-git` ou BD.

## Verificação manual no checkout do utilizador

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_asset.py view stage072 Field/Ricarten/village-2.smd
python3 app/pt_asset.py paint stage072 Field/Ricarten/village-2.smd --stage 0
python3 app/pt_asset.py validate stage072-geometry-roundtrip Field/Ricarten/village-2.smd
```

**Não altere manualmente a rotação da mesh fonte** para exportar. Se precisar de rodar a vista, faça-o apenas no viewport. No Paint, utilize o `stage072_texture_paint_workspace.blend` salvo em `pt_build/blender_edits/...`, nunca o `.blend` de certificação como ficheiro de pintura. Não aplique o resultado ao cliente até a validação visual de UV/material/persistência, e nunca pinte a face que refere a textura ausente.

## Limitações do teste

Provas Python: 3 testes novos passaram e mais 6 testes Stage existentes passaram; 6 casos foram skipped por requisitos de Blender/fixtures não presentes. Usámos o **SMD real fornecido** para confirmar a assinatura e a orientação matemática. Não existe `blender` executável neste ambiente, portanto a inicialização do Blender 5.2, a mudança para Texture Paint e a apresentação visual após a reflexão **precisam de ser confirmadas na instalação real**. O `ROUNDTRIP=PASS` original não muda de alcance: é prova binária, não de rendering ou pintura.
