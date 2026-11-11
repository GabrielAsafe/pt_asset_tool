# V18 — Stage 0.72: verificação estrita das posições no ABI binary32 Blender

## Evidência do diagnóstico V17

- `Field/Boss/dark_boss.smd`, `source_sha256=fff8acbe1cb39f70f376e380a21cfed760557c5af4ee73b2ad2ed26ebc39d706`
- Parsing e importação Blender: `PASS`.
- UVs: `max_uv_abs_error=0.0`; cor: `max_color_abs_error=2.9685450542160652e-08`.
- Transporte da posição: `max_position_abs_error=0.00390625`, com vários vértices a reprovar por serem comparados com Python64.
- Textura `field/boss/a_flag01.TGA`: `MISSING`; não é alterada, criada nem tratada como resolvida.

## Causa e correção

O Stage 0.72 armazena vértices e posições de luz em unidades fixas inteiras. O importador calcula `raw / 256.0` em Python `float64`, mas `MeshVertex.co` e `Object.location` persistem coordenadas `float32` no Blender. Para magnitudes grandes, o arredondamento correto pode produzir um delta de `0.00390625` relativamente ao valor Python64. Uma coordenada de origem `16777217 / 256 = 65536.00390625` é serializada em single precision como `65536.0`.

A V18 compara **cada coordenada persistida com `float32(raw / 256)`**, exatamente; qualquer delta real de um único passo representável continua a reprovar (`if err != 0`). Luzes usam a mesma regra estrita. O relatório mantém `max_position_abs_error` e acrescenta `position_precision_policy`, `max_position_python64_intermediate_delta`, `max_light_position_abs_error` e `max_light_python64_intermediate_delta`, distinguindo erro persistido de arredondamento esperado.

Não existe relaxamento global de tolerância. **O valor Python64 não pode ser reconstruído exatamente de um `float32` arredondado**; esta verificação certifica transporte fiel na representação Blender, não equivalência bit a bit com a origem.

## Âmbito e segurança

- Só modifica `app/pt_asset_tool/blender/check_stage072_transport.py`.
- Adiciona helper de quantização `stage072_position_float32.py`, testes V18 e este documento.
- Não muda o parser, importador, Stage SMD/SMB, UVs ou texturas originais; não escreve no cliente Etervale.
- A exceção de `hTexture=0` em `dark_boss` continua ligada ao SHA-256 exato e marcada `REVIEW_REQUIRED`.
- `field/boss/a_flag01.TGA` continua ausente e o mapa não se torna materialmente completo nem certificado em runtime.
- Esta regra é extensível a todos os Stage 0.72 e não seleciona nem modifica assets.

## Testes realizados

- 29 testes de regressão V12–V18 aprovados num ambiente de sandbox, incluindo um caso sintético que reproduz exatamente `0.00390625` e deteção de corrupção por um único ULP.
- Simulação da conversão binary32 para todas as posições de vértices do SMD físico Ricarten.
- Não foi realizada nova importação Blender do `dark_boss` na máquina do utilizador; a certificação real continua pendente.

## Validação em Etervale

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

Sem `--fresh`; os 57 mapas já aprovados são reutilizados do checkpoint. O resultado esperado é `PASS_BLENDER_TRANSPORT_AND_VIEW` também para `Field/Boss/dark_boss.smd`, mas o respetivo estado de dependências deve continuar `REVIEW_REQUIRED`, por `hTexture` revisto e textura ausente. Se ocorrer outra falha, consultar `stage072_transport_check.json` e logs específicos antes de aplicar novas mudanças.
