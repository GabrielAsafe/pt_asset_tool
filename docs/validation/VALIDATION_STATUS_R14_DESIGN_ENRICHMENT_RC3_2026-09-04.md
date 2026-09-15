# Validation Status — R14 Design + Enrichment RC3 — 2026-09-04

## Motivo da RC3
O rerun físico da RC2 reduziu o integration gate a uma única falha obrigatória: `affine_animation_selftest`.
O stack trace mostrou que uma matriz exatamente rank-2 produziu um autovalor positivo residual em `M^T M`; o código então tentou normalizar `M·v` praticamente zero e abortou com `cannot normalize near-zero vector`.

## Correção
`svd_affine_split` continua usando o eigensolver para obter/orderar `V`, mas a magnitude singular operacional passa a ser calculada por `||M·v||`. Isso classifica corretamente eixos nulos mesmo quando o eigensolver deixa resíduos positivos minúsculos.

A alteração não afrouxa tolerâncias nem transforma matrizes inválidas em PASS. O rebuild continua sujeito ao residual máximo fail-closed já existente.

## Regressões adicionadas
- matriz rank-2 exata usada pelo self-test Blender da RC2;
- segunda matriz rank-2 com shear/scale diferentes para proteger a classe numérica, não apenas uma fixture literal.

## Validação local RC3
- `dev_tests/test_affine_factor.py`: **7/7 PASS**;
- lote diretamente afetado (affine/integration/release/server/SMB/TGA): **53/53 PASS**;
- `compileall`: PASS;
- hashes dos quatro rare writers certificados: preservados;
- package verifier: executado sobre a cópia final antes do ZIP.

A regressão ampla da RC2 foi 228/228 PASS e a RC3 altera apenas o fatorador affine, testes/documentação/manifest. O ambiente deste container não possui o Blender/cliente Summit necessários para executar o self-test físico.

## Próximo gate físico

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate integration-regression-auto
```

Se PASS: `validate release-1-auto --resume`.

`production_authorized=false`, `client_write_authorized=false`, `server_write_authorized=false`.
