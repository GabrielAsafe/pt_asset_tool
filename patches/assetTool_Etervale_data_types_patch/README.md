# PT Asset Tool R14 1.0.0

PT Asset Tool is an evidence-driven Priston Tale asset and legacy-content engineering toolkit. It combines client inventory/inspection, server-aware enrichment, source-backed Legacy Management authoring, semantic name mapping, reversible quarantine, texture workflows, and transactional publication.

## Language

The first-party UI and default operational documentation are English as of V2.10.

Game display names stored in the semantic authoring catalog remain in their source game locale. Internal IDs, runtime codes, paths, hashes, and raw evidence are never translated.

English documentation starts at:

```text
docs/en/README.md
```

## Verify the package

```bash
./VERIFY_PACKAGE.sh
```

## CLI

```bash
cd app
python3 pt_asset.py --help
```

## UI

```bash
cd app
python3 pt_asset_gui.py
```

The UI is read-only by default. Workspace/build staging requires a temporary arm. Client/server publication uses separate explicit transactional authorization, hash preflight, backup, post-write verification, and restore/rollback.

## Dependencies

```bash
cd app
python3 pt_asset.py dependencies
```

## Runtime data

Generated/user runtime data belongs under `app/pt_build` and related local workspaces. Runtime data is excluded from the static package snapshot and must not be removed as part of normal release hygiene.

## Asset retention and quarantine

Retention distinguishes generic graph linkage from strong-root reachability. `ORPHAN_CANDIDATE` and Q1 review scores are not delete authority.

Quarantine remains reversible:

- Q0 — narrow documented-invalid zero-linkage orphans;
- Q1 — root-unreachable components ranked for review;
- manual Q1 component quarantine — exact component, strict eligibility, physical hashes, explicit confirmation, transactional restore.

There is no automatic delete authority.

## Summit canonical authoring (V2.11)

Authoring authority now comes from the configured Summit source tree under `Content/canonical/**`. The application loads it through `SummitCanonicalContentProvider`, builds Semantic Catalog V2 live, validates typed edits, compiles the canonical pack set in a complete staging tree, validates hashes, and publishes through explicit source/packs phases.

`priston_asset_name_map_v1.json` is retained only as a display-alias / pt-BR friendly-name / ambiguity / migration overlay. It no longer decides which Item, Monster, NPC, or Map entities exist.

In canonical mode, legacy Item/Monster/NPC/SPM/SPP/SPC formats remain inspect/import/compare/diagnostic inputs. Persistent authoring goes through canonical JSON and rebuilt packs. CLIENT and SERVER map profiles remain separate, dynamic field 53 is an explicit legacy exception, and localization production publish stays fail-closed until the runtime bridge validator passes.

See `docs/en/topics/SUMMIT_CANONICAL_SOURCE_V211.md`.

## Summit asset migration / cook coverage audit

The read-only `summit-canonical-assets` and `summit-asset-migration` audits import `SourceCode/Content/canonical/**/*.json` as asset evidence, compare it with current C/C++ asset literals and UI text candidates, and emit a deterministic runtime cook/package plan. Normal `asset-retention` also consumes the canonical strong roots so canonical assets cannot fall into orphan/quarantine review simply because their legacy source literal disappeared.

See `docs/tematicos/SUMMIT_ASSET_MIGRATION_AUDIT.md` and `RUN_SUMMIT_ASSET_MIGRATION_AUDIT.sh`.


### Material Lab pós-upscale (sem repetir upscale)

A versão atual inclui `app/pt_asset.py texture-material` para restaurar imagens à resolução atual (incluindo DEDXT 1× com pesos externos/verificados), gerar normal/height e demos parallax **offline**, fazer auditoria read-only de meshes e revisão de candidatos por hash. A interface inclui **Client / Enrichment → Texture Enhancement → Material Lab**. Não há publicação automática de mapas, nem alteração dos shaders do cliente. Consulte [a documentação do Material Lab](docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md) para comandos e limites do motor.

Material Lab pós-upscale: instalação do patch cumulativo e manual detalhado em `docs/tematicos/MATERIAL_LAB_GUIA_FINAL_PATCH_CUMULATIVO.md`. O processo 1× não repete o upscale e a exportação `export-approved` destina-se apenas a testes offline; mapas/meshes in-game continuam não certificados.

## Etervale data-format tooling import

The legacy canonical data-format inspectors, compilers, JSON schemas and ASE readers
from the previous source are now included under
`app/pt_asset_tool/legacy_data_tools/`, with safe CLI entrypoints via
`python3 app/pt_asset.py data-types --help`. The old `Content/` data is **not**
automatically installed or treated as an Etervale runtime source. Native Etervale
C# readers remain in their project and can be discovered through the single
`Etervale-git` repository root. See `docs/etervale/DATA_TYPE_TOOLS.md`.
