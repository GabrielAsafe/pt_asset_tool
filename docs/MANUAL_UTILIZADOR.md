# PT Asset Tool R14 1.0.0 — Manual Completo do Utilizador

**Estado:** release 1.0.0 certificada, safety-locked.  
**Público:** artista técnico, designer, integrador de assets, QA e operador da ferramenta.  
**Referência exaustiva de comandos:** `CLI_REFERENCE_1_0.md`.

## 1. O que a ferramenta faz

O PT Asset Tool cataloga, inspeciona, valida, compara e prepara alterações de assets Summit Tale/Priston Tale sem tratar o client/server como workspace editável. A 1.0 integra:

- catálogo físico e semântico;
- registry, bindings, profiles/LOD, heads e motions;
- Model0.62 static/rigid, materiais, object-local, TexLink e texturas;
- Stage0.72 geometry/UV/material/normal/texture;
- INX/SMB e animação;
- BMP/TGA legacy;
- `.part`/effect preview;
- Blender import/view/edit/paint/review;
- Monster/NPC/Field/Item server census;
- Asset Enrichment v9;
- source contracts e T5 asset/effect/audio diagnostics;
- aggregation, recovery fail-closed e donor provenance;
- build candidates e deployment planning/simulation;
- GUI, jobs, reports e certification journal;
- gates environment/physical/integration/release;
- package verification por SHA-256.

## 2. Regra de segurança

O target client e server são read-only por padrão. Edição/build gera cópias em `app/pt_build`. A distribuição não habilita publish/restore real.

Estados finais da 1.0:

```text
automatic_gate_status = PASS
automatic_blockers    = 0
production_authorized = false
client_write_authorized = false
server_write_authorized = false
```

## 3. Instalação

Leia `INSTALLATION_QUICKSTART_1_0.md`. Resumo:

```bash
./VERIFY_PACKAGE.sh
cd app
python3 pt_asset.py --version
python3 pt_asset.py config set-client-root "/path/cliente"
python3 pt_asset.py config set-server-root "/path/Servidor"
python3 pt_asset.py validate environment-auto
```

## 4. Conceitos de evidência

| Nível | O que prova | O que não prova |
|---|---|---|
| Catálogo/Inspect | identidade física/semântica | writer/publish |
| Structural | layout/invariantes do formato | aparência/runtime |
| Binding | relação model→config→skeleton/motion | writer |
| Visual | transporte visual no Blender | byte preservation |
| Roundtrip | reconstrução/edição controlada em cópia | publish |
| Writer | geração de artefacto no escopo certificado | client write |
| Publish | substituição no target | não habilitado no pacote 1.0 |

Use `explain statuses`, `explain bindings`, `explain structural`, `explain visual` e `explain roundtrip`.

## 5. Configuração

```bash
python3 pt_asset.py config show
python3 pt_asset.py config set-client-root PATH
python3 pt_asset.py config clear-client-root
python3 pt_asset.py config set-server-root PATH
python3 pt_asset.py config clear-server-root
```

Roots também podem ser passados como `--client-root` e `--server-root`.

## 6. GUI

```bash
python3 pt_asset_gui.py
```

Abas: Catálogo, Entidades, Servidor/Enrichment, Comparar, Tarefas, Relatórios, Ajuda/Guias e Configurações. Veja `GUI_MANUAL_1_0.md`.

## 7. Catálogo, assets e entidades

### Assets

- `assets list`: listar/filter;
- `asset inspect`: inspeção;
- `asset authoring`: canais/gates de authoring;
- `asset motions`: motions;
- `asset heads` / `head-tiers`: partes compatíveis;
- `asset object-local`: transforms;
- `asset texlinks` / `texlink-semantics`: materiais multicamada;
- `asset material-candidate`: material edit candidate.

### Entidades

`entities list` e `entities inspect` trabalham com Monster/NPC e evidência física/registry.

### Profiles

`profiles list/inspect/lod/discover/authoring-plan/verify` administram contexts canónicos de character/LOD sem promover guesses.

## 8. Audits

A família `audit` é a superfície mais ampla. Consulte `CLI_REFERENCE_1_0.md` para todos os argumentos.

Principais grupos:

- physique/model062/material/texture/object-local/TexLink/Stage0.72;
- INX/SMB writer corpus e semantic edit corpus;
- animation source/corpus/certification plan;
- server inventory/bundles/fields/items;
- source contracts/player-class contracts;
- enrichment plan/graph;
- class UI aliases;
- general asset census/T5;
- rare rigid contexts/geometry/multibone/edit workflow;
- release coverage e development readiness.

## 9. Model0.62

Antes de editar, rode structural/binding e o audit/corpus aplicável. Static e rigid Physique têm pipelines distintos. Mixed Physique físico não é writer de produção certificado na 1.0.

Materiais são validados por família física/domínio. TexLinks preservam a cadeia e UV por layer. Object-local writer edita keys existentes; não inventa animação/keys.

## 10. Stage0.72

Use:

- `audit stage072-*` para corpus;
- `validate stage072-preview`;
- `validate stage072-roundtrip` para UV;
- `validate stage072-geometry-roundtrip` para geometry;
- `view stage072`;
- `paint stage072`.

Outputs ficam em pt_build. Veja `FORMATS_WRITERS_1_0.md`.

## 11. Motion / INX / SMB / animação

- no-op roundtrip: `validate inx-roundtrip`, `validate smb-track-roundtrip`;
- candidate writers: `write inx-motion`, `write smb-key`;
- corpus: `audit inx-writer-*`, `audit smb-writer-*`, `audit motion-writer-semantic-edit-corpus`;
- visual: `validate animation`;
- diagnostics: `diagnose animation`, `motion-source`, `motion-segment`.

`--load-actions selected|core|all` controla ações carregadas no Blender.

## 12. Blender

`import ASSET` cria workspace reutilizável com adapter provado. `view` é preview; `edit/paint` são workspaces; `write/build` produzem artefactos. Blender nunca é tratado como autoridade dos bytes originais: o writer/reparser faz a validação final do artefacto.

## 13. Build

```bash
python3 pt_asset.py build ASSET --plan
python3 pt_asset.py build ASSET --candidate
```

`--plan` explica dispatch. `--candidate` só usa research writers explicitamente pt_build-only. Production route sem writer certificado é bloqueada.

## 14. Deploy seguro

```bash
python3 pt_asset.py deploy plan ASSET --artifact FILE
python3 pt_asset.py deploy prepare ASSET --artifact FILE
python3 pt_asset.py deploy verify MANIFEST
python3 pt_asset.py deploy simulate MANIFEST
python3 pt_asset.py deploy state MANIFEST
python3 pt_asset.py deploy restore-plan MANIFEST
```

Nenhum desses comandos é apply geral no client. Veja `RECOVERY_AGGREGATION_DEPLOYMENT_1_0.md`.

## 15. Aggregation e recovery

Use `aggregate ...` para overlays e `recover general-closed-bundles` para recovery scope-locked. Nunca substitua essa lógica por cópia manual baseada em nome.

## 16. Server / Enrichment

Configure `server-root`, rode server environment/design e use os censos. A GUI integra bundle explorer e Field Metadata Editor. Veja `SERVER_ENRICHMENT_1_0.md`.

## 17. T5 / source evidence

`audit t5-assets` é o audit canónico. Ele separa current runtime binding, reference evidence, audio/effect diagnostics e PRELOAD vs ACTIVATION. Reference-only não é autoridade de recovery.

## 18. UI de classe

Mechanician canónico: `image/Sinimage/skill/Mechanician`. O antigo `Mecha` é legacy ignorado na política atual e não deve ser fonte automática de write/recovery.

## 19. Rare rigid

A ferramenta preserva uma linha de workflows de rare rigid com seleção, edit, multivertex, cross-object e multibone extent. São superfícies estreitas e fortemente guardadas. Use os comandos normais `view/edit/write rare-model` e só use workflows `audit rare-rigid-...workflow` quando estiver auditando a política/certificação avançada.

## 20. Certificação

- `certification list` consulta journal;
- `certification record` registra review;
- `certification rigid-candidate-review` valida candidate + provenance + review humano.

Journal: `app/certifications/assets.jsonl`.

## 21. Gates automáticos

- `validate environment-auto` — máquina/client;
- `validate server-environment-auto` — server root;
- `validate server-design-auto` — server bundle design;
- `validate physical-regression-auto` — regressões físicas focadas;
- `validate integration-regression-auto` — regressões client+server;
- `validate release-1-auto` — gate consolidado da 1.0.

Um resultado global `BLOCKED_EXTERNAL` com `automatic_gate_status=PASS` significa que a capability passou e existe ação operacional externa bloqueada por segurança.

## 22. Texturas e conteúdo do target

Capability de codec e readiness de conteúdo são métricas diferentes. A 1.0 mantém missing/corrupt texture paths visíveis. Não existe pathname whitelist para mascarar payload inválido.

## 23. Efeitos `.part`

Há editor/draft/preview auxiliar (`pt_part_*`, `pt_effect_*`). O preview Blender é aproximado e não certifica equivalência do runtime.

## 24. Relatórios

Tudo mutável vai para `pt_build`; veja `REPORTS_OUTPUTS_1_0.md`. A GUI Relatórios faz descoberta recursiva dos JSONs.

## 25. Diagnóstico e suporte

Veja `TROUBLESHOOTING_1_0.md`. Primeiro use `doctor`, `status`, `smoke`, `config show` e o gate environment adequado.

## 26. Referência completa

- `FEATURE_MATRIX_1_0.md` — todas as áreas de capability;
- `CLI_REFERENCE_1_0.md` — todas as rotas CLI certificadas + compatibilidade;
- `GUI_MANUAL_1_0.md` — GUI;
- `FORMATS_WRITERS_1_0.md` — formatos/writers;
- `SERVER_ENRICHMENT_1_0.md` — server;
- `RECOVERY_AGGREGATION_DEPLOYMENT_1_0.md` — recovery/build/deploy;
- `SECURITY_SAFETY_1_0.md` — fronteiras de escrita;
- `ARCHITECTURE_1_0.md` / `MODULE_REFERENCE_1_0.md` — engenharia.
