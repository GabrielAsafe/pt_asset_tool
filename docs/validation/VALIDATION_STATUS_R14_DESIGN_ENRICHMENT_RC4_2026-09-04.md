# Validation Status — R14 Design + Enrichment RC4 — 2026-09-04

## Motivo da RC4

O rerun físico da RC3 deixou somente `affine_animation_selftest` em `required_failures`. O SVD já reconstruía os factores corretamente, mas a composição real dos PoseBones no Blender divergia porque rest matrices e inheritance fazem parte da conversão Local→Pose.

## Mudança

- representação: `SVD_BLENDER_RESIDUAL_TWO_BONE_TRS_V2`;
- primeiro factor: SVD/TRS no helper não-deformável;
- segundo factor: resolvido por `Bone.convert_local_to_pose(..., invert=True)` usando helper pose + target global;
- residual do segundo basis deve ser TRS dentro de `2e-5`;
- rank-deficient + non-TRS: `EXPECTED_BLOCKED`/fail-closed na camada Blender;
- pose tolerance global não foi alterada.

## Validação local RC4

- affine/selftest contracts: **14/14 PASS**;
- regressão ampla sem `fixture_client`: **232/232 PASS**;
- compileall: PASS;
- JavaScript syntax: PASS;
- `VERIFY_PACKAGE.sh`: PASS;
- lote crítico na cópia final: **50/50 PASS**;
- quatro hashes dos rare writers: preservados/certificados.

## Próximo gate físico

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate integration-regression-auto
```

Se PASS, avançar para `validate release-1-auto --resume`.

`production_authorized=false`, `client_write_authorized=false`, `server_write_authorized=false`.
