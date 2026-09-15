# Continuação autónoma — R12 — 2026-09-02

A R12 parte do primeiro **controlled edit real em Blender** reportado para o generic rigid saved-Blender candidate. Nenhum writer foi promovido, runtime/game não foi certificado, e client-write/deploy apply continuam bloqueados.

## Evidência real recebida da R11

O utilizador executou:

```bash
python3 pt_asset.py build "char/tmABCD/MfbC01.smd" \
  --candidate --object MbmC01 --require-edit
```

no profile `priestess_c01_m5`, LOD `default`, depois de editar `MbmC01` no Blender real.

O resultado reportado foi:

- candidate `PASS` / `CANDIDATE_PT_BUILD_ONLY`;
- `edit_observed=true` e `edit_required=true`;
- `non_target_changed=[]`;
- `unknown_physique_bones=[]`;
- `errors=[]`;
- 86 vertices / 138 faces / 138 TexLinks antes e depois;
- input/output com 290229 bytes;
- 14 blocos de objetos não alvo byte-idênticos;
- `max_vertex_fit_error=0.0`;
- source SHA-256 `9ec6be4cc148125e56156b5a35da0f2939c2e0b52f17103c9253bfe8bb87120b`;
- candidate SHA-256 `6ec9b5273cde73669972c1819851b6503ce64c2517671fdcb43c5f71fb653704`;
- production/client-write permaneceram `false`.

O log integral foi preservado em `evidence/manual_r11_rigid_candidate_2026-09-02.txt` (SHA-256 `e870268ae2c6b9c5e723536a0d6f7cfbb8413d12c44be24d2ff07b03d3ede2af`). Como o artefacto SMD e o sidecar `*.build.json` não foram enviados junto com o log, esta prova é registrada como `PASS_REPORTED`, não como artefacto revalidado dentro do snapshot.

## Implementado em R12

### 1. Provenance candidate enriquecida

Candidate builds passam a gravar no `*.build.json`, além dos hashes já existentes:

- target object;
- LOD/profile selecionado;
- `edit_observed` / `edit_required`;
- status/erros do verifier;
- non-target drift;
- bones Physique desconhecidos;
- target structural evidence;
- writer/tool e output SHA;
- source/output counts;
- número de non-target blocks preservados;
- max vertex fit error.

Isso permite validar o controlled edit depois sem depender de terminal copiado.

### 2. `rigid_authoring_evidence.py`

Novo módulo fail-closed para:

- revalidar artifact + `*.build.json` + source atual + selected context;
- exigir `CANDIDATE_RIGID`, build PASS, edição realmente observada, nenhum non-target drift, nenhum bone desconhecido e nenhum verifier error;
- restringir de novo o target ao LOD salvo;
- gerar `RIGIDCTX-*`, identidade estável asset + INX + SMB + LOD + profile + object.

### 3. Review visual sobre o **output candidate**

Novo comando:

```bash
python3 pt_asset.py view rigid-candidate <asset> --artifact pt_build/.../candidate.smd
```

Ele revalida o candidate e reimporta o próprio SMD de saída com o INX/skeleton/LOD pinned num workspace separado:

```text
pt_build/candidate_review/<asset>/<RIGIDCTX-...>/
```

O review manifest fixa candidate SHA, review `.blend` SHA e contexto. Se candidate/review mudar depois, a certificação é recusada.

### 4. Review/certificação estruturada, ainda abaixo de runtime

Novo comando:

```bash
python3 pt_asset.py certification rigid-candidate-review <asset> \
  --artifact pt_build/.../candidate.smd \
  --result PASS|FAIL|SKIP
```

Ele exige primeiro um review workspace válido e grava **duas evidências separadas**:

- `BLENDER_CANDIDATE`: automatic controlled-edit evidence, somente depois de revalidar bytes/provenance/context;
- `HUMAN_VISUAL`: resultado explícito do review humano do candidate reimportado.

Mesmo `PASS + PASS` continua com:

```text
runtime_authorized=false
production_authorized=false
client_write_authorized=false
```

### 5. Matriz profile/LOD/object

Novo audit:

```bash
python3 pt_asset.py audit rigid-authoring-certification-plan
python3 pt_asset.py audit rigid-authoring-certification-plan --profile priestess_c01_m5
```

A matriz distingue:

- `external_real_blender_reported` — log real preservado, não revalidado localmente;
- `controlled_edit_proven` — artifact/provenance R12 revalidado;
- `human_review_result`;
- `context_pass` — somente automatic PASS + HUMAN_VISUAL PASS para o mesmo profile/LOD/object e o mesmo artifact SHA-256.

`context_pass` ainda é abaixo de runtime/game e produção.

## Estado do roadmap após R12

O blocker rigid deixa de ser “nenhuma execução real Blender” e passa a ser **ampliar a evidência para além do único witness Priestess/default/MbmC01 e obter review/runtime representativos**. Não há justificativa para promover o writer ainda.

Próxima ordem recomendada:

1. R12 real: `MsmC01` em Priestess/default com controlled edit + candidate reimport + HUMAN_VISUAL review;
2. `MlmC01` no mesmo LOD;
3. representatives high/low da Priestess;
4. segundo profile/rig (Pikeman permanece runtime-unproven no profile metadata, então manter distinção explícita);
5. representantes NPC/Monster;
6. só depois discutir runtime/game gate e política de promoção.
