# PT Asset Tool R14 1.0.0 — Troubleshooting

## `PACKAGE_VERIFY=FAIL snapshot_manifest`

Algum arquivo estático difere do snapshot. Não “corrija” apagando a linha do manifest. Determine se houve alteração autorizada; em desenvolvimento, atualize documentação/código e depois regenere a certificação de snapshot de forma controlada.

## Client root não resolve

```bash
python3 pt_asset.py config show
python3 pt_asset.py config set-client-root "/path/cliente"
```

Depois rode `validate environment-auto`.

## Server root não resolve

Configure com `config set-server-root` ou `--server-root`. Use `validate server-environment-auto` antes do enrichment.

## Blender não abre / Flatpak

Verifique o comando disponível e `PT_BLENDER_COMMAND`. Rode `validate environment-auto`, que testa a bridge filesystem/headless real.

## `PENDING`, `REVIEW`, `CONFIG_ONLY`

Não são sinônimos de arquivo corrompido. Consulte:

```bash
python3 pt_asset.py explain statuses
python3 pt_asset.py explain bindings
```

## Model0.62 texture presence FAIL mas gate automático PASS

Na 1.0 capability do auditor/codec é separada de target-content readiness. Missing expected texture e payload inválido permanecem FAIL de conteúdo, sem se tornarem blocker do tool.

## Proprietary texture corpus FAIL

Leia `corpus_capability_status`, `corpus_target_content_status`, `corpus_codec_failure_count` e `corpus_target_content_invalid_count`. Um strict corpus FAIL pode coexistir com capability PASS quando a causa é target inválido.

## Recovery encontrou donor parecido

Não copie manualmente. Recovery depende de identidade/reachability/lineage/expected roots; basename/casefold é apenas pista diagnóstica.

## GUI não mostra uma ação

`ui_capabilities.py` filtra por asset/família/evidência. Use `asset authoring` e `build --plan` para ver por que um canal está bloqueado.

## Writer bloqueado

Isso é esperado se o asset não pertence ao escopo certificado ou se falta provenance/context. Não aumente tolerância para “fazer passar”.

## `BLOCKED_EXTERNAL`

Se `automatic_gate_status=PASS` e `blockers=[]`, significa que a capability automática passou e resta uma operação externa safety-locked (por exemplo publish/promotion). Não é falha de parser/writer.

## Client/server write authorization false

É o estado esperado da distribuição 1.0. Não altere os flags como atalho.

## T5 effect/audio divergente

Use `audit t5-assets`, `source-contracts` e `player-class-contracts`. Lembre que PRELOAD não prova ACTIVATION e reference-only não é recovery authority.
