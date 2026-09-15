# Validation Status — R14 Design + Enrichment RC3 — 2026-09-04

## Local automatic status
- compileall: PASS
- developer docs inventory: PASS
- dev tests sem `fixture_client`: **228 PASS / 0 FAIL**
- certified rare writer hashes: PRESERVED
- package policy: client/server read-only; `pt_build` only

## Último rerun físico recebido
O rerun RC1 confirmou que a camada server-side já não está falhando por parser:

- `server_parser_regression=PASS`;
- entity/OpenItem/Field detection ativa;
- identidade OpenItem e resolução ZHOON funcionando;
- `client_modified=false`;
- `server_modified=false`.

O gate ainda terminou em `FIX_REPORTED_INTEGRATION_REGRESSIONS`, mas o paste de terminal começou no meio do censo OpenItem e não continha o bloco inicial `required_failures`. Portanto não promovemos nenhum failure físico a PASS por inferência.

## Correções RC2
- O self-test affine usa `Bone.convert_local_to_pose` na hierarquia original para construir o target antes de inserir o helper, alinhando o self-test ao contrato do bake real.
- Falha affine agora persiste expected/actual/factor matrices em `build_report.json` antes de abortar.
- `integration-regression-auto` grava `failure_summary.json` e repete cada failure no final do terminal.
- A CLI imprime um resumo compacto e mantém os censos completos somente nos JSONs de `pt_build`.

## Próximo gate

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate integration-regression-auto
```

Se ficar PASS, o próximo gate é `validate release-1-auto --resume`.

## External gates ainda não promovidos
- Mixed-Physique físico autêntico, caso nenhum representative exista em client+server;
- runtime/game acceptance dos representatives definidos;
- promoção controlada de writers e publish/restore/rollback.

`production_authorized=false`, `client_write_authorized=false`, `server_write_authorized=false`.


## Correção RC3 — rank-deficient SVD
O `failure_summary.json` físico da RC2 confirmou uma única falha obrigatória, `affine_animation_selftest`, causada por normalização de um vetor `M·v` numericamente nulo. A RC3 calcula as magnitudes singulares por `||M·v||`, mantendo o eigensolver apenas para `V`/ordenação. Duas regressões rank-2 protegem a classe. PENDING_PHYSICAL_RERUN.
