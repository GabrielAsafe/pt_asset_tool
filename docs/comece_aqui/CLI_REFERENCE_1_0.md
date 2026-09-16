# PT Asset Tool R14 1.0.0 — Referência CLI Completa

Esta referência é gerada a partir do parser real da versão 1.0.0. Para operação diária, use também `MANUAL_UTILIZADOR.md`. Todos os comandos abaixo respeitam a regra de segurança da aplicação: o cliente/servidor são read-only por padrão e outputs mutáveis ficam em `pt_build`.

## Opções globais

```text
python3 pt_asset.py [--root ROOT] [--client-root CLIENT] [--server-root SERVER] COMANDO ...
```

- `--root`: raiz de trabalho/projeto; normalmente não é necessário ao executar de `app/`.
- `--client-root`: client Summit a auditar/usar como source físico.
- `--server-root`: server Summit, sempre tratado como fonte read-only pelos fluxos certificados desta distribuição.
- `--version`: imprime `1.0.0`.

## Comandos do parser certificado (117 rotas executáveis)

### `pt_asset.py doctor`

### `pt_asset.py families`

### `pt_asset.py entities list`

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--group` | choices: MONSTER, NPC | — |
| `--q` | default= | — |
| `--limit` | default=200 | — |
| `--json` | nargs=0 | — |

### `pt_asset.py entities inspect`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `group` | obrigatório; choices: MONSTER, NPC | — |
| `entity` | obrigatório | entity display name, folder path or entity key |

### `pt_asset.py profiles list`

### `pt_asset.py profiles inspect`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `profile_id` | obrigatório | — |

### `pt_asset.py profiles lod`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `profile_id` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | obrigatório; choices: high, default, low, all | — |

### `pt_asset.py profiles discover`

discover rigid Model0.62 profile/LOD candidates from registry-proven INX data without creating/authorizing profiles

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--limit` | default=50 | rows printed in JSON; zero means all |
| `--output` | — | optional full/limited JSON report under pt_build |

### `pt_asset.py profiles authoring-plan`

resolve one canonical profile to an exact registry-proven rigid import context; read-only and not writer authorization

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `profile_id` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | choices: auto, high, default, low; default=auto | — |

### `pt_asset.py profiles verify`

verify profile components against the configured client without authorizing writes

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `profile_id` | nargs=? | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--all` | nargs=0 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit physique`

audit canonical Model0.62 files for mixed Physique/static object modes

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit server-inventory`

read-only full server tree census classified by path/lifecycle; persistence, logs and security state are excluded from assets

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--progress-every` | default=10000 | — |
| `--sample-limit` | default=12 | — |

### `pt_asset.py audit server-bundles`

read-only Monster/NPC bundle census: literal model/name refs, logical INI->INX resolution across server/client; no authoring certification

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--progress-every` | default=250 | — |
| `--sample-limit` | default=40 | — |

### `pt_asset.py audit server-fields`

read-only field bundle census: SPM/SPP/SPC companions, canonical Summit sizes and basename stage candidates; ambiguous/mismatched layouts stay REVIEW

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--sample-limit` | default=50 | — |

### `pt_asset.py audit server-items`

read-only OpenItem census: CODE identity, ZHOON presence and duplicate-code conflicts; client catalog/DorpItem closure remains explicitly out of scope

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--progress-every` | default=250 | — |
| `--sample-limit` | default=50 | — |

### `pt_asset.py audit source-contracts`

read-only C/C++ source evidence census: sound maps, player-class job gates and source-proven item/field format relations; no hashes/copies

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback PT_SOURCE_ROOT or project config |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback PT_REFERENCE_SOURCE_ROOT or project config |

### `pt_asset.py audit player-class-contracts`

source-backed 10-class contract coverage graph: UI assets, class audio family, handler sound/particle/animation evidence, runtime migration and transitive .part dependencies; read-only, no hashes/copies

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback PT_SOURCE_ROOT or project config |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback PT_REFERENCE_SOURCE_ROOT or project config |
| `--donor-client` | default=[] | optional read-only donor client root; repeatable (e.g. OFFICIAL=/home/.../old/velho) |
| `--class` | choices: Mechanician, Fighter, Pikeman, Archer, Knight, Atalanta, Priestess, Magician, Assassin, Shaman | audit one class; repeatable; default all 10 |

### `pt_asset.py audit enrichment-plan`

run Summit Asset Enrichment v9 PLAN mode using current client/server roots and only donor roots that exist; writes manifest only under pt_build

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--timeout` | default=180.0 | — |

### `pt_asset.py audit enrichment-graph`

build the Asset Enrichment v9 client/server dependency graph under pt_build; source roots remain read-only

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--skip-client-scan` | nargs=0 | — |
| `--timeout` | default=240.0 | — |

### `pt_asset.py audit class-ui-aliases`

read-only class skill-UI alias audit; detects split roots such as Mecha/Mechanician and never moves/deletes client files

### `pt_asset.py audit general-asset-census`

plan-only general client/server reachability census; separates donor gaps from runtime-reachable dependencies and never writes target roots

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted donors used when omitted |
| `--donor-server` | default=[] | read-only donor server root; repeatable; persisted donors used when omitted |

### `pt_asset.py audit t5-assets`

fresh plan-only Tier-5 effect+audio asset readiness; gameplay functionality is assumed externally, while current asset calls must resolve to target or CLOSED same-lineage bundles

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted donors used when omitted |
| `--donor-server` | default=[] | read-only donor server root; repeatable; persisted donors used when omitted |

### `pt_asset.py audit t5-effects`

compatibility alias for the Tier-5 effect+audio asset readiness audit

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted donors used when omitted |
| `--donor-server` | default=[] | read-only donor server root; repeatable; persisted donors used when omitted |

### `pt_asset.py audit binding-coverage`

summarize rigid binding readiness and unresolved config-only reasons without promoting guesses

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit inx-writer-corpus`

read-only byte-preservation audit for candidate INX MotionInfo writer

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--prefix` | — | client-relative subtree to scan; repeatable (default char/npc + char/monster) |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit smb-writer-corpus`

read-only byte-preservation audit for candidate SMB existing-key writer

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--prefix` | — | client-relative subtree to scan; repeatable (default char/npc + char/monster) |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit inx-writer-edit-corpus`

temp-output corpus probe: perform one allowlisted existing MotionInfo edit per INX without modifying the client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--prefix` | — | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit smb-writer-edit-corpus`

temp-output corpus probe: perform one existing-key edit per editable SMB without modifying the client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--prefix` | — | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit motion-writer-semantic-edit-corpus`

temp-edit registry-proven INX/SMB contexts and require source-side animation evaluation to remain valid; not Blender/runtime certification

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--pair-limit` | default=0 | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit object-local-writer-corpus`

temp-edit existing static Model0.62 object-local ROT/POS/SCALE keys and require byte-preserving reparse; ROT rebuilds cumulative TmPrevRot

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--sample-limit` | default=25 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit rigid-model-info-contexts`

classify rigid assets with multiple INX model-info configs as semantically equivalent or fail-closed ambiguous using full LOD groups + skeleton

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit rigid-authoring-certification-plan`

show canonical profile/LOD/object coverage for verified controlled rigid candidate edits plus human visual reviews; never promotes production

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--profile` | — | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit development-readiness`

summarize current implementation maturity, evidence and remaining blockers; --deep reruns read-only INX/SMB/animation corpus gates

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--deep` | nargs=0 | — |
| `--prefix` | — | deep writer corpus subtree; repeatable (default char/npc + char/monster) |
| `--animation-pair-limit` | default=0 | deep-mode debug cap; zero audits all unique animation contexts |
| `--sample-limit` | default=25 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit release-1-coverage`

cross product of Release 1.0 content domains and required technical capabilities; read-only planning matrix

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit model062-authoring`

classify physical Model0.62 assets by current saved-Blender authoring maturity without writing the client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--include-missing` | nargs=0 | include registry assets whose physical source is absent from the configured client |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit animation-source`

source-side INX/SMB motion regression; diagnostic, not visual certification

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | rigid asset id/path with resolved animation binding |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--mode` | choices: core, all; default=core | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit animation-corpus`

deduplicated source-side regression of registry-proven INX/SMB motion contexts

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--mode` | choices: core, all; default=core | — |
| `--pair-limit` | default=0 | debug/quick-run cap; zero audits every unique physical context |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit animation-certification-plan`

build a deterministic human Blender review queue across proven INX/SMB contexts; does not open Blender or certify automatically

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--context-limit` | default=0 | — |
| `--motions-per-context` | default=3 | — |
| `--sample-limit` | default=50 | — |
| `--output` | — | optional JSON report under pt_build |

### `pt_asset.py audit object-local`

discover static Model0.62 files with serialized object-local transform arrays

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--limit` | default=50 | — |
| `--output` | — | optional JSON report path |

### `pt_asset.py audit object-local-corpus`

physically audit all object-local candidates for hierarchy/segmented subtypes

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing only rare subtype representatives |
| `--per-subtype` | default=3 | — |

### `pt_asset.py audit texlink-corpus`

physically audit Model0.62 multilayer TexLink chains and collect representative SMD/textures

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing representative SMDs plus referenced textures |
| `--per-profile` | default=2 | — |

### `pt_asset.py audit texlink-semantics`

audit exact hTexture->smTexture stage mapping and material stage/form profiles

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing representatives for every semantic profile |
| `--per-profile` | default=2 | — |

### `pt_asset.py audit stage072-corpus`

physically audit all SMD Stage data Ver 0.72 files from the canonical inventory

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing structural/capability representatives |
| `--per-profile` | default=2 | — |

### `pt_asset.py audit stage072-stagearea`

prove StageArea/StageMapRect reconstruction from physical Stage0.72 geometry

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing StageArea boundary representatives |

### `pt_asset.py audit stage072-normals`

audit physical Stage0.72 VectNormal generation families before geometry writing

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing all legacy-normal files plus current controls |

### `pt_asset.py audit stage072-textures`

audit physical presence of textures referenced by face-used Stage0.72 materials

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing SMDs with missing client texture references plus manifest |

### `pt_asset.py audit rare-outliers`

prove the physical families of the 18 canonical reverse-engineering outliers and classify remaining TGA exceptions

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional full JSON report path |
| `--bundle` | — | optional ZIP containing all 18 outliers plus anomalous TGA files and diagnostic manifest |

### `pt_asset.py audit rare-support`

prepare and verify the 16 physically-proven usable rare outliers without modifying client files

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-context`

classify Physique/binding context for the six rare Model0.62 files before Blender preview integration

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |
| `--bundle` | — | optional ZIP with rare SMDs, exact INX/INF context and standard peer controls |

### `pt_asset.py audit rare-rigid-binding`

resolve the six rare rigid Model0.62 files through verified serialized INX LinkFile targets

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |
| `--bundle` | — | optional ZIP with source INX, verified target INX, motion SMB and physical root-model evidence |

### `pt_asset.py audit rare-rigid-preview`

automatically import/check all six proven rare rigid Model0.62 files in their verified Blender binding context

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-geometry`

audit fixed-point Physique inverse loss and single-bone/mixed-bone geometry write preconditions for the six rare rigid files

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-geometry-roundtrip`

certify the first interior single-bone Model0.62 position writer with locked historical normal vector and byte-exact untouched data

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-normal-roundtrip`

certify affected-vertex normal updates through a historical-residual plus current SourceCode SetGNormals delta bridge

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-extent-roundtrip`

certify monotonic outward Model0.62 single-bone bound expansion while preserving historical normal provenance and all non-authorized bytes

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-multibone`

audit at_dragon mixed-bone changed-normal provenance using each affected vertex's own Physique bone transform; no writes

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-multibone-roundtrip`

certify the per-edit guarded at_dragon multibone position/normal writer on 2-, 3- and 4-bone representatives; interior only

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py audit rare-rigid-edit-workflow`

certify atomic 2/3/4-vertex saved-Blender transactions with joint final-geometry normal guards

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional JSON report path |

### `pt_asset.py bindings`

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--mode` | — | — |
| `--limit` | default=100 | — |
| `--discover` | — | resolve config-only binding; verified INX LinkFile is authoritative before legacy discovery fallbacks |
| `--candidate-limit` | default=0 | debug only: cap skeleton-signature groups; zero means all |
| `--full-scan` | nargs=0 | continue even after two distinct skeleton signatures pass |
| `--no-resume` | nargs=0 | ignore previous per-candidate probe state |

### `pt_asset.py aggregate player-classes`

aggregate contract-reachable assets for one or all player classes into pt_build staging overlay

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted donors used when omitted |
| `--class` | choices: Mechanician, Fighter, Pikeman, Archer, Knight, Atalanta, Priestess, Magician, Assassin, Shaman | aggregate one class; repeatable; default all 10 |
| `--plan-only` | nargs=0 | create manifest/review queues without copying recoverable files into the staging overlay |

### `pt_asset.py aggregate client-superset`

stage every target-missing deployable asset/data file from donor clients; preserve variants/reference-only files

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted/autodiscovered donors used when omitted |
| `--plan-only` | nargs=0 | build reports without copying files into staging |

### `pt_asset.py aggregate server-superset`

stage target-missing server data from donor servers; excludes runtime/log state and binaries

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--donor-server` | default=[] | read-only donor server root; repeatable; persisted/autodiscovered donors used when omitted |
| `--plan-only` | nargs=0 | build reports without copying files into staging |

### `pt_asset.py aggregate summit-superset`

combined 10-class contract + client superset + server superset staging run; emits one small reports_bundle.zip

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable |
| `--donor-server` | default=[] | read-only donor server root; repeatable |
| `--plan-only` | nargs=0 | build all reports without copying files into staging |

### `pt_asset.py recover general-closed-bundles`

rerun the general census, require the exact expected CLOSED roots, stage verified donor members and optionally create missing target files

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--source-root` | — | current Summit C/C++ source root; fallback config/discovery |
| `--reference-source-root` | — | EU reference C/C++ source root; fallback config/discovery |
| `--donor-client` | default=[] | read-only donor client root; repeatable; persisted donors used when omitted |
| `--donor-server` | default=[] | read-only donor server root; repeatable; persisted donors used when omitted |
| `--expected-root` | default=[] | exact authorized recovery root; repeatable; --apply refuses to run without this scope lock |
| `--apply` | nargs=0 | create only the missing files in client/server roots after fresh scope/closure checks; never overwrites existing files |

### `pt_asset.py recover class-ui-alias-only`

scope-locked create-only canonicalization of fresh ALIAS_ONLY class skill-UI files; never deletes alias files or touches conflicts

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--expected-group` | obrigatório | exact class UI alias group ID, e.g. MECHANICIAN_SKILL_UI |
| `--expected-path` | default=[] | exact fresh ALIAS_ONLY canonical destination; repeatable; --apply requires exact scope equality |
| `--apply` | nargs=0 | create only the missing canonical files after staging/hash verification; never overwrites or deletes |

### `pt_asset.py assets list`

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--family` | — | — |
| `--ext` | — | — |
| `--visual-only` | nargs=0 | — |
| `--gates` | nargs=0 | show structural/visual/animation certification columns |
| `--limit` | default=50 | — |

### `pt_asset.py asset inspect`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--physical` | nargs=0 | — |

### `pt_asset.py asset authoring`

show per-channel authoring maturity, blockers and generic-import workspace provenance

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

### `pt_asset.py asset motions`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

### `pt_asset.py asset heads`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--limit` | default=50 | — |

### `pt_asset.py asset head-tiers`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | body/armor asset |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--head` | obrigatório | one head asset from the desired appearance family |

### `pt_asset.py asset object-local`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | static Model0.62 asset |

### `pt_asset.py asset texlinks`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | Model0.62 asset with possible chained TexLinks |

### `pt_asset.py asset texlink-semantics`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | Model0.62 asset with chained TexLinks |

### `pt_asset.py asset material-candidate`

candidate-only fixed-size Model0.62/Stage0.72 material field edit; output remains under pt_build

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | Model0.62 or Stage0.72 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--material-index` | default=0 | — |
| `--set` | obrigatório | repeatable allowlisted field edit: texture_type, blend_type, shade, two_side, transparency, self_illum |
| `--output` | — | optional output path; must remain under pt_build |

### `pt_asset.py import`

prepare a reusable Blender workspace through a proven family adapter; never writes the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | supported asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | choices: auto, high, default, low; default=auto | rigid Model0.62 LOD selection |
| `--model-info` | — | exact associated INX path when a rigid asset has multiple non-equivalent model-info configurations |
| `--skeleton` | — | explicit SMB logical client path for rigid Physique assets without a usable model-info skeleton context; structural gate must PASS and context is persisted fail-closed |
| `--profile` | — | canonical character profile id; resolves to an exact INX+skeleton+LOD context and is mutually exclusive with --model-info/--skeleton |
| `--motion` | default=STAND | initial rigid Action state/index; case-insensitive (default STAND) |
| `--load-actions` | choices: all, selected, none; default=all | rigid animation preview Actions: all (default), selected only, or none |
| `--open-mode` | choices: paint, animation; default=paint | open stable paint/edit workspace (default) or separate animation preview |
| `--reset` | nargs=0 | discard the existing import workspace before rebuilding |
| `--no-open` | nargs=0 | prepare the Blender workspace without opening Blender interactively |

### `pt_asset.py build`

generic fail-closed build dispatcher; production routes only to certified writers; --candidate enables explicit pt_build-only static/rigid/mixed/Stage0.72 research writers

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--plan` | nargs=0 | show production adapter plus per-channel authoring decision without building |
| `--candidate` | nargs=0 | run the explicit static/rigid/mixed/Stage0.72 saved-Blender candidate writer; output remains pt_build-only and never authorizes publish |
| `--stress-profile` | nargs=0 | rigid canonical-profile stress build: rewrite every HIGH/DEFAULT/LOW profile mesh from one saved Blender session, require every target to be genuinely edited, and review one combined candidate |
| `--object` | — | target object for --candidate when more than one static/rigid object is eligible; Mixed rewrites its verified eligible set |
| `--require-edit` | nargs=0 | for static/rigid --candidate, fail unless the target object block differs from the source; useful for controlled manual Blender certification tests |
| `--output` | — | optional output path; must remain under pt_build |

### `pt_asset.py deploy plan`

plan provenance/drift/backup/rollback requirements for a pt_build artifact; never writes the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--artifact` | — | candidate artifact under pt_build; omission shows the missing-artifact blocker |

### `pt_asset.py deploy prepare`

prepare a verified pt_build transaction snapshot/backup/staged artifact; still never writes the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--artifact` | obrigatório | artifact under pt_build |

### `pt_asset.py deploy verify`

re-verify a prepared transaction and detect client/backup/staged-artifact drift; read-only

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `manifest` | obrigatório | pt_build deployment transaction.json |

### `pt_asset.py deploy simulate`

prove atomic replace/postwrite/rollback entirely inside the prepared pt_build transaction; never writes the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `manifest` | obrigatório | pt_build deployment transaction.json |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--inject-failure` | choices: postwrite | inject a controlled failure after simulated replace and require rollback |

### `pt_asset.py deploy state`

classify current client bytes as original source, known managed artifact, or unknown drift; read-only

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `manifest` | obrigatório | pt_build deployment transaction.json |

### `pt_asset.py deploy restore-plan`

plan fail-closed restoration from verified backup; apply remains disabled

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `manifest` | obrigatório | pt_build deployment transaction.json |

### `pt_asset.py view stage072`

generate/verify a Stage0.72 preview and open a disposable floating-origin Blender view

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | SMD Stage data Ver 0.72 asset id/path |

### `pt_asset.py view rare-model`

open one of the six proven rare rigid Model0.62 pieces on its physically verified root/skeleton context

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | rare SMD path or unique filename (ar0nass/Cartola*/at_dragon) |

### `pt_asset.py view rigid-candidate`

reimport a verified R12 rigid candidate artifact into a separate Blender review workspace; never writes the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | rigid source asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--artifact` | obrigatório | R12 candidate SMD under pt_build with sibling .build.json |
| `--no-open` | nargs=0 | prepare/verify the candidate reimport review workspace without opening Blender |

### `pt_asset.py edit rare-model`

open at_dragon in the V0.8.9 guarded 1..4-vertex single-object multibone transaction workspace

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | char/tmABCD/at_dragon.smd |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--reset` | nargs=0 | rebuild the persistent edit workspace from the physical source |

### `pt_asset.py write rare-model`

write 1..4 saved at_dragon vertex edits atomically only if the joint final-geometry guard passes

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | char/tmABCD/at_dragon.smd |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--output` | — | optional output SMD path; edit workspace stays under pt_build/blender_edits/rare_model |

### `pt_asset.py write inx-motion`

candidate MotionInfo writer to a new INX under pt_build; never modifies the client

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | client-relative .inx path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--motion` | obrigatório | motion state name (STAND/WALK/...) or motion index |
| `--start` | — | new logical start frame |
| `--end` | — | new logical end frame |
| `--repeat` | — | new repeat DWORD |
| `--key-code` | — | new key-code byte (0..255) |
| `--motion-frame` | — | new signed motion-frame/container slot |
| `--output` | — | optional project-relative output path; must remain under pt_build |

### `pt_asset.py write smb-key`

candidate existing-key SMB track writer to pt_build; no key insertion/deletion

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | client-relative .smb path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--bone` | obrigatório | exact skeleton bone name |
| `--track` | obrigatório; choices: pos, rot, scale | — |
| `--key-index` | obrigatório | — |
| `--x` | — | — |
| `--y` | — | — |
| `--z` | — | — |
| `--w` | — | — |
| `--output` | — | optional project-relative output path; must remain under pt_build |

### `pt_asset.py write object-local-key-candidate`

candidate static Model0.62 existing ROT/POS/SCALE key writer; rotation rebuilds cumulative TmPrevRot; pt_build only, no key insert/delete

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | static Model0.62 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--object-index` | obrigatório | — |
| `--channel` | obrigatório; choices: rot, pos, scale | — |
| `--key-index` | obrigatório | — |
| `--x` | obrigatório | — |
| `--y` | obrigatório | — |
| `--z` | obrigatório | — |
| `--w` | — | required only for --channel rot |
| `--output` | — | optional project-relative output path; must remain under pt_build |

### `pt_asset.py paint stage072`

open Stage0.72 in normalized floating-origin Texture Paint with private texture copies

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | SMD Stage data Ver 0.72 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--stage` | choices: 0, 1, 2, 3, 4, 5, 6, 7; default=0 | TexLink stage to paint (default 0) |
| `--reset` | nargs=0 | discard the existing private paint workspace before opening |

### `pt_asset.py validate structural`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

### `pt_asset.py validate inx-roundtrip`

byte-exact no-op MotionInfo re-encode proof for MODERN_172/LEGACY_120 INX

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | client-relative .inx path |

### `pt_asset.py validate smb-track-roundtrip`

byte-exact no-op rewrite proof for existing SMB rot/pos/scale/PrevRot records

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | client-relative .smb path |

### `pt_asset.py validate stage072-preview`

automatic Stage0.72 Blender geometry/UV/color/light transport gate

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | SMD Stage data Ver 0.72 asset id/path |

### `pt_asset.py validate stage072-roundtrip`

strict Stage0.72 UV writer/roundtrip; preserves geometry, StageArea, materials, lights and opaque suffix byte-identically

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | SMD Stage data Ver 0.72 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--uv-delta` | default=0.03125 | — |

### `pt_asset.py validate stage072-geometry-roundtrip`

strict Stage0.72 geometry witness with normal provenance bridge; rebuilds changed-face VectNormal, StageArea and StageMapRect

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | SMD Stage0.72 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--delta-world` | default=64.0 | intentional X witness move in world units (default 64; must map to 1/256 grid) |

### `pt_asset.py validate visual`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path, or 'next' |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--lod` | choices: auto, high, default, low; default=auto | — |

### `pt_asset.py validate roundtrip`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | static Model0.62 asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--witness-strength` | default=0.08 | intentional radial vertex edit as bbox fraction (default 0.08) |

### `pt_asset.py validate object-local`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | static Model0.62 asset with object-local transform keys |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--fps` | default=30 | — |

### `pt_asset.py validate texlinks`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | Model0.62 asset with two-stage TexLink chains |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | choices: auto, high, default, low; default=auto | — |

### `pt_asset.py validate texlink-roundtrip`

automatic strict NextTex/hTexture + per-layer UV roundtrip witness

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | Model0.62 asset with two-stage TexLink chains |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | choices: auto, high, default, low; default=auto | — |
| `--uv-delta` | default=0.03125 | intentional stage-1 U witness delta (default 0.03125) |

### `pt_asset.py validate animation`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path, or 'next' |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--category` | — | — |
| `--lod` | choices: auto, high, default, low; default=auto | — |
| `--motion` | default=auto | auto, state name (case-insensitive: STAND/stand/Stand), or motion index |
| `--load-actions` | choices: selected, core, all; default=all | all (default, persistent workspace with every active Action), selected (only requested motion), or core (legacy subset) |
| `--fps` | default=30 | — |
| `--head` | default=auto | auto assembles verified heads only for CHARACTER assets; non-character assets default to monolithic/no head; use none or an exact verified head path/id to override |
| `--head-tier` | default=auto | auto/base/0, a/1, b/2, c/3, d/4, or t; suffix only selects art after root compatibility is verified |

### `pt_asset.py validate rigid-profile-auto`

fully automated Blender/dev writer stress for canonical rigid profiles: deterministic edits across HIGH/DEFAULT/LOW, combined candidate build, and headless reimport checks; pt_build only

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--profile` | — | — |
| `--all` | nargs=0 | — |
| `--amplitude` | default=0.12 | deterministic mesh deformation amplitude in Blender units (default 0.12) |

### `pt_asset.py validate environment-auto`

fast automatic environment preflight: client/inventory consistency, pt_build isolation, certified hashes and real headless Blender filesystem bridge; never writes client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--blender-timeout` | default=60.0 | headless Blender environment probe timeout in seconds (default 60) |

### `pt_asset.py validate server-environment-auto`

fast read-only server-root preflight: lifecycle separation, static/shared-3D samples, client/server shared-path evidence, and no server writes

### `pt_asset.py validate server-design-auto`

read-only server design catalog gate: environment + Monster/NPC + field + OpenItem bundle censuses; no server/client writes

### `pt_asset.py validate physical-regression-auto`

focused physical regression gate for fixes discovered by the first complete client run; runs exact historical witnesses plus current per-domain representatives; never writes client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--fps` | default=30 | — |
| `--environment-blender-timeout` | default=60.0 | environment preflight Blender bridge timeout in seconds |
| `--rigid-operation-timeout` | default=180.0 | per Blender/writer operation timeout inside rigid_regressions; timed-out assets fail closed and the batch continues |
| `--smb-sample-limit` | default=25 | per-domain SMB writer regression sample size for MONSTER/EFFECT (default 25) |

### `pt_asset.py validate integration-regression-auto`

focused client+server regression gate for affine animation, exact SMB/TGA outliers and Asset Enrichment bundle parsers; skips already-green material/rigid/static breadth

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--fps` | default=30 | — |
| `--environment-blender-timeout` | default=60.0 | client environment Blender bridge timeout in seconds |
| `--affine-blender-timeout` | default=90.0 | per-operation Blender timeout for the synthetic affine save/reopen self-test |

### `pt_asset.py validate release-1-auto`

single automatic Release 1.0 development gate across real content-domain representatives; Blender/headless + writer/corpus/codec checks, never writes client

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--rigid-per-domain` | default=3 | — |
| `--static-per-domain` | default=3 | — |
| `--object-local-limit` | default=4 | — |
| `--texlink-limit` | default=4 | — |
| `--motion-pair-limit` | default=0 | limit motion semantic edit contexts (0 = full corpus; Release 1.0 PASS requires the full corpus) |
| `--fps` | default=30 | — |
| `--environment-blender-timeout` | default=60.0 | preflight Blender bridge timeout in seconds before the Release 1.0 gate starts |
| `--motion-semantic-timeout` | default=120.0 | per-writer watchdog in seconds for each INX/SMB semantic context (default 120; timeout fails that context and continues) |
| `--resume` | nargs=0 | reuse exact PASS Blender batches plus SHA-validated completed motion-semantic checkpoints in this app/pt_build; physical corpus audits are rerun |

### `pt_asset.py diagnose animation`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--lod` | choices: auto, high, default, low; default=auto | — |
| `--motion` | default=ATTACK | state name or motion index |
| `--load-actions` | choices: selected, core, all; default=selected | — |
| `--fps` | default=30 | — |

### `pt_asset.py diagnose motion-source`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--motion` | default=STAND | state name or motion index |

### `pt_asset.py diagnose motion-segment`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | asset id/path |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--motion` | default=STAND | state name or motion index |

### `pt_asset.py certification list`

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--asset` | — | — |
| `--latest` | nargs=0 | — |
| `--limit` | default=100 | — |

### `pt_asset.py certification record`

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--test` | obrigatório | — |
| `--layer` | default=HUMAN_VISUAL | — |
| `--result` | obrigatório; choices: PASS, FAIL, SKIP | — |
| `--notes` | — | — |

### `pt_asset.py certification rigid-candidate-review`

verify a pt_build rigid candidate + provenance and record automatic controlled-edit evidence plus an explicit human review; never authorizes runtime/production

**Posicionais**

| Argumento | Regras | Descrição |
|---|---|---|
| `target` | obrigatório | — |

**Opções**

| Opção | Regras | Descrição |
|---|---|---|
| `--artifact` | obrigatório | candidate SMD under pt_build; sibling .build.json must contain R12 controlled-edit evidence; run `view rigid-candidate` first |
| `--result` | obrigatório; choices: PASS, FAIL, SKIP | — |
| `--notes` | — | — |

## Comandos da camada consolidada / compatibilidade

Estes comandos são interceptados por `app/pt_asset.py` antes da delegação ao parser core. Alguns são superfícies de investigação avançada preservadas por compatibilidade; não devem ser confundidos com publish no cliente.

| Comando | Função | Escrita permitida |
|---|---|---|
| `status / app-status` | Mostra readiness da aplicação, roots resolvidos, presença de runtime e hashes dos writers certificados. | read-only |
| `smoke / self-test` | Smoke real do pacote: catálogo, registry, GUI contracts, Blender/import bridge, writers e pt_build. Só cria e remove probe em pt_build. | read-only + pt_build probe |
| `ui / gui` | Inicia a aplicação gráfica local. | UI local |
| `compare trees` | Compara duas árvores com filtros de extensão/categoria/path e hash opcional. | read-only |
| `explain TOPIC` | Explica statuses, bindings, structural, visual e roundtrip. | read-only |
| `config show | set-client-root | clear-client-root | set-server-root | clear-server-root` | Configuração persistente de roots usada pela GUI/CLI. | config local |
| `audit monster-npc-census` | Censo físico/semântico Monster/NPC. | read-only/report |
| `audit semantic-asset-census` | Censo semântico adicional preservado da linha consolidada. | read-only/report |
| `audit official-character-donor-census` | Inventário forense de donor oficial para personagens. | read-only/report |
| `audit official-character-physical-compatibility` | Compara compatibilidade física de personagens oficiais. | read-only/report |
| `audit official-container-character-atlas` | Indexa personagens em containers oficiais. | read-only/report |
| `audit official-container-record-index` | Indexa records de containers oficiais. | read-only/report |
| `audit official-container-entry-recovery` | Recuperação/extracção de entry oficial somente para staging/evidência; não publica no target. | pt_build only |
| `audit official-update-manifest-pack-correlation` | Correlaciona manifests/packs oficiais. | read-only/report |
| `audit official-payload-source-locator` | Localiza origem provável de payloads oficiais. | read-only/report |
| `audit official-payload-provenance-extraction` | Extrai proveniência de payload oficial previamente localizado. | read-only/report |
| `audit update-tmp-lha-forensics` | Forensics de containers/update.tmp LHA. | read-only/report |
| `audit update-tmp-lh5-decode` | Decode/validação LH5 baseado no relatório forense. | pt_build/report |
| `audit rare-rigid-large-transaction-workflow` | Probe de transação rare rigid large. | pt_build only |
| `audit rare-rigid-large-saved-blender-workflow` | Prova de candidato salvo no Blender. | pt_build only |
| `audit rare-rigid-large-live-writer-candidate-workflow` | Writer candidate em cópia. | pt_build only |
| `audit rare-rigid-large-production-promotion-workflow` | Audita a promoção de política do writer rare rigid; não equivale a client publish. | policy/report |
| `artist-test rare-model-large-candidate ASSET` | Workspace interativo de candidato large. | pt_build/Blender |
| `audit rare-rigid-cross-object-probe-workflow` | Probe cross-object. | pt_build only |
| `audit rare-rigid-cross-object-saved-blender-workflow` | Prova cross-object salvo no Blender. | pt_build only |
| `audit rare-rigid-cross-object-live-writer-candidate-workflow` | Writer cross-object candidate. | pt_build only |
| `audit rare-rigid-cross-object-production-promotion-workflow` | Audita promoção cross-object, sem publicar no client. | policy/report |
| `artist-test rare-model-cross-object-candidate ASSET` | Workspace manual cross-object. | pt_build/Blender |
| `audit rare-rigid-multibone-outward-extent-probe-workflow` | Probe multibone outward extent. | pt_build only |
| `audit rare-rigid-multibone-outward-extent-saved-blender-workflow` | Prova saved-Blender do extent. | pt_build only |
| `audit rare-rigid-multibone-outward-extent-live-writer-candidate-workflow` | Candidate writer do extent. | pt_build only |
| `audit rare-rigid-multibone-outward-extent-production-promotion-workflow` | Audita promoção do extent. | policy/report |
| `artist-test rare-model-multibone-outward-extent-candidate ASSET` | Workspace manual do extent. | pt_build/Blender |
| `audit rare-rigid-selection-workflow` | Audita seleção guardada de rare rigid. | pt_build/report |
| `audit rare-rigid-edit-entry-workflow` | Audita entrada no workspace persistente de edição. | pt_build/report |
| `audit release-consolidation-workflow` | Audita/exporta consolidação histórica da aplicação. | pt_build/report |

> Observação: `write rare-model` também possui dispatch consolidado para as políticas rare-rigid promovidas. Mesmo quando o writer informa `production_authorized=true` para o **formato/escopo do artefacto**, o próprio comando não autoriza publish no cliente; `client_modified=false` continua sendo a fronteira desta distribuição.
