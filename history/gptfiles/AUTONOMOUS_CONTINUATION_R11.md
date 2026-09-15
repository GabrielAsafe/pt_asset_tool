# Continuação autónoma — R11 — 2026-09-02

Esta etapa parte da confirmação manual R10 enviada pelo utilizador. Nenhum writer, runtime gate, produção ou deploy apply foi promovido.

## Confirmação externa recebida

No snapshot R10, no ambiente real do utilizador:

- `pt_asset.py status` => `PASS`;
- `pt_asset.py smoke` => `PASS`;
- o client foi descoberto pelo app em `~/Área de Trabalho/summit/Summit Tale Client Full/cliente` via `LEGACY_HOME_DESKTOP_LAYOUT`;
- `Bcn02f.inx` + `lod=default` + `--reset` falhou host-side antes do Blender com `MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES` e `missing=['hart']`.

Isso confirma externamente os dois fixes principais de R10: descoberta consistente do client e preflight INX-LOD→SMD antes de destruir/recriar workspace.

A evidência resumida está em `evidence/manual_r10_confirmation_2026-09-02.md`.

## Problema adicional revelado pelo plano Priestess

O profile `priestess_c01_m5` em `lod=default` seleciona exatamente:

```text
MbmC01
MsmC01
MlmC01
```

Mas o `authoring_plan` source-side do SMD contém 15 objetos fisicamente elegíveis ao writer rigid, incluindo outros LODs/variantes como C03. A elegibilidade física do writer não deve permitir que um candidate produzido a partir de um workspace `default/C01` edite silenciosamente um objeto fora do contexto salvo.

## Implementado em R11

### 1. Candidate rigid limitado ao `selected_context.selected_lod_nodes`

`pt_asset_tool/rigid_authoring_candidate.py` agora calcula dois conjuntos separados:

- `source_contract_eligible_objects`: tudo que satisfaz o contrato físico do writer no SMD;
- `eligible_objects`: somente a interseção desse conjunto com os nós do LOD salvo no `selected_context`.

`--object` fora do contexto salvo é rejeitado mesmo que seja fisicamente gravável pelo writer.

O plano expõe também:

- `selected_lod_nodes`;
- `selected_lod_ineligible_objects`;
- `selection_required` via `inspect_rigid_candidate_scope()`.

Isso é uma restrição de authoring/candidate, não uma afirmação sobre o que o runtime do jogo aceita.

### 2. `build --plan` mostra o scope do workspace rigid salvo

Quando existe um `authoring_manifest.json` rigid válido, `build <asset> --plan` acrescenta `candidate_scope`, permitindo distinguir claramente:

- os objetos fisicamente elegíveis no source;
- os objetos candidate permitidos no LOD/contexto efetivamente importado.

Para a Priestess/default confirmada pelo utilizador, o esperado é o scope candidato ficar limitado a `MbmC01`, `MsmC01`, `MlmC01`.

### 3. Prova explícita de que uma edição realmente ocorreu

Os verificadores static/rigid agora reportam:

```text
edit_observed = true | false
```

Um roundtrip/no-op byte-idêntico continua válido como preservação, mas já não deve ser confundido com prova de edição controlada.

Foi adicionado:

```bash
--require-edit
```

em `build --candidate`. Para static/rigid, se o target sair byte-idêntico ao source, o build fica `FAIL` com:

```text
TARGET_EDIT_NOT_OBSERVED
```

Assim, o próximo teste manual pode provar que a alteração feita no `.blend` chegou realmente ao candidate output.

### 4. Readiness de código enriquecido sem promoção

`development_readiness.py` passa a expor como capacidades ligadas:

- `selected_lod_candidate_scope_enforced=true`;
- `candidate_require_edit_gate_available=true`.

Os blockers/maturidade continuam inalterados em essência: rigid saved-Blender ainda precisa de execução real controlada e runtime/produção continuam bloqueados.

## Validação R11

```text
58 PASS / 0 FAIL   lote amplo reproduzível sem fixture_client
8 PASS / 0 FAIL    testes focados de authoring/candidate novos/relevantes
175 PASS / 1 SKIP  suíte histórica/maintained com symlink test-only temporário
compileall          PASS
node --check        PASS
bash -n              PASS
certified hashes    unchanged
```

O symlink test-only `payload -> .` foi removido ao final.

## Próximo teste manual objetivo

No snapshot R11:

1. abrir/recriar a Priestess com profile `priestess_c01_m5`, LOD `default`;
2. executar `build char/tmABCD/MfbC01.smd --plan` e confirmar `candidate_scope.eligible_objects` = `MbmC01`, `MsmC01`, `MlmC01`;
3. no Blender, editar minimamente **um único** desses objetos, preferencialmente `MbmC01`, sem alterar skeleton/material assignment/topologia desnecessariamente;
4. salvar o `.blend`;
5. executar:

```bash
python3 pt_asset.py build "char/tmABCD/MfbC01.smd" \
  --candidate \
  --object MbmC01 \
  --require-edit
```

Resultado desejado nesta fase:

- candidate `PASS`;
- `verification.edit_observed=true`;
- `non_target_changed=[]`;
- `unknown_physique_bones=[]`;
- build provenance criado;
- `production_authorized=false`;
- `client_write_authorized=false`;
- `client_modified=false`.

Não executar deploy/apply no client.
