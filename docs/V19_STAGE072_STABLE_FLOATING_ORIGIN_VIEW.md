# V19 — Stage 0.72: floating origin estável no proxy Blender

## Evidência (10-11-2026)

O Etervale V18 já passou no parsing, importação e transporte nativo do mapa
`Field/Boss/dark_boss.smd`. O auditor V13 de **preview visual** ainda reportava
`proxy_vertices_wrong_coordinate_basis` apesar de `PT_STAGE072_VIEW=PASS`.

Valores do log real: `source_center=(198296.328125,1461.146484,241891.828125)`,
`view_scale=0.0276040543`, `proxy_meshes=1`, `proxy_lights=0`. A validação do
transporte V18 indicou posição `0.0` e UV `0.0` de erro absoluto.

### Causa

O construtor V12 aplicava `Matrix(axis) @ Matrix.Scale(scale) @
Matrix.Translation(-center)` como uma única matriz a um objeto com coordenadas
mundiais grandes. Blender usa `float32` na mesh e no `mathutils.Matrix`; a
multiplicação da escala por coordenadas de 200–240 mil, seguida de subtração
de outro valor semelhante, pode perder precisão antes de chegar ao proxy.

O verificador V13 calculava `(posição - centro) * escala`, avaliando a
translação numa ordem mais estável, e reprovava quando o erro excedia `2e-4`.

### Correção

O proxy privado aplica quatro transformações **em sequência**:

1. matriz mundial do objeto-fonte, sobre `mesh = src.data.copy()`;
2. translação `-center`, antes de reduzir a escala;
3. escala `view_scale`;
4. matriz de conversão de eixos Y-up → Z-up, de determinante -1.

São preservados: a mesh fonte, a ordem das faces, os materiais, UVs, `SMD`
original, scripts de importação/exportação e a política da textura ausente.
Não se altera o limiar do auditor `2e-4` nem se introduz uma exceção por SHA.

### Validação

Os testes offline confirmam que a transformação composta ultrapassa `2e-4`
para coordenadas derivadas do centro real de Dark Boss, enquanto a sequência
centrar → escalar fica dentro de `5e-6` nessa amostra. Os testes não
substituem a execução de Blender 5.2.

Executar no projeto real:

```sh
python3 -m pytest -q app/dev_tests/test_etervale_stage072_view_rebase_f32_v19.py
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

**Sem `--fresh`:** os 57 mapas com PASS reaproveitam checkpoint; apenas
`dark_boss` deve repetir o worker. O esperado é
`blender_counts.PASS_BLENDER_TRANSPORT_AND_VIEW=58`. O `status` global pode
continuar `FAIL_OR_REVIEW_REQUIRES_ACTION` por referências em falta, `hTexture`
de Dark Boss e outras exceções de material; esta V19 não mascara tais revisões.

A certificação visual no cliente Etervale e a entrada no Texture Paint para
cada mapa continuam fora do alcance deste PASS de transporte e proxy.
