# PT Asset Tool R14 1.0.0 — Matriz de Funcionalidades

Legenda de segurança: **RO** = read-only no target; **BUILD** = escreve somente em `pt_build`; **EXT** = depende de ferramenta externa como Blender; **LOCKED** = promoção/publish externo não habilitado pela distribuição.

| Área | Funcionalidades 1.0 | Estado | Segurança |
|---|---|---|---|
| Aplicação | status, smoke/self-test, config persistente, doctor, cache/readiness | Certificado | RO/BUILD probe |
| GUI | Catálogo, Entidades, Servidor/Enrichment, Comparar, Tarefas, Relatórios, Ajuda, Configurações | Certificado | RO; ações BUILD exigem arm |
| Catálogo | inventário físico, semântica, filtros, favoritos, preview, inspeção | Certificado | RO |
| Registry/Bindings | SMD/INX/SMB, skeleton/root, LOD/profile, heads/head tiers | Certificado | RO |
| Entidades | Monster/NPC physical catalog e evidence | Certificado | RO |
| Model0.62 | static, rigid Physique, materiais, object-local, TexLink, textura presence | Certificado no escopo documentado | RO/BUILD |
| Mixed Physique | identificação/synthetic/dev candidates | Não certificado para produção 1.0 | fail-closed |
| Stage0.72 | corpus, StageArea, normals, textures, UV/material/geometry roundtrip, preview/paint | Certificado no escopo documentado | RO/BUILD/EXT |
| Motion | INX modern/legacy, SMB tracks, action/motion resolution, semantic corpus | Certificado | RO/BUILD |
| Animação Blender | pose/action preview, diagnostics, selected/core/all actions | Certificado como ferramenta de validação | EXT; sem client write |
| Texturas legacy | BMP protegido, TGA não-standard/protegido, codec corpus, overlay | Capability PASS | RO/BUILD |
| `.part` | parse semântico, draft, diff/verify, corpus mutation, UI, Blender preview aproximado | Desenvolvimento suportado | BUILD/EXT |
| UI de classes | audit de aliases; Mechanician canonical | Certificado | RO; canonicalize explícito e guardado |
| T5 | census assets/effects/audio, source evidence, PRELOAD vs ACTIVATION, reference parity | Diagnóstico/capability certificado | RO |
| Source C/C++ | source contracts, runtime call probes, skill contracts | Certificado como evidência | RO |
| Server | inventory, lifecycle, Monster/NPC bundles, Field, OpenItem, server environment/design gate | Certificado read-only | RO |
| Field metadata | SPM text draft; SPP 200x12; SPC template-clone limitado | Suporte staging | BUILD; server write false |
| Enrichment | vendor v9 Fix136 plan/graph, client/server bundle analysis | Certificado | RO/BUILD reports |
| Aggregation | player-classes, client/server/summit superset, provenance/hashes | Suportado | BUILD only |
| Recovery | CLOSED reachability bundles, expected roots, lineage/hash constraints | Suportado fail-closed | BUILD/staging only |
| Donor forensics | official payload/container/update.tmp workflows | Avançado | RO/BUILD; sem target write |
| Tree compare | filtros, hash, differences-only, JSON output | Certificado | RO |
| Build dispatcher | production route somente quando writer certificado; `--candidate` para research writers | Fail-closed | BUILD only nesta distribuição |
| Deploy | plan, prepare, verify, simulate, state, restore-plan | Certificado como planejamento/transação simulada | BUILD; apply no client não exposto |
| Rare rigid | preview/edit, multivertex, cross-object, multibone extent, policies e reviews | Escopos específicos certificados/promovidos | BUILD; publish separado |
| Certificação | journal JSONL, human reviews, rigid candidate review | Certificado | BUILD metadata |
| Gates | environment, server environment/design, physical/integration regression, release-1-auto | Certificado | RO/BUILD reports |
| Package | snapshot SHA-256, RC6/12 verifier, VERIFY_PACKAGE, clean extract | Certificado | RO |

## Limites deliberados

- `production_authorized=false`, `client_write_authorized=false`, `server_write_authorized=false` no pacote 1.0.
- `WRITER_PROMOTION_AND_PUBLISH_RESTORE` é operação externa/manual e não é habilitada por instalação.
- Falhas de conteúdo do target (texturas ausentes/corruptas) são mantidas como diagnóstico separado da capability do tool.
- Gameplay/runtime Tier 1–4 não é gate da release do PT Asset Tool 1.0.
- Mixed Physique físico permanece fora do escopo certificado de produção.
