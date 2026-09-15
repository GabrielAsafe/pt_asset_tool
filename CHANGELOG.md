## 2026-09-14 — 1.0.0 documentation-complete distribution

- Added exhaustive parser-derived CLI reference and complete feature matrix.
- Added dedicated GUI, installation, security, server/enrichment, formats/writers, recovery/deploy, reports and troubleshooting manuals.
- Exported final release gate evidence into the clean distribution so certification remains inspectable without `pt_build`.
- Updated user/developer manuals and documentation index; application code/writer authority is unchanged.
- Production/client/server writes remain disabled by default.

## 1.0.0 — PT Asset Tool certified release (2026-09-14)

- Final physical `release-1-auto --resume`: automatic gate PASS with zero automatic blockers.
- FIX22/FIX24/FIX25 close long-function source evidence, rigid duplicate-object reimport, capability-vs-target-content texture separation, and material domain×family evidence.
- Promotes package/version metadata to 1.0.0 while keeping production/client/server writes locked by default.
- Separates target-content limitations from tool capability; no basename/reference-only recovery authority is introduced.
- Makes `t5_asset_readiness.json` canonical and keeps `t5_effect_readiness.json` as an explicit compatibility descriptor.
- Adds release notes, certification and known-limitations documents plus clean-extract package verification.

## 2026-09-14 — FIX25 material family evidence

- Preserve `asset.family` on every Model0.62 physical material-corpus row.
- Feed physical-family evidence into the existing domain × family material writer coverage contract.
- Fail closed if a future real corpus row loses family metadata instead of silently producing an empty required-family set.
- Surface material `writer_pass_domains` and per-domain `family_coverage` in the compact release summary.
- No client/server game assets are written or recovered by this update.

## 2026-09-14 — FIX24 release capability/target separation

- Preserve physical SMD object indices in rigid reimport expectations so duplicate NodeName chunks are checked independently.
- Mirror the runtime/importer 16-byte INX ModelName matching rule when selecting reimport objects.
- Classify zero-filled and HTTP/HTML error `.tga` payloads as invalid target content, not unsupported proprietary codecs.
- Separate automatic tool capability from target-content readiness in MODEL062 texture presence and proprietary texture corpus gates.
- Keep missing/invalid target assets explicit and fail-closed without basename/reference-only recovery.
- Mark external gameplay/runtime acceptance out of scope for PT Asset Tool 1.0; production publish/restore remains safety-locked.
- No game client/server assets are written by this update.

## 2026-09-14 — FIX22 core corpus/T5 attribution

- Scan complete large legacy runtime functions so T5 `case SKILL_T5_*` bindings are attributable.
- Preserve FIX21 `.pt_*` backup exclusion and `PRELOAD != ACTIVATION` policy.
- Give INX and SMB semantic writer probes independent watchdog budgets.
- Classify legacy source-baseline parse/evaluation gaps as fail-closed SKIP instead of writer regressions.
- Carry Blender `pt_smd_object_index` into rigid writer steps for duplicate-name physical objects.
- No game client/server assets are written by this update.

## 2026-09-14 — FIX21 current-source scan hygiene

- Classify active `Shared/.../*_client.inl` and `*_server.inl` implementations as runtime source.
- Exclude `.pt_*` patch/backup trees from current-source evidence.
- Prevent backup copies from contaminating T5 audio/effect diagnostics.
- Preserve `PRELOAD != ACTIVATION`; only actual runtime Start/audio calls become activation evidence.
- No game client/server assets are written by this update.

## 2026-09-14 — FIX20 adaptive PT Asset Tool 1.0 scope/finalization gate

- External game/runtime behavior is explicitly outside the PT Asset Tool 1.0 release gate.
- Mechanician skill UI remains canonical at `image/Sinimage/skill/Mechanician`; historical `Mecha` remains ignored legacy.
- Package/snapshot certification is refreshed only for the explicit accumulated-delta allowlist.
- No client/server game asset is written by this update.

## 2026-09-14 — FIX19 current Mechanician UI root policy

- Current canonical Mechanician skill-UI root is now `image/Sinimage/skill/Mechanician`, matching the updated project source.
- Historical `image/Sinimage/skill/Mecha` is reported only as ignored legacy; it no longer creates a split/conflict gate.
- Automatic `recover class-ui-alias-only` is disabled for `MECHANICIAN_SKILL_UI`, so legacy `Mecha` can never be used as an automatic write source or destination.
- `wav/Effects/player/Mechanician` remains explicitly outside the UI-root policy.

# 2026-09-14 — Runtime smoke blocker + class UI alias gate

- Manual runtime smoke invalidated the previous “ready for final manual smoke” release-readiness claim: Pikeman Tier 1–4 is now tracked as `RUNTIME-PK-T1T4-01`.
- Original Summit source comparison shows legacy T1–T4 SkillSub/character dispatch code remains present; current client tree retains representative Pike WAV/particle assets. No donor recopy is authorized from this evidence.
- Added read-only `audit class-ui-aliases` with canonical Mechanician skill-UI root `image/Sinimage/skill/Mechanician`; historical `image/Sinimage/skill/Mecha` is ignored legacy and is not a write source.
- Historical `wav/Effects/player/Mechanician` is explicitly excluded from UI alias canonicalization.
- General Asset Census and the web UI expose alias split/alias-only/conflict counts and force `REVIEW_REQUIRED` when the split is present.
- Added regression tests for canonical-only, alias-only/duplicate and conflict cases.
- Release 1.0 remains blocked; T5 source patching is frozen until a clean pre-FIX15 legacy smoke passes.

## 2026-09-11 — RC6.15 / RC6.16 Pre-1.0 Consolidation

- Integrated RC6.15 asset contracts while preserving version 0.13.0.
- Closed offline rigid blockers including ar0n multi-context binding.
- Reconciled all 117 Legacy8 provisional runtime missing edges; proven current-runtime blockers: 0.
- Proved smASE cache fallback for apparent ASE gaps.
- Closed `star06B_04.bmp` as shadowed/nonblocking.
- Staging-proved 8 Mechanician skill-button recoveries.
- Staging-proved 4 historical Missing19 texture recoveries.
- Proved exact-path loading semantics for remaining historical Missing11.
- Remaining Missing11 documented as nonblocking Release 1.0 limitations.
- Deferred TGA (2) and INX semantic/bounds (8) documented as limitations.
- Mixed Physique remains NOT_CERTIFIED / OUT_OF_SCOPE.
- Assassin/Shaman remain out of scope for the eight-active-class 1.0 line.
- RC6.16 consolidated gate PASS with 12 certified overlay files and target unchanged.
- Remaining normal path: final manual smoke -> final certification/package -> 1.0.0.

# Changelog

## 0.13.0 — housekeeping + Asset Enrichment v9 + Field/Effects staging (05/09/2026)

- `vendor/summit_asset_enrichment_v9/` (`v9-fix136`) passa a ser o vendor preferido; v6 fica histórico.
- Aba Servidor / Enrichment ganha Field metadata staging integrado:
  - SPM text draft com encoding/newline preservados;
  - SPP 200×12 structured record draft;
  - SPC ADD_NPC clone-patch only, sem synthetic-from-zero.
- Effects/Particles documentados como `.part` transactional staging + `BLENDER_PREVIEW_APPROXIMATE`.
- Housekeeping move runners RC antigos, writer backups e hotfixes para `app/history/`.
- Documentação/readiness atualizados com a evidência RC6.5.5: 13/13 static representatives `PT_RC6_5_MULTI_VEC3_DIVERGENT`.
- Client/server writes e produção permanecem desativados.

 — PT Asset Tool R14 Integration Regression

Data: 2026-09-04

## RC4 — Blender-aware affine residual

### Correção derivada do rerun físico RC3
- O `failure_summary.json` voltou a reduzir o integration gate a **uma única falha obrigatória**: `affine_animation_selftest`.
- O fatorador SVD da RC3 já reconstruía a matriz fonte com residual ~`1.4e-7`; a falha restante era a avaliação da hierarquia de PoseBones no Blender (`~0.95` no caso SHEAR).
- A causa de design era assumir que `matrix_basis(first) × matrix_basis(second)` equivale diretamente ao target global. Blender aplica rest matrices, `inherit_scale`, local-location e parent pose quando converte channels locais para pose space.
- A RC4 mantém o primeiro fator SVD/TRS no helper, mas deriva o **segundo basis pelo próprio `Bone.convert_local_to_pose(..., invert=True)`**, usando a pose efetiva calculada do helper e o target global original.
- O segundo basis só é aceito se sua reconstrução `LocRotScale` ficar dentro de `2e-5`; caso contrário o bake falha fechado com diagnóstico.
- `rank-deficient + non-TRS` deixa de ser prometido como representação Blender certificada. A matemática SVD continua suportando rank deficiente, mas a camada Blender marca essa combinação como `EXPECTED_BLOCKED`/fail-closed porque inverter um parent singular não é um contrato físico certificado.
- Nenhuma tolerância global de pose foi relaxada.

### Regressão local RC4
- affine math + self-test contracts: **14/14 PASS**.
- regressão ampla sem `fixture_client`, em quatro lotes reproduzíveis: **232/232 PASS**.
- Client/server continuam read-only; `production_authorized=false`.
- Próximo passo continua sendo rerun físico de `integration-regression-auto`.

## RC3 — rank-deficient affine SVD fix

### Correção derivada do rerun físico RC2
- O `failure_summary.json` reduziu o integration gate a **uma única falha obrigatória**: `affine_animation_selftest`.
- O stack trace mostrou `ValueError: cannot normalize near-zero vector` dentro de `_complete_orthonormal_columns`.
- A matriz rank-2 do self-test gerava um autovalor residual positivo em `M^T M` (~ruído numérico), embora `M·v` fosse zero a precisão de máquina.
- `svd_affine_split` agora usa `||M·v||` como magnitude singular operacional para decidir rank/zero axes. O eigensolver continua responsável por `V` e ordenação.
- O residual de reconstrução continua fail-closed; nenhuma tolerância de pose ou matriz foi relaxada.

### Regressão
- Adicionada fixture exata do caso rank-2 da RC2.
- Adicionada segunda matriz rank-2 com shear/scale distintos.
- `test_affine_factor.py`: **7/7 PASS**.
- Lote diretamente afetado (affine, integration, release, server, SMB, TGA): **53/53 PASS**.
- A regressão ampla da RC2 permanece a baseline de **228/228 PASS**; a RC3 altera apenas o fatorador affine, regressões/documentação/manifest.

### Estado
- PENDING_PHYSICAL_RERUN do `integration-regression-auto`.
- Client/server continuam read-only; `production_authorized=false`.

## RC2 — diagnóstico físico compacto + self-test affine alinhado ao Blender

### Integração regression UX
- `integration-regression-auto` agora grava `pt_build/devtest/integration_regression_auto/failure_summary.json` em todas as falhas obrigatórias.
- O gate imprime linhas `FAILURE <gate> ...` e os caminhos de `result.json`/`failure_summary.json` **no fim** da execução, evitando perder o diagnóstico quando os censos server-side têm milhares de rows.
- A CLI deixa de despejar os rows completos de Monster/NPC/Field/OpenItem no terminal; o JSON completo continua preservado em `pt_build`, enquanto stdout mostra status por gate, failures e seleção física.

### Affine animation self-test
- O target sintético do self-test deixou de usar uma multiplicação manual de parent/rest. Ele agora calcula, **antes de inserir o helper**, a pose esperada com `Bone.convert_local_to_pose` (ou fallback equivalente), o mesmo contrato que o pipeline de produção inverte ao derivar `matrix_basis`.
- Isso elimina uma fonte de falso negativo específica do self-test sem relaxar o gate real de pose.
- Em caso de nova divergência Blender, o build report passa a persistir basis fonte, matrices dos dois fatores, matrix esperada, matrix real, `use_connect` e erro máximo antes de abortar.

### Evidência do último rerun recebido
- O parser regression server-side permaneceu PASS: entidades, OpenItems e Fields foram detectados e stage matching funcionou.
- OpenItems com ZHOON ausente ou CODE duplicado continuam REVIEW por conteúdo, não são artificialmente promovidos.
- O rerun ainda terminou em `FIX_REPORTED_INTEGRATION_REGRESSIONS`; a cópia de terminal recebida perdeu o início do JSON com os nomes dos failures. A saída compacta desta RC foi criada precisamente para tornar isso impossível no próximo rerun.
- `client_modified=false` e `server_modified=false` continuaram preservados.

### Validação local RC2
- Regressão sem `fixture_client`: **228/228 PASS** após os novos contratos/summary tests.
- `compileall`: PASS.
- Hashes dos quatro writers raros certificados: preservados.
- Continua RC: Blender/client/server físicos ainda precisam confirmar os gates após esta mudança.

## R14 Integration Regression — atual

### Client / formatos físicos
- Corrige o gate de materiais Model0.62 para ler `MaterialCount` no offset físico correto (`+8`), evitando interpretar `0xCDCDCDCD` como contagem.
- Mantém compatibilidade conservadora com TexLink nulo legacy, padding NUL terminal e trailers opacos preservados byte-a-byte.
- Mantém suporte rigid/static fail-closed para degenerações já existentes no source; degenerações novas continuam bloqueadas.
- Corrige seleção/backfill de representatives static e standalone rigid para escolher apenas assets authorable quando existirem.
- Mantém sibling-SMB rigid/Map condicionado a structural gate PASS.

### SMB / animação
- Corrige layout SMB com bloco `Physique` de `32 × vertex_count`, cobrindo o outlier físico `Effect/PcBangPet/Pet_Phoenimin/Phoenix.smb`.
- Corrige probes de edição SMB para usar o float32 adjacente representável, evitando falso `requested SMB key edit is a no-op` em `char/monster/Darkmage/skullma_A.smb`.
- Distingue support-SMB estruturalmente preservável com parent externo de hierarquia standalone avaliável; não promove o primeiro a pose-space PASS.
- Preserva Actions Blender com Fake User.
- Adiciona diagnóstico de `NON_TRS_SOURCE_BASIS` em pose-space.
- Adiciona fatoração affine `SVD_TWO_BONE_TRS_V1`: helper bone não-deformável + bone original para representar shear/non-TRS sem relaxar tolerâncias.
- Adiciona self-test Blender save/reopen da representação affine, incluindo shear, reflection e rank-deficient/zero-scale.

### Texturas
- Adiciona regressão exata para `weapons/crow2.tga`.
- Protected TGA type-2 sem footer é aceito somente quando o payload fecha exatamente `width × height × bytes_per_pixel`; RLE ambíguo sem footer continua bloqueado.
- Extension Area, Developer Area e footer são preservados quando presentes.

### Summit Server / Asset Enrichment
- Inclui a versão final original do Asset Enrichment v6 em `vendor/summit_asset_enrichment_v6/`, preservando source, audit data e documentação; comandos de escrita do vendor não são expostos automaticamente pela UI.
- `server_root` é uma raiz de primeira classe separada de `client_root`.
- Corrige resolução de paths server-side case-insensitively para reproduzir o comportamento esperado do runtime Windows em host Linux.
- Corrige `name/*.zhoon` relativo ao diretório da definição Monster/NPC.
- Corrige normalização de field companions (`foo.ase.spp/.spc/.spm` → basename lógico `foo`) e preferência SMD/ASE.
- OpenItem usa identidade server-side segura sem inferir igualdade com asset visual do client.
- Mantém `DataServer`, `PostBox`, `LogItemData`, WAR, `cpItem.dat`, `BlessCastle.dat`, `BlackUser`, `FuncBox` e logs fora da superfície de autoria.
- UI `Servidor / Enrichment` integrada com client+server e execução assíncrona dos gates read-only.

### Gates automáticos
- `validate environment-auto`: preflight do client/Blender/Flatpak/paths/hashes/read-only.
- `validate server-design-auto`: inventário e catálogo server-aware.
- `validate physical-regression-auto`: regressão física client focada, com watchdog/progresso por etapa.
- **Novo** `validate integration-regression-auto`: gate mais curto para as regressões ainda abertas: ambiente client/server, self-test affine, animation pose, SMB outliers/corpus, TGA/codecs e parsers server.

### Segurança / política
- Client e server continuam read-only em todos os gates desta distribuição.
- Outputs/candidates são gravados somente em `app/pt_build`.
- `production_authorized=false`, `client_write_authorized=false` e `server_write_authorized=false` permanecem obrigatórios.
- Mixed-Physique real continua exigindo amostra física autêntica antes de qualquer claim 1.0.

### Validação local desta distribuição
- `python3 -m compileall -q .`: PASS.
- Dev tests sem dependência de `fixture_client`: **226 PASS / 0 FAIL** em lotes reproduzíveis.
- Developer docs inventory: PASS.
- JavaScript UI syntax (`node --check`): PASS quando Node disponível.
- Hashes dos quatro writers raros certificados permanecem idênticos ao R14.

### Ainda exige validação física externa
- O self-test Blender affine e os assets reais de pose/SMB/TGA precisam rodar no ambiente Summit real; este container não possui o client/server/Blender Flatpak do usuário.
- Um PASS de `integration-regression-auto` é o próximo gate antes de repetir a regressão física/full release.

## RC1 — fechamento local de produto

- Corrige o teste de contrato do affine helper que procurava um delimitador de função inexistente; o contrato agora inspeciona exatamente `_install_affine_controls`.
- Regressão local completa sem `fixture_client`: **226/226 PASS**.
- `VERIFY_PACKAGE.sh`: PASS.
- Adiciona `START_HERE.md` como entrada curta e beginner-friendly para as duas ferramentas.
- `VERIFY_PACKAGE.sh` agora valida também os SHA-256 dos quatro writers raros certificados.
- Hashes dos quatro writers raros certificados: preservados.
- O último `integration-regression-auto` físico conhecido terminou com apenas dois blockers (`affine_animation_selftest` e `smb_outlier_edit/Phoenix.smb`). Ambos possuem correções nesta RC, mas continuam **PENDING_PHYSICAL_RERUN** até execução no Blender/client Summit real.
- Nenhuma escrita em client/server foi promovida; a RC continua `production_authorized=false`.

## R14 Design Tool + Asset Enrichment — integração de produto (continuação)

### Correções derivadas do último gate físico
- Corrige probe SMB para `-0.0`: o float32 adjacente agora usa o menor subnormal negativo (`0x80000001`) em vez de cair em NaN.
- Corrige a representação affine de helper bones: helpers `SVD_TWO_BONE_TRS_V1` nunca são marcados como `connected`, preservando os 3 graus de liberdade de translação do primeiro fator.

### Integração completa na UI
- Adiciona **Explorador de bundles** para Monster/NPC, Fields e OpenItem, com busca, filtro por estado e filtro por motivo.
- Adiciona detalhe explicativo por bundle, mostrando cadeia server → client e o motivo de REVIEW/BLOCKED.
- Adiciona endpoint read-only `/api/server/report` para consultar os rows dos relatórios já produzidos; não faz rescan e não expõe writers.
- Mostra presença/versão do Summit Asset Enrichment v6 no dashboard.
- Adiciona card de **Readiness Release 1.0** quando existe `release_1_auto/result.json`.
- Adiciona aba **Ajuda / Guias** com modelo mental, estados e runbook recomendado.

### Documentação
- Novo `docs/GUIA_DESIGN_TOOL.md`.
- Novo `docs/GUIA_ASSET_ENRICHMENT.md`.
- Novo `docs/GUIA_WORKFLOW_CLIENT_SERVER.md`.
- Novo `docs/README.md` como índice beginner-friendly.
- `MANUAL_UTILIZADOR.md` e `SUMMIT_GAME_ASSET_ENRICHMENT.md` passam a apontar para os novos guias.

### Asset Enrichment v6 executado pelo Design Tool
- Adiciona adapter seguro `enrichment_vendor_adapter.py` para executar o planner e o grafo originais sem expor `apply`.
- Novos comandos `audit enrichment-plan` e `audit enrichment-graph`; todos os outputs ficam em `app/pt_build/enrichment_vendor`.
- A UI `Servidor / Enrichment` ganha **Gerar plano v6** e **Grafo de dependências v6**.
- Donor roots inexistentes são reportados como indisponíveis; nunca são inventados nem substituídos silenciosamente.

### Release 1 server-aware
- Quando `--server-root` está configurado, `release-1-auto` executa `server-design-auto` antes da matriz física pesada.
- Falha estrutural do ambiente/catalogador server aborta o full gate antes de gastar horas no corpus.
- Bundles server-side em REVIEW/BLOCKED continuam sendo estado de conteúdo, não são convertidos artificialmente em PASS.
- O `release_1_auto/result.json` inclui resumo do server design e mantém `server_write_authorized=false`.

### Distribuição e documentação
- Adiciona `docs/RELEASE_1_READINESS.md` com critérios objetivos para package gate, integration gate, full release gate, Mixed-Physique, runtime acceptance e publish/restore.
- Amplia o guia de Asset Enrichment com o uso dos botões/CLIs integrados de plano e grafo.
- O pacote final remove relatórios de smoke locais antes do ZIP para não herdar resultados produzidos com roots de teste.


## RC6.14 Offline Checkpoint — 2026-09-06

- consolidated ar0nDrac exact INX LinkFile multi-context support;
- rigid context census now physically closes with unresolved=0;
- ar0nDrac remains non-authorable through generic single-skeleton writer;
- animation binding for ar0nDrac remains false;
- fpt-01 TGA 494-declared/495-physical exact off-by-one support retained;
- user runtime policy recorded: assistant must not clone or launch game/client;
- 19 missing textures, ch_tree1, m_fury and 8 INX failures explicitly deferred;
- Mixed Physique remains external sample requirement;
- runtime/game acceptance remains user-manual external requirement;
- product remains 0.13.0 / NOT Release 1.0.

## RC6.14 Mixed Physique scope decision — 2026-09-06

- Release 1.0 scope explicitly sets Mixed Physique to `NOT_CERTIFIED / OUT_OF_SCOPE`;
- real Mixed Physique sample is no longer a Release 1.0 blocker/external request;
- synthetic/candidate pipeline remains preserved and fail-closed;
- physical certification moved to `docs/POST_1_0_BACKLOG.md`;
- runtime/game acceptance remains manual-user external evidence;
- no production/client/server write authorization changed.

## RC6.15 Asset Contracts Integration — 2026-09-06

- ported source-backed asset contracts and staging-only superset aggregation from the 0.17.1 Documentation Handoff;
- added source/reference/donor configuration to CLI/GUI;
- added exact INX MotionInfo SkillCodeList/JobCodeBit/item/event metadata exposure without changing existing decode/frame semantics;
- client/server targets remain read-only and all recovered files materialize only under `app/pt_build`;
- preserved RC6.14 rigid/ar0n, TGA494, Mixed out-of-scope and release-safety policies;
- product version remains 0.13.0 / NOT Release 1.0.

# 2026-09-14 — FIX18 conservative class-UI alias canonicalization

- Added scope-locked `recover class-ui-alias-only` for create-only migration of fresh `ALIAS_ONLY` files into the canonical class skill-UI root.
- Apply requires exact repeated `--expected-path` scope equality against a fresh alias audit.
- Sources must resolve under the configured alias root; targets must resolve under the canonical root and must not already exist.
- Stages bytes under `pt_build`, verifies SHA-256/size, uses temp + `os.replace`, verifies post-write bytes and rolls back created targets on failure.
- Never deletes alias files, never overwrites targets, never touches `DUPLICATE_IDENTICAL` or `DUPLICATE_CONFLICT` rows.
- Current Mechanician audit scope: 8 T5 `ALIAS_ONLY` button files are eligible; the two `TM23 Maximize` conflicts remain explicit `NO_WRITE` review items.
