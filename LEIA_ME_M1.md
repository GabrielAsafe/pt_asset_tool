# M1 — Pré-teste não destrutivo do Stage 0.72

Este pacote não instala código no cliente e não faz commit/rollback. Verifica a proveniência dos dados e as condições mínimas para os testes reais.

## 1. No teu PT Asset Tool

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 tools/m1_stage_preflight.py --tool-root . --game-root "$HOME/Transferências/Etervale-git"
```

Se o jogo usa uma pasta de assets diferente, usa `--source-smd /caminho/real/Field/forest/fore-1.smd`.

O source SHA-256 esperado dos teus JSON é:
`df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62`.

`SOURCE_PASS_RUNTIME_NOT_TESTED` significa apenas que a origem corresponde ao Stage classificado, **não que as árvores modernizadas estejam publicadas no cliente**.

## 2. Reexecutar os testes da pipeline existente

```bash
PYTHONPATH=app python3 -m pytest -q \
  app/dev_tests/test_asset_bundle_deploy.py \
  app/dev_tests/test_workspace_bundle_deploy.py \
  app/dev_tests/test_deployment_plan.py \
  app/dev_tests/test_stage072_compiler.py
```

Estes testes devem atuar apenas em fixtures temporárias. Se já houve mudanças locais nos próprios testes ou código, revê o diff antes.

## 3. Estado dos bundles existentes

```bash
python3 app/pt_asset.py asset-compiler status
```

Se a descoberta automática do client não funcionar, usa `--client-root` com a pasta real do client/assets. Verifica cuidadosamente a pasta de destino antes de qualquer publicação.

Não executar `asset-compiler publish` ou `deploy workspace-publish` sobre a pré-visualização V32. O V32 ainda guarda máscaras/instâncias em JSON; não existe por isso um SMD modificado certificado a publicar neste pacote.

## 4. Primeiro carregamento do mapa original

Com o cliente Etervale fechado, guardar o SHA do Stage efetivamente consumido pelo jogo. Depois, inicia o cliente e entra na área de `fore-1` pelo fluxo habitual. Confirmar que a cena carrega, que a navegação/colisão funciona e que o log não apresenta erro de Stage ou texturas. Este teste é a referência **antes** de qualquer commit experimental.

A partir daí: gerar o artefacto compatível, testar o mesmo no clone do client, medir FPS/erros, aplicar por transação aprovada e restaurar comprovando SHA idêntico ao original. O pipeline transacional existente deve ser reutilizado, não reimplementado.
