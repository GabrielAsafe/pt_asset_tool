# PT Asset Tool R14 1.0.0 — Relatórios, Evidence e `pt_build`

## O que é `pt_build`

É a única área normal de trabalho mutável da ferramenta. Pode conter:

- reports JSON/CSV/TSV;
- devtest/corpus results;
- workspaces Blender;
- candidate artifacts;
- staged deploy transactions;
- backups de operações de build;
- UI state e jobs;
- aggregation/recovery overlays.

Não confunda artefactos de `pt_build` com assets publicados no target.

## Famílias de relatório

- `devtest/environment_auto` — preflight da máquina/client;
- `devtest/server_*` — server gates;
- `devtest/release_1_auto/result.json` — gate consolidado quando executado numa working tree;
- `general_asset_census/` — reachability/recovery/T5 reports;
- `aggregate/` — superset overlays e manifests;
- `server_field_editor/` — drafts SPM/SPP/SPC;
- `blender_edits/` — workspaces/edit evidence;
- deployment manifests — plan/prepare/verify/simulate/state/restore.

O pacote limpo não inclui `pt_build`. O resultado final de Release 1 exportado fica em `docs/release/RELEASE_1_AUTO_FINAL_RESULT.json`; evidência textual adicional pode permanecer em `docs/evidence/`.

## Journal de certificação

`app/certifications/assets.jsonl` é append-only/mutável e por isso consta em `SNAPSHOT_MUTABLE_PATHS.txt`. Cada linha é JSON object.

## Snapshot do pacote

`SNAPSHOT_SHA256SUMS.txt` protege os arquivos estáticos do pacote. `VERIFY_PACKAGE.sh` valida o manifest e os writers certificados.

## Como anexar um relatório a um bug

Inclua:

1. versão (`python3 pt_asset.py --version`);
2. comando completo sem segredos;
3. JSON de output;
4. path lógico do asset/bundle;
5. hashes quando o problema é de bytes/provenance;
6. se Blender estiver envolvido, versão e o artefacto de review em `pt_build`.
