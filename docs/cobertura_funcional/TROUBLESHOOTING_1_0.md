# PT Asset Tool R14 1.0.0 — Troubleshooting

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

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

Verifique o comando disponível e `PT_BLENDER_COMMAND`. `validate environment-auto` testa a bridge filesystem/headless quando Blender existe. Se Blender não estiver instalado, a capability fica `SKIP` e o ambiente geral pode continuar `PASS`; operações Blender e `release-1-auto` permanecem bloqueadas.

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

## Client/server write authorization / arms

Read-only continua sendo o default. Não altere flags como atalho. Para Legacy Authoring: stage usa BUILD arm; publish/restore usa ASSET DEPLOY arm/confirmation e só funciona para bundles tipados suportados.

## T5 effect/audio divergente

Use `audit t5-assets`, `source-contracts` e `player-class-contracts`. Lembre que PRELOAD não prova ACTIVATION e reference-only não é recovery authority.
\n## World Closure mostra REVIEW por ASE missing\n\n`REVIEW` é diagnóstico, não confirmação de que o item está quebrado. Verifique se a família realmente exige DropItem ASE e se o item possui target OpenItem/runtime válido. Selecionar a linha pode carregar o OpenItem correspondente no Legacy Authoring.\n\n## Explorer não carregou o Authoring\n\nVerifique o detalhe da linha:\n\n- `authoring_reason`;\n- path ambíguo;\n- mais de uma definição OpenItem para o mesmo code;\n- row sem kind suportado.\n\nTargets ambíguos não são escolhidos automaticamente.\n\n## `ITEM_CODE_NOT_IN_RUNTIME_TABLE`\n\nO OpenItem tentou usar um code sem contrato `sITEM` source-verificado. Não force. O writer de registro de novo code runtime ainda não foi promovido.\n\n## `LEGACY_AUTHORING_SOURCE_DRIFT`\n\nO arquivo mudou desde o Inspect/hash esperado. Reabra/inspecione o target, revise a nova versão e gere um novo stage.\n\n## `SPP_NON_CANONICAL_LAYOUT` / `SPC_NON_CANONICAL_LAYOUT`\n\nO arquivo não possui o layout canónico provado. Não redimensione/trunque manualmente para “fazer passar”; recupere o formato/corpus correto.\n\n## Publish recusado\n\nCheque:\n\n1. `server_root`;\n2. stage/manifest atual;\n3. `ARM ASSET DEPLOY` na GUI ou confirmação literal na CLI;\n4. target drift;\n5. transaction state.\n\n## Preciso abrir PriTaTor/NPCManager?\n\nNão para os workflows já reescritos. Os EXEs antigos são evidência histórica. Um bloqueio do Python authoring deve ser resolvido provando o contrato, não recorrendo ao EXE como bypass automático.\n