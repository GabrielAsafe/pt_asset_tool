# PATCH NOTES v6

## Gate fechado pelo corpus v5

A análise recursiva do `summit_reverse_samples_v5.zip` separa três níveis que antes estavam misturados:

- 21/25 bundles fecham `INX -> SMD/SMB`;
- 17/25 fecham também todas as texturas observadas na cadeia de runtime;
- 16/25 são **Summit-ready**: INX `MODERN_172`, localization presente, runtime recursivo resolvido e texturas resolvidas.

Os gaps repetidos ficaram reduzidos a famílias específicas:

- `Xmasguy`: `char/npcXms/ChTree_Longbo.inx` ausente;
- `navisko-warehouse`: `char/npc/npc-10.inx` ausente;
- `quest/MN-011`: faltam `MN-012-h`, `MN-012-b`, `MN-012-ob` na família correspondente;
- `Hound`: `char/monster/Hound/houndD_opa.jpg` ausente;
- `priston/acasia-store` fecha o bundle, mas usa INX `LEGACY_120`, portanto não é destino binário nativo do Summit atual.

## Analyzer v6

`analyze_reverse_samples.py` agora percorre o `closure_report.json` a partir de cada `.INF/.NPC`, seguindo:

- `.INI/.IN -> .INX` runtime alias;
- referências INX recursivas (`model`, `motion`, `sub/link/talk link`, `talk motion`);
- referências de textura de SMD/SMB.

O relatório passa a expor `runtime_closure_complete`, `texture_complete`, `current_summit_inx_compatible` e `summit_ready_complete`.

## SPC: semântica confirmada pelo source

O source atual confirma:

- arquivo canônico = 100 × 504 bytes = 50.400 bytes;
- `code != 0` é o gate real usado pelos loops de runtime; em todo o corpus observado os registros ativos usam `0x48470070` (`smTRANSCODE_ADD_NPC`);
- registros `code == 0` podem conter dados antigos/desabilitados e não devem ser chamados de ativos;
- `STG_AREA::OpenNpc()` substitui `dwObjectSerial` por `GetNewObjectSerial()`, então o serial gravado no SPC não é identidade persistente.

## Writer SPC clone-based

`character_bundle_tool.py spc-patch` agora pode criar uma alteração real de SPC com política conservadora:

- exige SPC canônico de 50.400 bytes;
- exige um registro donor ativo (`0x48470070`);
- clona bytes desconhecidos do `smCHAR_INFO`, em vez de sintetizá-los do zero;
- patcha somente nome, model path, server NPC path, coordenadas/ângulos e campos efêmeros conhecidos;
- zera `ModelNameCode2` e os object serial donor-specific;
- em modo automático usa somente um slot **100% zerado**; um registro desabilitado/stale só é reutilizado com `slot_index` explícito;
- grava `spc_patch_manifest.json` com SHA-256 base e patched.

## Installer transacional

A v6 adiciona:

- `mirror-visuals`: replica a cadeia visual validada de `bundle/client` para `bundle/server`;
- `validate-stage`: valida recursivamente o bundle antes de tocar no Summit;
- `install-plan`: compara staging x destinos e classifica `COPY`, `PRESENT_IDENTICAL`, `PATCH`, `CONFLICT`;
- `install-apply`: aplica somente plano seguro; SPC patch exige hash-base idêntico e recebe backup;
- `rollback`: remove cópias feitas pela transação e restaura o SPC salvo, desde que o destino não tenha mudado depois.

Smoke tests cobrem `scaffold -> mirror -> validate-stage -> install-plan -> install-apply -> validate -> rollback` e um patch real clone-based sobre `Ba1.ase.spc` com restauração byte-a-byte do SHA-256 original.
