# Validation Status — R14 Design + Enrichment RC2 — 2026-09-04

## Local automatic status
- compileall: PASS
- developer docs inventory: PASS
- dev tests sem `fixture_client`: **228 PASS / 0 FAIL**
- package verifier: será executado sobre a cópia final antes do ZIP
- certified rare writer hashes: PRESERVED
- package policy: client/server read-only; `pt_build` only

## Último rerun físico recebido
A parte visível do resultado confirmou:

- parser regression server-side: PASS;
- OpenItem identity/ZHOON resolution ativos;
- `client_modified=false`;
- `server_modified=false`;
- `next_gate=FIX_REPORTED_INTEGRATION_REGRESSIONS`.

O paste recebido começou no meio do censo OpenItem, então os nomes dos failures obrigatórios do topo não sobreviveram ao scrollback. Isto motivou uma correção de produto nesta RC: o gate agora grava `failure_summary.json` e repete cada failure no final do terminal.

## Correção affine desta RC
O self-test sintético calcula o target de pose com `Bone.convert_local_to_pose` na hierarquia original antes da inserção do helper. Isso alinha o self-test com o contrato usado pelo bake real e evita comparar contra uma fórmula manual que pode divergir das regras de inherit-scale/local-location do Blender.

Uma eventual falha física futura grava as matrices dos fatores, expected/actual source matrices, `use_connect` e erro máximo antes de abortar.

## Próximo gate

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate integration-regression-auto
```

Se PASS: `validate release-1-auto --resume`.

## External gates ainda não promovidos
- Mixed-Physique físico autêntico, caso nenhum representative exista em client+server;
- runtime/game acceptance dos representatives definidos;
- promoção controlada de writers e publish/restore/rollback.

`production_authorized=false`, `client_write_authorized=false`, `server_write_authorized=false`.
