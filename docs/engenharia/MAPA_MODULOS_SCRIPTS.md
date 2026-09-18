# PT Asset Tool — Mapa de Módulos e Famílias de Scripts

> **Documentação 1.0:** Mapa técnico 1.0. Para índice completo veja `README.md`; para comandos exaustivos veja `CLI_REFERENCE_1_0.md`.

Este documento responde “qual família de `*.py` faz o quê?” e deve permanecer sincronizado com o checkout de desenvolvimento.

---

# 1. Entrypoints

| Arquivo | Papel |
|---|---|
| `pt_asset.py` | aplicação consolidada; intercepta comandos novos e delega core histórico |
| `pt_asset_core_v0_8_9.py` | wrapper do CLI core em `pt_asset_tool.cli` |
| `pt_asset_gui.py` | entrypoint do servidor UI local |
| `update_snapshot_manifest.py` | regenera de forma determinística `SNAPSHOT_SHA256SUMS.txt` após mudanças autorizadas de estrutura/código/docs |
| `pt-asset-gui` | launcher shell |

---

# 2. Core / infraestrutura em `pt_asset_tool`

| Módulo | Responsabilidade |
|---|---|
| `__init__.py` | package marker/version context |
| `__main__.py` | execução package |
| `app_config.py` | client-root persistente e portable discovery |
| `config.py` | `Settings`, paths do project/client/data/work |
| `utils.py` | normalization, hashes, JSON/CSV, atomic writes, subprocess helpers |
| `cli.py` | parser/dispatch do core histórico e ligação dos audits/validators |
| `resolver.py` | resolução segura/case-aware de logical client paths |
| `registry.py` | `Asset`, `AssetRegistry`, families, binding e dependências |
| `registry_bootstrap.py` | gera automaticamente o registry machine-local a partir do client atual em `pt_build/state/asset_registry` |
| `certification.py` | registry append-only de certificações |
| `certified_writers.py` | fonte única dos SHA-256 dos writers certificados da revisão atual |
| `validation.py` | runner/context dos gates visual/structural e import workspace fail-closed |
| `environment_validation.py` | preflight automático rápido do ambiente: client/inventário físico, isolamento e escrita apenas em `pt_build`, hashes certificados; bridge Blender headless/Flatpak é capability opcional e gates Blender continuam bloqueados sem ela; nunca escreve no client |
| `physical_regression_auto.py` | gate físico focado pós-preflight: reexecuta os regressions reais descobertos no primeiro client run (Model0.62 materiais/rigid/static, pose-space, TexLink rigid e SMB/codec) mais representatives atuais; gera `pt_build/devtest/physical_regression_auto/result.json` e nunca escreve no client |
| `rigid_model_info.py` | identidade/classificação semântica multi-INX rigid (skeleton + LOD groups), audit e IDs de contexto |
| `workflow_dispatch.py` | plano fail-closed para generic build |
| `authoring.py` | preflight por canal de authoring Model0.62/Stage0.72, manifest de proveniência e audit de candidates |
| `deployment.py` | contrato legacy single-file de deploy plan/prepare/verify/simulate; continua read-only no client |
| `workspace_bundle_deploy.py` | deploy/restauro transacional de workspaces Model0.62: diff de modelo/texturas, backup completo de contexto, rebuild de codecs legacy, drift gate, replace atómico, post-write verification, rollback e histórico |
| `build_provenance.py` | sidecar `*.build.json` que fixa asset/source/artifact SHA-256, adapter, modo candidate/production e separa autorização do writer de autorização de publish |
| `development_readiness.py` | matriz machine-readable de maturidade e blockers do projeto |
| `semantic_path.py` | classificação conservadora por árvore física; navegação somente, nunca binding/writer evidence |
| `blender_workspace.py` | paths descritivos sob `pt_build/blender_edits` |

---

# 3. Catálogo, entidades, profiles e comparação

| Módulo | Responsabilidade |
|---|---|
| `semantic_census.py` | classificação semântica de corpus físico |
| `entity_catalog.py` | entidades físicas NPC/Monster, preview/evidências/registry enrichment |
| `monster_npc_census.py` | censo agregado e relatórios Monster/NPC |
| `profile_registry.py` | profiles character/LOD canónicos e verificação |
| `profile_candidates.py` | discovery de candidates LOD/profile a partir de evidência registry+INX+SMD, com estado multi-INX e semantic context ID |
| `profile_authoring.py` | resolve profile canónico a contexto exato asset+INX+skeleton+LOD para import Blender; nunca autoriza writer/produção |
| `tree_compare.py` | comparação read-only de árvores, filtros e outputs |
| `binding_coverage.py` | cobertura de binding, incluindo unresolved/config-only |

---

# 4. Motion / INX / SMB

| Módulo | Responsabilidade |
|---|---|
| `motion_core.py` | resolve INX/SMB, motions, action payload, source diagnostics |
| `animation_source_regression.py` | regressão source-side de um par INX/SMB sem Blender |
| `animation_corpus.py` | deduplica contextos INX/SMB registry-proven e executa regressão source-side de corpus |
| `animation_certification.py` | gera fila determinística de contexts/motions para review Blender/humano; não certifica sozinho |
| `inx_writer.py` | candidate MotionInfo writer/preservation-aware patch |
| `smb_writer.py` | candidate track/key writer e parser de layout relaxed |
| `writer_corpus_audit.py` | roundtrip/edit probes em corpus INX/SMB |

Scripts relacionados fora do package:

| Arquivo | Papel |
|---|---|
| `pt_inx_motion_core_v2.py` | parser de referência INX modern/legacy + SMB segment validation |
| `pt_asset_tool/legacy_runtime/pt_smb_motion_evaluator_v1.py` | evaluator source-equivalent de skeleton/motion |

---

# 5. Model0.62 static/object-local/material

| Módulo | Responsabilidade |
|---|---|
| `object_local.py` | parser/evaluator de transforms static/no-Physique |
| `object_local_writer.py` | writer candidato byte-preserving para keys object-local POS/SCALE existentes; sem insert/delete, sem rotação/TmPrevRot e sem autorização de produção |
| `object_local_audit.py` | audit focado de object-local |
| `object_local_corpus.py` | cobertura física de object-local no corpus |
| `multilayer_texlink.py` | semântica de material stages/TexLink chains |
| `texlink_corpus.py` | corpus de multilayer TexLinks |
| `texlink_roundtrip.py` | strict UV witness writer/comparator |
| `static_roundtrip.py` | comparator de roundtrip Model0.62 static |
| `static_authoring_candidate.py` | plano/verificação do saved-Blender static candidate; exige manifest de proveniência e output pt_build-only |
| `rigid_authoring_candidate.py` | plano/comando/verificação do saved-Blender rigid candidate com skeleton/bone closure e output pt_build-only |
| `mixed_authoring_candidate.py` | análise/plano/verificação do Model0.62 Mixed-Physique; dispatch por objeto para adapters rigid/static, preservação de modo Physique e non-target blocks; pipeline sintético aguardando amostra física real |
- `mixed_synthetic_devtest.py`: gate sintético do container Mixed-Physique, exercitando edição combinada rigid/static sem promover evidência física real.
- `mixed_real_devtest.py`: gate físico automático fail-closed para todo Mixed-Physique real presente; resolve contexto de skeleton/model-info de forma determinística, exige structural PASS, edita objetos rigid+static no Blender, reconstrói pelos dois adapters, verifica preservação e reimporta o candidate sem escrever no client.
| `rigid_authoring_evidence.py` | revalida candidate rigid + `*.build.json`, prepara reimport do próprio artefacto para review Blender, cria chave estável profile/LOD/object e separa controlled-edit automático de review humano; nunca promove runtime/produção |
| `rigid_authoring_stress.py` | stress candidate rigid por profile canónico: usa numa única sessão Blender todos os meshes HIGH/DEFAULT/LOW, encadeia o writer por todos os alvos, exige edição observada em cada alvo, preserva non-targets e continua pt_build-only |
| `rigid_profile_devtest.py` | orchestrador de devtest rigid totalmente automático: workspace isolada em `pt_build/devtest`, deformação determinística de todos os meshes HIGH/DEFAULT/LOW, candidate combinado e reimport headless dos três LODs; nunca promove runtime/produção |
| `stage072_authoring_candidate.py` | plano/extract/apply do saved-Blender Stage0.72 candidate; aceita UV-only ou edição geométrica multi-vértice XYZ na grelha 1/256 e reutiliza os strict writers já provados |
| `texture_overlay.py` | prepara overlays de texturas para Blender/Stage |

Scripts externos relacionados:

| Arquivo | Papel |
|---|---|
| `pt_pikeman_smd_material_audit_v1.py` | decoder detalhado de `smMATERIAL_GROUP`/`smMATERIAL` |
| `pt_smd_static_capability_probe_v1.py` | classifica se static pode entrar nos workflows atuais |
| `pt_blender_to_smd_static_v1.py` | strict static writer em cópia |
| `pt_blender_to_smd_free_mesh_v3.py` | rebuild de mesh rigid em escopo artist-oriented |

---

# 6. Physique / importer Model0.62

| Arquivo | Papel |
|---|---|
| `physique_audit.py` | classifica RIGID/STATIC/MIXED e inconsistências |
| `pt_smd_blender_import_v4_generic.py` | dispatcher STATIC/RIGID; MIXED fail-closed |
| `pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py` | parser/importer rigid comprovado, materials, Physique e armature |
| `pt_character_structural_gate_v2.py` | structural gate SMD + skeleton closure |

---

# 7. Stage0.72

| Módulo | Responsabilidade |
|---|---|
| `stage072_corpus.py` | parser completo e corpus profile/flags |
| `stage072_area.py` | reverse/rebuild de StageArea WORD16/DWORD32 |
| `stage072_geometry.py` | geometry witness writer/comparator |
| `stage072_normals.py` | análise de normals |
| `stage072_roundtrip.py` | UV witness writer/comparator |
| `stage072_texture_audit.py` | presença/aliases de texturas e transport failures |

Blender helpers relacionados estão listados na seção Blender.

---

# 8. Rare rigid: leitura e evidência básica

| Módulo | Responsabilidade |
|---|---|
| `rare_support.py` | normalização de raros e protected ship BMP support |
| `rare_outliers.py` | audit de outliers SMD/TGA |
| `rare_rigid_context.py` | parse Physique/context de raros e peer evidence |
| `rare_rigid_binding.py` | binding evidence para rare rigid |
| `rare_rigid_preview.py` | root LOD/preview de rare rigid |
| `rare_rigid_geometry.py` | preflight geométrico |
| `rare_rigid_roundtrip.py` | single-bone witness roundtrip |
| `rare_rigid_multivertex.py` | guarded multivertex transaction core **certificado** |
| `rare_rigid_normal_bridge.py` | normal provenance bridge **certificado** |
| `rare_rigid_extent_bridge.py` | outward extent witness bridge |
| `rare_rigid_multibone_bridge.py` | multibone analysis/bridge **certificado** |
| `rare_rigid_multibone_roundtrip.py` | multibone guarded roundtrip |
| `rare_rigid_edit.py` | artist workspace/write guard **certificado** |

---

# 9. Rare rigid: família “large transaction”

A sequência de nomes registra a maturidade da prova.

| Módulo | Papel |
|---|---|
| `rare_rigid_large_transaction_probe.py` | descobre/testa representatives 5..8 e negativos |
| `rare_rigid_large_interactive_candidate.py` | candidate de transação manual/interativa |
| `rare_rigid_large_saved_blender_candidate.py` | prova candidate usando `.blend` salvo |
| `rare_rigid_large_live_writer_candidate.py` | exercita writer real em certificação isolada, ainda não produção |
| `rare_rigid_large_production_promotion.py` | reexecuta gates e gera policy de promoção |
| `rare_rigid_large_production.py` | production wrapper que exige policy/hashes/evidência |

---

# 10. Rare rigid: família cross-object

| Módulo | Papel |
|---|---|
| `rare_rigid_cross_object_probe.py` | descobre e compara transações entre objects |
| `rare_rigid_cross_object_interactive_candidate.py` | candidate manual |
| `rare_rigid_cross_object_saved_blender_candidate.py` | candidate de `.blend` salvo |
| `rare_rigid_cross_object_live_writer_candidate.py` | live candidate isolado |
| `rare_rigid_cross_object_production_promotion.py` | audit de promoção |
| `rare_rigid_cross_object_production.py` | dispatcher/production guard do escopo promovido |

---

# 11. Rare rigid: família multibone extent

| Módulo | Papel |
|---|---|
| `rare_rigid_multibone_extent_probe.py` | witness/probe de extent com múltiplos bones |
| `rare_rigid_multibone_extent_interactive_candidate.py` | candidate manual |
| `rare_rigid_multibone_extent_saved_blender_candidate.py` | candidate `.blend` salvo |
| `rare_rigid_multibone_extent_live_writer_candidate.py` | live candidate isolado |
| `rare_rigid_multibone_extent_production_promotion.py` | promotion audit |
| `rare_rigid_multibone_extent_production.py` | production dispatcher/policy |

---

# 12. Research `official_*`

Esses módulos são arqueologia/evidência sobre patches/containers oficiais, não dependência de uso normal.

| Módulo | Pergunta de pesquisa |
|---|---|
| `official_character_donor_census.py` | quais assets oficiais podem servir como donors/controles |
| `official_character_physical_compatibility.py` | compatibilidade física entre character payloads |
| `official_container_character_atlas.py` | atlas de character records em containers |
| `official_container_entry_recovery.py` | recuperação de entries de container |
| `official_container_record_index.py` | índice de records/container layout |
| `official_payload_provenance_extraction.py` | extração/proveniência de payloads |
| `official_payload_source_locator.py` | localização da origem de payload |
| `official_update_manifest_pack_correlation.py` | correlação manifest ↔ pack/update |

---

# 13. Forensics `update_tmp_*`

| Módulo | Papel |
|---|---|
| `update_tmp_lha_forensics.py` | analisa estrutura/artefatos LHA em update temp |
| `update_tmp_lh5_decode.py` | experimentos/decoder LH5 para pesquisa de containers |

Eles não devem virar dependência do catálogo/runtime normal sem uma decisão arquitetural explícita.

---

# 14. GUI

| Módulo | Responsabilidade |
|---|---|
| `ui_app.py` | HTTP loopback server, APIs, safety arm, reports, actions |
| `ui_catalog.py` | scan físico, taxonomia, folder/role/extension facets, metadata |
| `ui_capabilities.py` | decide quais ações a GUI pode oferecer por asset/evidência |
| `ui_actions.py` | catálogo de actions e tradução action → CLI command |
| `ui_image.py` | preview adapter BMP/TGA, sem parser paralelo de formato |
| `ui_jobs.py` | subprocess jobs, logs, process group, cancel, review stdin bridge |

A UI não é autoridade de autorização. `/api/action` revalida capability no backend.

---

# 15. Blender helpers em `pt_asset_tool/blender`

## Stage0.72

- `import_stage072.py` — materializa stage no Blender;
- `open_stage072_preview.py` — abre preview;
- `open_stage072_paint.py` — workspace de texture paint;
- `check_stage072_transport.py` — verifica transporte;
- `witness_stage072_uv.py` — cria witness UV;
- `write_stage072_uv.py` — bridge Blender para strict UV writer;
- `witness_stage072_geometry.py` — witness geometry;
- `write_stage072_geometry.py` — bridge Blender para geometry writer.
- `extract_stage072_saved_edit.py` — compara o `.blend` salvo com o Stage0.72 source e extrai somente edits representáveis pelos scanners strict: UV-only ou geometria multi-vértice XYZ na grelha 1/256; qualquer collateral drift fora do contrato é recusado.

## Animation / object-local

- `assemble_player_parts.py` — monta parts/head/body quando comprovados;
- `bake_actions.py` — cria Actions a partir de payload source-side;
- `diagnose_animation_bridge.py` — coleta matrizes para diagnóstico source↔Blender;
- `open_animation_diagnostic.py` — sessão Blender de diagnóstico;
- `bake_object_local.py` — aplica object-local keys no Blender.

## Multilayer TexLink

- `apply_multilayer_texlink.py` — representa stages/material no Blender;
- `witness_multilayer_texlink.py` — alteração controlada;
- `write_multilayer_texlink.py` — passa witness ao writer estrito.

## Rare rigid

- `open_rare_rigid_preview.py`
- `import_rare_rigid_context.py`
- `prepare_rare_rigid_edit.py`
- `open_rare_rigid_edit.py`
- `capture_rare_rigid_edit_baseline.py`
- `canonicalize_rare_rigid_edit.py`
- `extract_rare_rigid_edit.py` — extrai alterações do `.blend` dentro do guard;
- `extract_physique_usage.py` — mede/expõe uso de Physique/vertex groups no Blender;
- `apply_rare_rigid_artist_witness.py` — aplica witness artístico controlado;
- `apply_rare_rigid_transaction_witness.py` — aplica witness transacional small-core;
- `ensure_rare_rigid_transaction_selection.py`
- `verify_rare_rigid_transaction_selection.py`
- `check_rare_rigid_transaction.py`
- `check_rare_rigid_context.py`
- `check_rare_rigid_geometry_witness.py`
- `witness_rare_rigid_geometry.py`
- `ensure_rare_rigid_large_candidate_selection.py`
- `open_rare_rigid_large_candidate.py`
- `ensure_rare_rigid_cross_object_manual_selection.py`
- `open_rare_rigid_cross_object_manual_candidate.py`
- `extract_rare_rigid_cross_object_candidate.py`
- `apply_rare_rigid_cross_object_transaction.py`
- `ensure_rare_rigid_multibone_extent_manual_selection.py`
- `open_rare_rigid_multibone_extent_manual_candidate.py`

## Generic/static witness

- `witness_geometry.py` — deslocamento visual de geometria para validação humana;
- `write_static_witness.py` — bridge para roundtrip static.
- `apply_rigid_profile_devtest.py` — deforma automaticamente todos os meshes de um profile rigid numa cópia `.blend` isolada para stress dev; não altera topologia/material/vertex groups por intenção.
- `check_rigid_profile_devtest.py` — reabre headless os candidates rigid por HIGH/DEFAULT/LOW e verifica presença, contagens, finitude geométrica e weights mínimos antes de marcar o devtest automático como PASS.

---

# 16. Scripts top-level adicionais

| Arquivo | Papel |
|---|---|
| `pt_blender_bind_editable_texture_v2.py` | rebind de texture em cópia do `.blend`; basename/material slot deterministic fallback |
| `pt_character_texture_v1_4.py` | protected BMP baseline/edit/build/publish workspace |
| `pt_protected_tga_v1.py` | protected TGA inspect/decode/build/audit |
| `summit_workspace_asset_bridge_v1_2.py` | register/publish de build para workspace manifest |
| `summit_roundtrip_restore_v4.py` | dry-run/apply restore transacional hardened |

---

# 17. Código histórico e legado

Backups de source, RC runners antigos e versões substituídas não são distribuídos dentro da árvore operacional. O Git é a fonte de histórico desses ficheiros. Código antigo que ainda é necessário em runtime fica explicitamente em `pt_asset_tool/legacy_runtime/` e continua coberto por testes até ser substituído.

Não reintroduza `history/`, `app/history/` ou `history_py/` como dependências do pacote.

---

# 18. Regra para novos módulos

Ao adicionar um novo `.py`, classifique-o explicitamente como uma destas classes:

```text
RUNTIME_CORE
FORMAT_PARSER
READ_ONLY_AUDIT
CORPUS_AUDIT
BLENDER_HELPER
WITNESS_WRITER
CANDIDATE_WRITER
PROMOTION_GATE
PRODUCTION_WRITER
RESEARCH_FORENSICS
LEGACY_REFERENCE
UI
```

O teste `dev_tests/test_developer_docs_inventory.py` exige que módulos de runtime/Blender apareçam neste mapa.

## Release 1.0 automated coverage / semantic devtests (R14)

| Módulo | Responsabilidade |
|---|---|
| `release_1_coverage.py` | matriz executável conteúdo × capacidade da Release 1.0; inventário e seleção determinística de representantes rigid/static/Stage/animation |
| `release_1_auto.py` | runner agregado read-only/`pt_build` para os gates automáticos da 1.0; falha se uma família presente ficar sem prova física/semântica suficiente; Mixed real exige gate físico e um automatic PASS termina em `BLOCKED_EXTERNAL` até runtime/game + promoção/publish/restore |
| `rigid_semantic_devtest.py` | import/edit/build/reimport headless para Model0.62 rigid com INX+skeleton resolvidos, incluindo NPC/monster e variantes multi-INX |
| `standalone_rigid_devtest.py` | probe structural-gate-first e candidate automático para rigid Effect/Map/NPC/Monster sem INX mas com hipótese SMB irmã; adjacência nunca é tratada como binding sem gate físico PASS |
| `rigid_context_census.py` | censo físico corpus-wide de todos os Model0.62 rigid da 1.0 em MODEL_INFO_LOD / RESOLVED_SKELETON / STANDALONE_STRUCTURAL / UNRESOLVED; qualquer resto bloqueia o gate |
| `standalone_animation_devtest.py` | censo corpus-wide de SMB animado por TmFrame+keys e pose-space Blender headless direto do SMB para contextos standalone sem fabricar INX |
| `static_semantic_devtest.py` | devtest automático Model0.62 static com deformação/topologia, build combinado, preservação e reimport |
| `stage072_semantic_devtest.py` | gate automático Stage0.72 com UV + geometria multi-vértice/XYZ na grelha, rebuild e reimport |
| `animation_pose_devtest.py` | gate Blender headless de pose-space para motions INX/SMB comparando matrizes baked contra o payload esperado |
| `object_local_devtest.py` | runner automático das curvas object-local existentes ROT/POS/SCALE e bake Blender, preservando fail-closed para layouts ainda não suportados |
| `texlink_devtest.py` | seleção representativa e roundtrip Blender automático de multilayer TexLink |
| `texture_codec_devtest.py` | roundtrip automático dos codecs BMP/TGA proprietários, incluindo a família ship/chrselect |
| `apply_static_semantic_devtest.py` | helper Blender que aplica alterações determinísticas static, incluindo uma alteração de topologia controlada |
| `apply_mixed_semantic_devtest.py` | helper Blender que aplica deformações determinísticas a targets rigid e static do mesmo container Mixed para o gate físico automático |
| `check_static_semantic_devtest.py` | checker Blender do SMD static candidate reimportado |
| `apply_stage072_semantic_devtest.py` | helper Blender que cria edição Stage0.72 multi-vértice/XYZ representável |
| `check_baked_animation_pose.py` | checker Blender de matrizes pose-space contra o contrato esperado de animação |

A seleção automática dá preferência a testes representativos e falha fechado. Em especial, SMD Model0.62 rigid sem INX não é promovido por similaridade de nome: `standalone_rigid_devtest.py` apenas formula a hipótese de SMB irmã e exige `pt_character_structural_gate_v2.py` PASS antes de importar ou escrever qualquer candidate.

### Model0.62 material candidate / Release 1 automatic material gate

- `model062_material_writer.py`: candidate-only fixed-size edits for verified Model0.62 material scalar/flag fields; preserves every byte outside explicitly authorized 4-byte fields and never authorizes client writes.
- `model062_material_devtest.py`: selects representatives by Release 1 content domain and automatically performs/validates a deterministic material edit under `pt_build/devtest/release_1_auto`.
- `model062_corpus.py`: auditoria física corpus-wide do container SMD Model 0.62; valida parse/layout por domínio e separa rigid/static/mixed sem inferir autorização de escrita.
- `model062_texture_audit.py`: auditoria física corpus-wide das texturas usadas por materiais face-referenced de Model0.62; aliases só quando explícitos no registry.

- `stage072_material_writer.py`: candidate-only fixed-size Stage0.72 smMATERIAL field edits with byte-range verification.

- `stage072_material_devtest.py`: automatic Stage0.72 material edit/verify gate used by Release 1.

## Server-root / design bundle integration (R14 server-aware)

| Módulo | Classe | Responsabilidade |
|---|---|---|
| `server_lifecycle.py` | RUNTIME_CORE / READ_ONLY_AUDIT | classifica paths do Summit Server por ciclo de vida, não apenas por extensão; separa conteúdo estático e 3D compartilhado de persistência, logs, segurança, configs e tooling |
| `server_environment_validation.py` | READ_ONLY_AUDIT | preflight `--server-root`: confirma roots, samples de gameplay/3D, política de exclusão, evidência client↔server por path compartilhado e prova que nenhum sample do server foi alterado |
| `server_inventory.py` | CORPUS_AUDIT | censo read-only da árvore completa do server com contagens por lifecycle/extensão e amostras; nunca lê/escreve payload de persistência como asset e grava somente em `pt_build` |

### Contrato server-aware do Design Tool

O server é uma raiz física independente do client. `GameServer/monster`, `GameServer/npc`, `GameServer/OpenItem`, `GameServer/Field`, `char` e `Field` podem participar de bundles de conteúdo, mas `DataServer`, `PostBox`, `LogItemData`, `BlackUser`, `FuncBox`, `BlessCastle.dat` e `cpItem.dat` são estado/persistência/forensics e ficam explicitamente fora do catálogo de assets editáveis. `Configs/` é visível apenas como configuração em REVIEW. INX/SMD/SMB/ASE server-side usam o mesmo pipeline PT Asset quando um bundle provar que o runtime realmente os referencia; presença por extensão não autoriza cópia nem escrita.
- `server_bundle_census.py` — `CORPUS_AUDIT`: censo read-only de bundles Monster/NPC server-side; extrai apenas referências literais `char/...`/`name/...`, resolve `.INI` lógico para `.INX` em server/client com matching case-insensitive e reporta dependências não resolvidas sem inferir autoria.
- `server_field_census.py` — `CORPUS_AUDIT`: agrupa `GameServer/Field/*.spm/*.spp/*.spc` por basename, classifica SPP 2400 B/600 B e SPC 50400 B, procura stage SMD/ASE por basename e mantém colisões/layouts divergentes em REVIEW.
- `server_item_census.py` — `CORPUS_AUDIT`: lê `GameServer/OpenItem/*.txt` de forma read-only, extrai identidade `CODE`, referências literais ZHOON e conflitos de código; não afirma ainda fechamento de code-map/client catalog/DorpItem.
- `server_design_auto.py` — `READ_ONLY_AUDIT`: gate agregado do catálogo server-aware: preflight do server + bundles Monster/NPC + Field + OpenItem. PASS significa que o catálogo foi construído com política segura; `bundle_closure_complete` é separado e pode permanecer falso sem autorizar escrita.

## Integração Summit Server / Asset Enrichment 1.0

A arquitetura server-aware, os lifecycles excluídos, os bundles Monster/NPC/Field/Item e os gates read-only estão documentados em `docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md`. A especificação original recebida é preservada em `docs/reference/Summit_Server_Arquivos_e_Funcionamento_2026-09-04.docx`.

### Camada Server / Asset Enrichment 1.0

- `pt_asset_tool/server_lifecycle.py` — classifica paths do server por ciclo de vida; separa assets de persistência/log/segurança/config/tooling.
- `pt_asset_tool/server_environment_validation.py` — preflight read-only do `server_root`, com samples compartilhados client↔server e prova de não-modificação.
- `pt_asset_tool/server_inventory.py` — censo completo da árvore do server por lifecycle/extensão/layout; inclui SPP/SPC/INX size families e exclui estado da autoria.
- `pt_asset_tool/server_bundle_census.py` — fecha a primeira camada Monster/NPC: definição, ZHOON, model lógico e resolução INX entre server/client.
- `pt_asset_tool/server_field_census.py` — bundles Field SPM/SPP/SPC e candidatos SMD/ASE, com layouts não-Summit/ambiguidades em REVIEW.
- `pt_asset_tool/server_item_census.py` — OpenItem CODE/ZHOON/duplicatas; catálogo client/DorpItem permanecem explicitamente não inferidos.
- `pt_asset_tool/server_design_auto.py` — gate agregado environment + inventory + entidades + fields + itens.
- `pt_asset_tool/server_ui.py` — resumo seguro para a aba `Servidor / Enrichment` da UI; lê somente relatórios em `pt_build`.
- `pt_asset_tool/ui_app.py` + `ui_static/*` — configuração persistente de `server_root`, dashboard, execução assíncrona dos gates server read-only.
- `server_ui.py` — resumo seguro da camada Server / Asset Enrichment para a UI.
- `server_field_editor.py` — parser + writer staging de Field metadata: SPM texto preservando encoding/newlines, SPP 200×12 structured record edits e SPC clone-patch ADD_NPC fail-closed; outputs só em `pt_build/server_field_editor`.


## Integração regression gate + animação affine (R14.1)

| Módulo | Classe | Responsabilidade |
|---|---|---|
| `affine_factor.py` | RUNTIME_CORE | fatoração determinística de matrizes afins legacy em dois fatores TRS para preservar shear/non-TRS sem relaxar tolerâncias |
| `affine_animation_selftest.py` | READ_ONLY_AUDIT | self-test Blender headless save/reopen da representação affine two-bone; grava somente em `pt_build` e falha fechado se a matriz global não sobreviver |
| `integration_regression_auto.py` | READ_ONLY_AUDIT | gate focado client+server após o primeiro corpus físico: ambiente, self-test affine, pose-space, SMB outliers, TGA outlier/codecs e censos server corrigidos |
| `enrichment_vendor_adapter.py` | READ_ONLY_AUDIT / WORKSPACE | integra o Summit Asset Enrichment v9 Fix136 ao Design Tool para gerar migration plan e dependency graph usando os roots atuais; escreve apenas manifests/graph em `pt_build`, filtra donors inexistentes e não expõe `apply`/install writes |
| `affine_rig_selftest_build.py` | BLENDER_HELPER | constrói em Blender um rig sintético com helper bone não-deformável para provar a decomposição two-bone em shear/reflection/rank-deficient |
| `affine_rig_selftest_check.py` | BLENDER_HELPER | reabre o `.blend` do self-test e verifica matrizes globais após persistência/evaluation |

O gate `validate integration-regression-auto` é deliberadamente menor que `release-1-auto`: não repete material/rigid/static já certificados pelo physical regression anterior; concentra-se nas regressões ainda abertas e na integração server-aware. Um PASS continua sendo evidência automática em `pt_build`, não autorização de produção/client/server write.

## Utilitários operacionais na raiz de `app/` — 1.0.0

| Script | Responsabilidade atual |
|---|---|
| `blender_watchdog.py` | watchdog externo de processos Blender/bwrap; contém hangs sem alterar semântica de assets |
| `cache_status.py` | diagnóstico do incremental audit cache |
| `incremental_audit_cache.py` | infraestrutura/cache read-only para reaproveitar resultados por fingerprint/dependência |
| `pt_asset_cached.py` | wrapper de execução do PT Asset Tool com incremental cache |
| `pt_effect_blender_preview.py` | bridge Blender headless do plano `.part` para `.blend`/renders, sempre aproximado |
| `pt_effect_preview.py` | constrói/valida plano semântico de Effects/Particles e coordena o preview |
| `pt_effect_preview_verify.py` | verifica artefactos/resultados do preview de efeitos |
| `pt_model062_failure_analysis.py` | triage offline dos failures físicos Model0.62 |
| `pt_part_editor.py` | parser/draft transacional de `.part` |
| `pt_part_tool.py` | CLI/utilitário de inspeção/edição `.part` |
| `pt_part_ui.py` | UI local do editor `.part`; staging only, sem publish |
| `pt_rc6_5_5_recover.py` | recupera a evidência física static RC6.5.4/6.5.5 sem rerun quando provada fresca |
| `pt_rc6_5_5_verify.py` | compacta o resultado static físico corrente |
| `pt_release_live_progress.py` | resume progresso de logs `release-1-auto` sem interferir no processo |
| `pt_release_postrun.py` | pós-processamento de resultados de release já produzidos |
| `pt_release_triage_v3.py` | triage compacto de blockers de release, versão corrente |
| `pt_rigid_context_triage.py` | analisa unresolved do rigid context census e padrões de famílias |
| `pt_static_focused_rc6_5_5.py` | harness físico focused da investigação static corrente; histórico de desenvolvimento, não gate de produção |
| `pt_texture_upscale.py` | entry point CLI do pipeline de upscale seguro; outputs/manifests fora do client |
## Apêndice 1.0 — inventário completo de arquivos runtime

Este apêndice é gerado diretamente da árvore 1.0 e garante que todo módulo/script runtime distribuído seja localizável na documentação. Para responsabilidade detalhada, veja `MODULE_REFERENCE_1_0.md` e `ARCHITECTURE_1_0.md`.

### `pt_asset_tool/*.py`

- `affine_animation_selftest.py`
- `affine_factor.py`
- `aggregation.py`
- `animation_certification.py`
- `animation_corpus.py`
- `animation_pose_devtest.py`
- `animation_source_regression.py`
- `app_config.py`
- `authoring.py`
- `binding_coverage.py`
- `blender_workspace.py`
- `build_provenance.py`
- `certification.py`
- `certified_writers.py`
- `class_ui_alias_audit.py`
- `class_ui_alias_canonicalize.py`
- `cli.py`
- `client_manifest_evidence.py`
- `config.py`
- `contract_graph.py`
- `deployment.py`
- `development_readiness.py`
- `enrichment_vendor_adapter.py`
- `entity_catalog.py`
- `environment_validation.py`
- `general_asset_census.py`
- `general_asset_recovery.py`
- `integration_regression_auto.py`
- `inx_writer.py`
- `mixed_authoring_candidate.py`
- `mixed_real_devtest.py`
- `mixed_synthetic_devtest.py`
- `model062_corpus.py`
- `model062_material_devtest.py`
- `model062_material_writer.py`
- `model062_texture_audit.py`
- `monster_npc_census.py`
- `motion_core.py`
- `multilayer_texlink.py`
- `object_local.py`
- `object_local_audit.py`
- `object_local_corpus.py`
- `object_local_devtest.py`
- `object_local_writer.py`
- `official_character_donor_census.py`
- `official_character_physical_compatibility.py`
- `official_container_character_atlas.py`
- `official_container_entry_recovery.py`
- `official_container_record_index.py`
- `official_payload_provenance_extraction.py`
- `official_payload_source_locator.py`
- `official_update_manifest_pack_correlation.py`
- `physical_regression_auto.py`
- `physique_audit.py`
- `player_class_motion_contract.py`
- `player_scale_witness.py`
- `profile_authoring.py`
- `profile_candidates.py`
- `profile_registry.py`
- `rare_outliers.py`
- `rare_rigid_binding.py`
- `rare_rigid_context.py`
- `rare_rigid_cross_object_interactive_candidate.py`
- `rare_rigid_cross_object_live_writer_candidate.py`
- `rare_rigid_cross_object_probe.py`
- `rare_rigid_cross_object_production.py`
- `rare_rigid_cross_object_production_promotion.py`
- `rare_rigid_cross_object_saved_blender_candidate.py`
- `rare_rigid_edit.py`
- `rare_rigid_extent_bridge.py`
- `rare_rigid_geometry.py`
- `rare_rigid_large_interactive_candidate.py`
- `rare_rigid_large_live_writer_candidate.py`
- `rare_rigid_large_production.py`
- `rare_rigid_large_production_promotion.py`
- `rare_rigid_large_saved_blender_candidate.py`
- `rare_rigid_large_transaction_probe.py`
- `rare_rigid_multibone_bridge.py`
- `rare_rigid_multibone_extent_interactive_candidate.py`
- `rare_rigid_multibone_extent_live_writer_candidate.py`
- `rare_rigid_multibone_extent_probe.py`
- `rare_rigid_multibone_extent_production.py`
- `rare_rigid_multibone_extent_production_promotion.py`
- `rare_rigid_multibone_extent_saved_blender_candidate.py`
- `rare_rigid_multibone_roundtrip.py`
- `rare_rigid_multivertex.py`
- `rare_rigid_normal_bridge.py`
- `rare_rigid_preview.py`
- `rare_rigid_roundtrip.py`
- `rare_support.py`
- `registry.py`
- `registry_bootstrap.py`
- `release_1_auto.py`
- `release_1_coverage.py`
- `release_scope.py`
- `resolver.py`
- `rigid_authoring_candidate.py`
- `rigid_authoring_evidence.py`
- `rigid_authoring_stress.py`
- `rigid_context_census.py`
- `rigid_model_info.py`
- `rigid_profile_devtest.py`
- `rigid_semantic_devtest.py`
- `semantic_census.py`
- `semantic_path.py`
- `server_bundle_census.py`
- `server_design_auto.py`
- `server_environment_validation.py`
- `server_field_census.py`
- `server_field_editor.py`
- `server_inventory.py`
- `server_item_census.py`
- `server_lifecycle.py`
- `server_ui.py`
- `skill_contract_census.py`
- `smb_writer.py`
- `source_catalog.py`
- `source_contract_census.py`
- `source_evidence.py`
- `stage072_area.py`
- `stage072_authoring_candidate.py`
- `stage072_corpus.py`
- `stage072_geometry.py`
- `stage072_material_devtest.py`
- `stage072_material_writer.py`
- `stage072_normals.py`
- `stage072_roundtrip.py`
- `stage072_semantic_devtest.py`
- `stage072_texture_audit.py`
- `standalone_animation_devtest.py`
- `standalone_rigid_devtest.py`
- `static_authoring_candidate.py`
- `static_roundtrip.py`
- `static_semantic_devtest.py`
- `superset_aggregation.py`
- `texlink_corpus.py`
- `texlink_devtest.py`
- `texlink_roundtrip.py`
- `texture_codec_devtest.py`
- `texture_upscale.py`
- `texture_overlay.py`
- `tree_compare.py`
- `ui_actions.py`
- `ui_app.py`
- `ui_capabilities.py`
- `ui_catalog.py`
- `ui_image.py`
- `ui_jobs.py`
- `update_tmp_lh5_decode.py`
- `update_tmp_lha_forensics.py`
- `utils.py`
- `validation.py`
- `workflow_dispatch.py`
- `writer_corpus_audit.py`

### `pt_asset_tool/blender/*.py`

- `affine_rig_selftest_build.py`
- `affine_rig_selftest_check.py`
- `animation_session_guard.py`
- `apply_mixed_semantic_devtest.py`
- `apply_multilayer_texlink.py`
- `apply_rare_rigid_artist_witness.py`
- `apply_rare_rigid_cross_object_transaction.py`
- `apply_rare_rigid_transaction_witness.py`
- `apply_rigid_profile_devtest.py`
- `apply_stage072_semantic_devtest.py`
- `apply_static_semantic_devtest.py`
- `assemble_player_parts.py`
- `authoring_session_save.py`
- `bake_actions.py`
- `bake_object_local.py`
- `canonicalize_rare_rigid_edit.py`
- `capture_rare_rigid_edit_baseline.py`
- `check_baked_animation_pose.py`
- `check_rare_rigid_context.py`
- `check_rare_rigid_geometry_witness.py`
- `check_rare_rigid_transaction.py`
- `check_rigid_profile_devtest.py`
- `check_stage072_transport.py`
- `check_static_semantic_devtest.py`
- `diagnose_animation_bridge.py`
- `ensure_rare_rigid_cross_object_manual_selection.py`
- `ensure_rare_rigid_large_candidate_selection.py`
- `ensure_rare_rigid_multibone_extent_manual_selection.py`
- `ensure_rare_rigid_transaction_selection.py`
- `extract_physique_usage.py`
- `extract_rare_rigid_cross_object_candidate.py`
- `extract_rare_rigid_edit.py`
- `extract_stage072_saved_edit.py`
- `import_rare_rigid_context.py`
- `import_stage072.py`
- `open_animation_diagnostic.py`
- `open_rare_rigid_cross_object_manual_candidate.py`
- `open_rare_rigid_edit.py`
- `open_rare_rigid_large_candidate.py`
- `open_rare_rigid_multibone_extent_manual_candidate.py`
- `open_rare_rigid_preview.py`
- `open_stage072_paint.py`
- `open_stage072_preview.py`
- `prepare_animation_workspace.py`
- `prepare_rare_rigid_edit.py`
- `select_animation_action.py`
- `verify_rare_rigid_transaction_selection.py`
- `witness_geometry.py`
- `witness_multilayer_texlink.py`
- `witness_rare_rigid_geometry.py`
- `witness_stage072_geometry.py`
- `witness_stage072_uv.py`
- `write_multilayer_texlink.py`
- `write_stage072_geometry.py`
- `write_stage072_uv.py`
- `write_static_witness.py`

### Scripts Python runtime na raiz de `app/`

- `blender_watchdog.py`
- `cache_status.py`
- `incremental_audit_cache.py`
- `pt_asset.py`
- `pt_asset_cached.py`
- `pt_asset_core_v0_8_9.py`
- `pt_asset_gui.py`
- `pt_blender_bind_editable_texture_v2.py`
- `pt_blender_to_smd_free_mesh_v3.py`
- `pt_blender_to_smd_static_v1.py`
- `pt_character_structural_gate_v2.py`
- `pt_character_texture_v1_4.py`
- `pt_effect_blender_preview.py`
- `pt_effect_preview.py`
- `pt_effect_preview_verify.py`
- `pt_inx_motion_core_v2.py`
- `pt_model062_failure_analysis.py`
- `pt_part_editor.py`
- `pt_part_tool.py`
- `pt_part_ui.py`
- `pt_pikeman_smd_material_audit_v1.py`
- `pt_protected_tga_v1.py`
- `../VERIFY_PACKAGE.sh` — verifier estático/fresh-install do pacote
- `RUN_REGRESSION_FOCUSED.sh` — regressões focadas preservadas
- `pt_release_live_progress.py`
- `pt_release_postrun.py`
- `pt_release_triage_v3.py`
- `pt_rigid_context_triage.py`
- `pt_smd_blender_import_v4_generic.py`
- `pt_texture_upscale.py`
- `pt_smd_static_capability_probe_v1.py`
- `summit_roundtrip_restore_v4.py`
- `summit_workspace_asset_bridge_v1_2.py`
