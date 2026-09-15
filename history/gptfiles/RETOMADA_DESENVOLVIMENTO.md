# Retomada do Desenvolvimento — PT Asset Tool

**Data do congelamento:** 2026-09-02 (R13 autonomous, Europe/Lisbon)  
**Snapshot:** `PT_Asset_Tool_dev_snapshot_2026-09-02_r13_autonomous`  
**Versão interna da aplicação:** `0.12.0`  
**Estado:** desenvolvimento não promovido; a release inicial auditada continua separada e não deve ser substituída automaticamente.  
**Git base do checkout:** `9cdddd506983186ae728aeb1c607f268f4614d20`

---
## Atualização R13 — devtest rigid automático em lote

O fluxo manual granular foi substituído como caminho recomendado por `python3 pt_asset.py validate rigid-profile-auto --all`. O runner usa workspace isolada em `pt_build/devtest`, aplica deformações determinísticas em todos os meshes HIGH/DEFAULT/LOW de cada profile canónico, executa o writer rigid em candidate combinado e reimporta/verifica os três LODs headless. O utilizador só precisa devolver o JSON final.

A evidência R12 mais recente também reportou `priestess_c01_m5/default/MsmC01` com candidate `PASS`, review humano `PASS` sobre o mesmo artifact SHA e `context_pass=true`; ela permanece evidência externa reportada, abaixo de runtime/game e produção.

**Próximo gate:** executar `validate rigid-profile-auto --all` no client/Blender real. Se passar para todos os profiles canónicos, expandir a mesma abordagem automatizada para representatives NPC/Monster antes de qualquer discussão de promoção.

## Atualização R12 — primeiro controlled edit rigid real e evidência estruturada

O utilizador executou no Blender real o witness Priestess `priestess_c01_m5`, LOD `default`, objeto `MbmC01`, e depois `build --candidate --object MbmC01 --require-edit`. O resultado reportado foi `PASS`, com `edit_observed=true`, `non_target_changed=[]`, `unknown_physique_bones=[]`, nenhum erro, 14 blocos não alvo byte-idênticos, tamanho do SMD preservado e produção/client-write ainda falsos.

R12 não promove o writer com base num único witness. Em vez disso:

- enriquece o `*.build.json` para transportar toda a evidência relevante do controlled edit;
- adiciona `certification rigid-candidate-review`, que exige artefacto + provenance R12 revalidáveis antes de gravar evidência automática e review humano separadamente;
- adiciona `view rigid-candidate`, que reimporta o SMD candidate num workspace de review separado e fixa artifact SHA/context key antes do review humano;
- adiciona `audit rigid-authoring-certification-plan`, matriz profile/LOD/object que só considera contexto PASS quando controlled edit revalidado e review humano PASS coincidem no mesmo artifact SHA-256;
- preserva o witness R11 como evidência externa `PASS_REPORTED`, mas não o conta como revalidação local porque o artefacto/sidecar não foram enviados;
- mantém runtime, produção e deploy apply bloqueados.

**Próxima expansão:** repetir controlled edits em `MsmC01`/`MlmC01`, depois `high`/`low`, e só depois ampliar para outro profile/rig/representantes NPC/Monster. Review visual e runtime continuam gates separados.

---


## Atualização R10 — evidência manual real e preflight de LOD

Após o snapshot R9, o utilizador executou os testes manuais no client/Blender real. Os logs estão em `evidence/manual_r9_test_2026-09-02_part1.txt` e `part2.txt`.

Resultados principais:

- multi-INX fail-closed funcionou para `Bcn02.smd`;
- `Bcn02.inx` explícito importou com `selected_context` físico verificado;
- troca para `Bcn02f.inx` sem reset foi corretamente bloqueada;
- `Bcn02f.inx --reset` revelou que o INX pede nós (`hart`, `T-npc-12-H02`) ausentes do SMD associado;
- R10 move essa detecção para preflight host-side e valida o novo contexto antes de apagar workspace existente;
- o cruzamento das 106 rows / 258 choices do audit real encontrou apenas 2 choices com este tipo de ausência (`Bcn02f.inx` e `C004.inx` para `tmbC03.smd`);
- profile Priestess `priestess_c01_m5` resolveu contexto exato e abriu no Blender; observação visual do utilizador foi positiva, mas não é certificação formal;
- `status/smoke` e `doctor` usavam discovery inconsistente; R10 alinha app-level discovery aos layouts históricos de `Settings.discover()`.

**Ponto de retomada R10:** rerun curto dos guards no ambiente real; depois, no workspace Priestess visualmente conferido, fazer uma única alteração geométrica controlada em um objeto elegível e executar `build --candidate --object <nome>` para obter a primeira evidência real do generic rigid saved-Blender candidate. Continuar sem deploy/apply.

---

## 1. Como usar este documento para retomar

Este arquivo é o ponto de entrada para continuar o desenvolvimento sem reconstruir o contexto por conversa.

Ao retomar:

1. extrair este snapshot;
2. trabalhar dentro de `app/`;
3. ler primeiro este arquivo;
4. consultar `docs/REVERSE_ENGINEERING_FORMATOS.md` para formatos;
5. consultar `docs/MAPA_MODULOS_SCRIPTS.md` para entender as famílias de módulos;
6. consultar `CURRENT_GIT_STATUS.txt` e `CURRENT_DIFF.patch` para saber o que estava fora do commit base;
7. usar `CURRENT_READINESS.json` como fotografia machine-readable do roadmap;
8. manter os quatro writers certificados byte-for-byte até uma nova certificação formal.

O snapshot não inclui `pt_build`, caches, configuração pessoal, `.git`, fixture client nem os grandes bundles enviados pelo utilizador.

---

## 2. Objetivo do produto

O PT Asset Tool está sendo transformado numa aplicação standalone para **inspecionar, classificar, visualizar, editar, validar, construir e futuramente publicar/restaurar assets do Summit Tale/Priston Tale**, sem exigir que o utilizador conheça scripts históricos individuais.

Princípios que não devem ser quebrados:

- o client original é read-only por padrão;
- edição e build ficam em `pt_build`;
- Blender é editor/transporte, não autoridade do formato binário;
- uma capacidade só sobe de maturidade quando existe evidência correspondente;
- parser funcionando não implica writer autorizado;
- preview visual não implica roundtrip correto;
- roundtrip byte-idêntico não implica edição semanticamente correta;
- edição source-side correta não implica aceitação Blender/runtime;
- publish não é autorizado apenas porque existe um writer;
- qualquer ambiguidade de binding/configuração deve falhar fechada em vez de escolher por heurística.

A escada de confiança usada no projeto é, em termos gerais:

```text
parse / inspect
→ structural evidence
→ binding evidence
→ source-side semantic evidence
→ Blender representation/review
→ byte-preserving roundtrip
→ controlled candidate edit
→ runtime/game evidence
→ production promotion
→ transactional deploy/restore
```

---

## 3. Estado atual por área

| Área | Maturidade atual | Resumo |
|---|---|---|
| Núcleo standalone | **OPERATIONAL** | CLI/GUI, config, catálogo, status/smoke/doctor, jobs, reports e política read-only. |
| Catálogo/Entidades | **OPERATIONAL** | Filtros hierárquicos, taxonomia UI, entidades NPC/Monster e evidência de registry. |
| Model0.62 static | **PARTIAL** | Import/inspect + saved-Blender candidate + object-local POS/SCALE candidate. |
| Model0.62 rigid | **PARTIAL** | Binding/import/animação amplos + saved-Blender candidate; produção só em rare scopes certificados. |
| Stage0.72 | **PARTIAL** | Parse/preview/paint/roundtrip + saved-edit candidate estrito. |
| Animação | **PARTIAL** | INX↔SMB, Actions, source regression e fila de review; falta Blender/runtime representativo. |
| INX writer | **CANDIDATE** | Candidate preservacional/semântico; não autorizado em produção. |
| SMB writer | **CANDIDATE** | Candidate para existing keys; não autorizado em produção. |
| Profiles/LOD | **PARTIAL** | Registry, verify e discovery; authoring genérico ainda parcial. |
| Mixed-Physique | **DEFERRED_NO_REPRESENTATIVE** | Corpus canónico tem zero representantes; manter fail-closed. |
| Publish/Restore | **BLOCKED_BY_POLICY_AND_WRITER_PROMOTION** | Plan/prepare/verify/simulate/state/restore-plan existem; apply real permanece bloqueado. |

### Blockers formais atuais

#### Model0.62 static
- real Blender corpus execution of static candidate writer
- object-local POS/SCALE candidate corpus/runtime evidence
- object-local rotation/TmPrevRot writer remains unimplemented
- family-wide runtime certification for arbitrary artist edits
- production promotion policy

#### Model0.62 rigid
- real Blender corpus execution of rigid candidate writer
- Blender/runtime certification beyond currently promoted rare scopes
- production promotion policy

#### Stage0.72
- real Blender corpus execution of Stage0.72 saved-edit candidate
- full edited-map runtime acceptance gate
- production promotion policy

#### Animação
- Blender pose-space visual certification across representative player/NPC/monster rigs
- runtime/game acceptance for edited animation data

#### INX writer
- runtime semantic acceptance of edited MotionInfo
- transactional publish/restore integration
- production policy/promotion gate

#### SMB writer
- runtime semantic acceptance of edited SMB motion
- key insertion/deletion/segment editing if required
- transactional publish/restore integration
- production policy/promotion gate

#### Profiles/LOD
- generic profile-driven authoring/build path
- runtime gates for profiles still marked unproven

#### Deploy/Restore
- per-family production writer authorization
- real-client-filesystem atomic replace + postwrite verification policy
- explicit app-level apply/restore promotion gate after production-writer coverage
- real-client restore execution + post-restore verification remains unpromoted


---

## 4. O que está operacional no produto

### 4.1 Núcleo

Já existe um caminho normal de aplicação baseado em:

```text
status
smoke
doctor
config
ui / gui
assets
asset
entities
profiles
bindings
compare trees
view
import
edit
paint
build
write
validate
diagnose
certification
audit
deploy
```

O código histórico de research continua presente quando ainda serve como evidência ou dependência, mas não deve ser apresentado como fluxo normal ao utilizador.

### 4.2 Catálogo e GUI

A GUI já possui:

- catálogo físico do client;
- `Categoria → Pasta → Role → Extensão`;
- extensão com descrição humana;
- tabela/galeria;
- preview BMP/TGA através dos adapters do projeto;
- entidades NPC/Monster por pasta física;
- detalhe enriquecido com famílias, binding e dependências;
- jobs, cancelamento e relatórios recursivos;
- comparação de árvores;
- Monster/NPC census;
- review humano PASS/FAIL/SKIP dentro da GUI para validators interativos;
- seleção de motion, `selected/core/all`, head e tier nos fluxos de animação;
- capability gating fail-closed.

A classificação física tem precedência específica para evitar falsos NPC/Monster: árvores de frontend como `StartImage` e `Image/Sinimage` continuam UI mesmo quando um componente do path contém `npc`.

### 4.3 Entidades NPC/Monster

O seed enviado pelo utilizador contém 351 entidades físicas:

```text
267 Monster
84 NPC
```

A entidade agrega caminhos de modelo/config/animação/textura e escolhe representante visual. Isso é identidade de catálogo, não autorização de runtime/writer.

O audit de binding corrigido mede atualmente, no registry canónico:

```text
NPC rigid:     95 / 96 resolvidos
Monster rigid: 392 / 393 resolvidos
```

O caso NPC restante (`Bcn05_`) permanece fail-closed porque pairing aponta para outra entidade física e não prova aquele SMD como root animado.

---

## 5. Reverse engineering / formatos já estabelecidos

A referência detalhada está em `docs/REVERSE_ENGINEERING_FORMATOS.md`. Não recomeçar reverse desses formatos antes de consultar esse arquivo e os módulos correspondentes.

Estado resumido:

### SMD Model0.62

Há três classificações relevantes no código:

```text
SMD_MODEL_062_STATIC
SMD_MODEL_062_RIGID_PHYSIQUE
SMD_MODEL_062_VARIANT_OR_DAMAGED
```

O audit canónico encontrou:

```text
3148 Model0.62
1953 raw rigid
1195 static
0 mixed
```

O inventário semântico tem 1952 rigid + 1195 static + 1 variant/damaged. `at_dragon` é o variant/damaged conhecido por mismatch de NodeName, mas possui caminhos especializados certificados.

### Stage0.72

Há 63 assets canónicos. Parse, StageArea, normals, textures, UV e geometry witnesses já existem. O candidate salvo no Blender é deliberadamente restrito a:

```text
UV_ONLY
ou
SINGLE_VERTEX_X_GRID
```

Qualquer mistura de alterações, topologia/material/light/color drift deve ser recusada.

### INX

Layouts comprovados incluem `MODERN_172` e `LEGACY_120`. O writer candidate preserva a representação binária original de campos não editados, inclusive encodings válidos não canónicos.

Evidência de corpus já obtida:

```text
542 / 542 no-op byte-identical
542 / 542 controlled edits reparsed/allowlisted
531 MODERN_172
11 LEGACY_120
73 files / 100 MotionInfo records com start encoding alternativo preservado
```

### SMB

O parser separa preservação de layout binário de avaliação de hierarquia. Isso foi necessário para `Ahinf.smb`, que contém parent externo e pode ser preservado sem tornar a hierarquia válida para avaliação de animação.

Evidência:

```text
18 / 18 no-op byte-identical
14 / 14 arquivos com existing key editável passaram candidate edit
4 sem key adequada
0 falhas
```

### BMP/TGA proprietários

O runtime já usa adapters específicos. Não substituir por decoder genérico. Existem TGA outliers onde alguns casos são preview-only recoverable e outros não representam uma imagem TGA válida.

---

## 6. Authoring atual

### 6.1 Generic import

`import <asset>` prepara workspace em:

```text
pt_build/blender_edits/generic_import/<asset-descritivo>/
```

Um workspace novo contém `authoring_manifest.json` com SHA-256 do source e dependências físicas. Reabrir workspace não deve sobrescrever edição artística; reset precisa ser explícito.

### 6.2 Model0.62 static saved-Blender candidate

Existe candidate de build, `pt_build` only, provenance-gated. O authoring plan identifica objetos elegíveis. Produção não está autorizada.

Constraints genéricas atuais incluem:

- static/no Physique;
- target sem object-local animation para o caminho geometry saved-Blender;
- pelo menos 3 vértices e faces;
- exatamente uma camada TexLink por face no caminho genérico;
- material IDs existentes.

### 6.3 Model0.62 rigid saved-Blender candidate

Existe candidate provenance/skeleton-gated. O output é verificado para garantir que slots Physique apontam para bones reais do SMB.

Ainda falta execução de corpus no Blender real e promoção de produção.

### 6.4 Stage0.72 saved-edit candidate

Existe candidate estrito, com extração do edit salvo no `.blend` e aplicação host-side usando os writers/compares já provados.

Não ampliar o edit set sem nova prova.

### 6.5 Object-local candidate — trabalho mais recente

Módulo atual:

```text
pt_asset_tool/object_local_writer.py
```

Escopo implementado:

```text
existing POS key
existing SCALE key
```

Regras:

- somente key existente;
- nenhum insert/delete;
- tamanho do arquivo preservado;
- somente 12 bytes do valor da key podem mudar;
- structural/hierarchy/key-count invariants precisam ficar idênticos;
- SCALE precisa permanecer exatamente na grelha 1/256;
- output é `CANDIDATE_PT_BUILD_ONLY`;
- client nunca é modificado.

Ainda bloqueado:

```text
ROT keys
TmPrevRot
segmented TmFrame writer
key insertion/deletion
production promotion
```

A razão para manter rotation bloqueada é que ela precisa reconstrução matricial cumulativa própria e não deve ser tratada como simples substituição de quaternion sem prova.

Comandos atuais relacionados:

```bash
python3 pt_asset.py write object-local-key-candidate ...
python3 pt_asset.py audit object-local-writer-corpus ...
```

---

## 7. Ponto técnico exato onde o desenvolvimento foi interrompido

O trabalho imediatamente anterior ao pedido de snapshot estava endurecendo **profiles/LOD e múltiplos INX em rigid assets**.

Foi identificado que existem rigid assets com mais de um INX/model-info, e alguns INX não são semanticamente equivalentes em `lod_groups`.

### Implementação já feita

`ValidationRunner._select_rigid_lod()` agora aceita `model_info=` e possui modo `require_unambiguous=True`.

Comportamento esperado:

1. se há um único config útil, selecionar normalmente;
2. se há vários configs mas eles são semanticamente equivalentes, auto pode usar o primeiro de forma determinística;
3. se há vários configs não equivalentes, **não escolher silenciosamente**;
4. emitir `AMBIGUOUS_MODEL_INFO_CONFIG`;
5. exigir `--model-info <exact-associated-inx>`;
6. validar que o INX explícito realmente pertence ao asset.

A GUI/action builder também já aceita `lod` + `model_info` explícitos.

Testes focados atuais passam para:

- configs diferentes → fail-closed;
- config explícito → seleciona corretamente;
- configs semanticamente equivalentes → auto permitido;
- comando UI → propaga `--lod` e `--model-info`.

### Lacuna a fechar em seguida

O `workspace_info.json` / `import_summary.json` registra o `model_info_inx` selecionado, mas `authoring_manifest.json` ainda guarda dependências como uma lista geral e **não promove explicitamente o model-info selecionado a uma identidade de authoring**.

Próximo passo recomendado:

1. adicionar ao manifest algo como `selected_context` com:
   - `model_info_inx` lógico;
   - SHA-256 físico desse INX;
   - `skeleton_smb` lógico;
   - SHA-256 do SMB;
   - LOD efetivamente escolhido;
   - assinatura dos `lod_groups`;
2. no rigid candidate build, exigir que o contexto salvo no manifest coincida com o contexto selecionado/importado;
3. impedir build quando outro INX semanticamente diferente tenha sido escolhido implicitamente;
4. adicionar essa identidade também ao `*.build.json` provenance;
5. incluir o contexto na transação deploy.

Essa é a retomada técnica mais imediata.

---

## 8. Profiles / LOD

O projeto possui `CharacterProfileRegistry`, verify e discovery.

Discovery atual do inventário completo encontrou:

```text
1940 combinações asset + INX com grupos LOD
55 structurally candidate-ready
1 canonical/runtime-proven profile
```

Regra central: **não associar profile por basename**. Correspondência deve usar paths/documentação física exatos.

Próximos passos após fechar `selected_context`:

1. transformar candidatos LOD equivalentes em profiles estáveis;
2. distinguir variantes deliberadas de conflitos;
3. usar profile como input de authoring apenas depois de cross-check registry/INX/skeleton;
4. rodar Blender/runtime em representantes HIGH/DEFAULT/LOW;
5. só depois permitir generic profile-driven build.

---

## 9. Animação

Já existe:

- INX parsing moderno/legacy;
- SMB parsing/evaluation;
- resolução INX→SMB;
- motion selection;
- Actions Blender;
- `selected/core/all`;
- heads verificadas;
- source-side regression;
- `audit animation-corpus`;
- `audit animation-certification-plan`;
- GUI human-review bridge PASS/FAIL/SKIP.

A prioridade P0 continua sendo provar pose-space e visual em skeletons diferentes, sem voltar a alterar parser INX/SMB sem evidência.

O plano de certificação deve cobrir representantes de:

```text
PLAYER / CHARACTER
NPC
MONSTER
MODERN_172
LEGACY_120
STAND
WALK
ATTACK
DAMAGE
SKILL quando disponível
```

O source-side PASS não é certificação visual Blender nem runtime.

---

## 10. Candidate writers INX/SMB

Além do roundtrip e controlled edit, existe:

```text
audit motion-writer-semantic-edit-corpus
```

A ideia é editar temporariamente MotionInfo INX e uma key SMB em contextos registry-proven e exigir que o evaluator source-side continue válido e finito.

Maturidade pretendida quando a prova passa:

```text
CANDIDATE_SOURCE_SEMANTIC_EDIT_PROVEN
```

Isso ainda fica abaixo de:

```text
BLENDER_VISUAL_PROVEN
RUNTIME_PROVEN
PRODUCTION_AUTHORIZED
```

Não promover writers automaticamente com base em audit deep.

---

## 11. Build provenance e deploy/restore

### Build provenance

Candidate builds passam a gerar sidecar `*.build.json`. Isso diferencia:

```text
arquivo qualquer dentro de pt_build
```

de:

```text
artefacto produzido por adapter/writer conhecido, ligado ao source SHA e asset
```

Um artefacto manual sem provenance deve ser bloqueado pelo deploy planner.

### Deploy atual

Comandos atuais:

```text
deploy plan
deploy prepare
deploy verify
deploy simulate
deploy state
deploy restore-plan
```

Não existe `apply` real.

`deploy prepare` cria, dentro de `pt_build`:

- snapshot do source esperado;
- backup verificado;
- artefacto staged;
- transaction manifest;
- snapshot de provenance.

`deploy simulate` testa numa cópia sandbox:

- atomic replace;
- post-write SHA/size verification;
- rollback;
- failure injection pós-write.

`deploy state` classifica bytes atuais como:

```text
ORIGINAL_SOURCE
MANAGED_ARTIFACT
UNKNOWN_DRIFT
MISSING
```

`restore-plan` só considera restorable um `MANAGED_ARTIFACT` conhecido. Drift desconhecido permanece bloqueado.

### Antes de qualquer `deploy apply`

Ainda exigir:

1. writer de produção autorizado para a família;
2. source/client drift gate;
3. build provenance íntegra;
4. backup verificado;
5. transaction manifest;
6. política de atomic replace no filesystem real;
7. post-write verification;
8. rollback real comprovado;
9. post-restore verification;
10. promoção explícita da policy — nunca implícita por existência do código.

---

## 12. Mixed-Physique

Não implementar agora.

O audit fornecido pelo utilizador prova:

```text
smd_model_062_total = 3148
RIGID = 1953
STATIC = 1195
MIXED = 0
UNKNOWN = 0
```

Decisão: manter detecção/fail-closed e reabrir somente se aparecer um representante físico real.

---

## 13. Writers certificados que NÃO devem ser alterados

Hashes no momento do snapshot:

```text
229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42  pt_asset_tool/rare_rigid_edit.py
```

```text
0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991  pt_asset_tool/rare_rigid_multivertex.py
```

```text
010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0  pt_asset_tool/rare_rigid_multibone_bridge.py
```

```text
67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96  pt_asset_tool/rare_rigid_normal_bridge.py
```


Qualquer alteração nesses quatro módulos deve ser tratada como nova certificação formal, não como refactor comum.

---

## 14. Testes e baseline no congelamento

### Última regressão completa confirmada antes das alterações mais recentes

```text
288 PASS / 2 SKIP / 0 FAIL
```

Essa baseline incluía 113 testes de desenvolvimento + 175 históricos/maintained.

### Validação do estado atual, posterior a essa baseline

Os módulos diretamente afetados por authoring/provenance/deploy/Stage/object-local passaram:

```text
33 / 33 PASS
```

Os testes focados em multi-INX rigid + object-local passaram:

```text
11 / 11 PASS
```

A suíte histórica completa atual foi novamente executada:

```text
175 PASS / 1 SKIP
```

Syntax checks atuais:

```text
Python compileall PASS
JavaScript node --check PASS
shell bash -n PASS
```

Com fixture client e `PT_BLENDER_COMMAND=/bin/true`:

```text
status = PASS
smoke = PASS
doctor_check = PASS
certified_writer_hashes_valid = true
```

### Nota sobre a suíte dev completa

Uma execução única de todos os `dev_tests` ultrapassa a janela deste ambiente porque alguns audits/corpus são pesados. Não registrar isso como FAIL. Ao retomar, execute em blocos ou use os tests opt-in de corpus separadamente.

Stage0.72 full fixture corpus continua opt-in:

```bash
PT_RUN_SLOW_FIXTURE_TESTS=1 python3 -m pytest -q dev_tests/test_stage072_fixture_corpus.py
```

---

## 15. Comandos úteis para retomar

### Baseline

```bash
python3 pt_asset.py --version
python3 pt_asset.py status
python3 pt_asset.py smoke
python3 pt_asset.py doctor
```

### Readiness

```bash
python3 pt_asset.py audit development-readiness
python3 pt_asset.py audit development-readiness --deep
```

### Model authoring

```bash
python3 pt_asset.py audit model062-authoring
python3 pt_asset.py import <asset> --no-open
python3 pt_asset.py build <asset> --plan
python3 pt_asset.py build <asset> --candidate
```

Para rigid com configuração ambígua:

```bash
python3 pt_asset.py import <asset> --model-info "char/.../config.inx" --lod high --no-open
```

### Object-local

```bash
python3 pt_asset.py audit object-local
python3 pt_asset.py audit object-local-corpus
python3 pt_asset.py audit object-local-writer-corpus
```

### INX / SMB

```bash
python3 pt_asset.py audit inx-writer-corpus
python3 pt_asset.py audit inx-writer-edit-corpus
python3 pt_asset.py audit smb-writer-corpus
python3 pt_asset.py audit smb-writer-edit-corpus
python3 pt_asset.py audit motion-writer-semantic-edit-corpus
```

### Animation

```bash
python3 pt_asset.py audit animation-source
python3 pt_asset.py audit animation-corpus
python3 pt_asset.py audit animation-certification-plan --motions-per-context 3
```

### Profiles

```bash
python3 pt_asset.py profiles list
python3 pt_asset.py profiles verify --all
python3 pt_asset.py profiles discover --limit 100
```

### Deploy — somente read-only/sandbox

```bash
python3 pt_asset.py deploy plan <asset> --artifact pt_build/.../build.smd
python3 pt_asset.py deploy prepare <asset> --artifact pt_build/.../build.smd
python3 pt_asset.py deploy verify ...
python3 pt_asset.py deploy simulate ...
python3 pt_asset.py deploy state ...
python3 pt_asset.py deploy restore-plan ...
```

Não criar `deploy apply` sem passar pelos blockers da seção 11.

---

## 16. Ordem recomendada de continuação

### P0 — agora

1. **Fechar identidade de contexto rigid multi-INX** no `authoring_manifest` e build provenance.
2. Rodar audit do universo real de assets com múltiplos INX e classificar equivalentes vs não equivalentes.
3. Executar static/rigid/Stage candidates no Blender real em representantes controlados.
4. Executar `animation-certification-plan` no Blender real e fechar pose-space/visual em player/NPC/monster.
5. Rodar `object-local-writer-corpus` no client real para POS/SCALE e só depois decidir promoção desse canal.

### P1

6. Generalizar profiles/LOD a partir dos 55 candidates prontos.
7. Levar INX/SMB de source-semantic proven para Blender/runtime evidence.
8. Determinar se key insertion/deletion SMB é realmente necessária antes de implementá-la.
9. Investigar object-local rotation/TmPrevRot como família separada; não reutilizar writer POS/SCALE.
10. Ampliar Stage0.72 candidate apenas quando existir edição real que exija outro canal.

### P2

11. Formalizar production promotion por família.
12. Só então criar policy de deploy apply/restore apply real.
13. Testar atomicidade/rollback no filesystem real do client usando um protocolo controlado e backup independente.
14. Full-client regression final.
15. Atualizar versão e somente então promover V1.

---

## 17. Coisas que NÃO fazer ao retomar

- não modificar o client para “ver se funciona” antes do deploy gate;
- não promover INX/SMB por causa de roundtrip byte-idêntico apenas;
- não tratar folder/name como prova de skeleton binding;
- não escolher primeiro INX quando houver variantes semanticamente diferentes;
- não reabrir Mixed-Physique sem representante real;
- não remover módulos de `history_py` apenas pelo nome da pasta sem verificar dependências dinâmicas;
- não editar os quatro writers certificados casualmente;
- não usar decoder BMP/TGA genérico no lugar dos adapters existentes;
- não transformar preview visual em certificação estrutural/runtime;
- não relaxar thresholds/guards apenas para obter PASS.

---

## 18. Bundles/evidências externas usados nesta linha

Eles **não estão incluídos neste snapshot** por tamanho/separação de dados. Se uma nova sessão precisar reproduzir os audits completos, usar os mesmos arquivos ou equivalentes e conferir os SHA-256 abaixo.

- `Ahin.zip` — `d315ad88f6d5b5a6dafd5707c2fa7d92ac475e540a3658e251ccac3ad47a8363`
- `monsters.zip` — `eecb5cef87d0ec1d24c0dcc1d23a0f8db1e0e7f45444a15ece4c815f1919ab3a`
- `profiles.zip` — `f9b39763cb70bc6b31ba077b504f1da604e1e755c2214e6ac63e8545b4b9f105`
- `stage072_dev_bundle.zip` — `7169eac8147cb9710a856f2479c9878d6879f15154ea863c3d0b3fb4009d00be`
- `stage072_textures_dev_bundle.zip` — `6dd3433c39329ce2afcef796b670e4adf2751887d506c8dc5d85f955f9179e60`
- `rare_outliers_dev_bundle(1).zip` — `a9760c94ab96bf39639c4a256cc33ec69de0a415260364e68b116edb6b33586f`
- `PT_ENTITY_CATALOG.zip` — `2f6950306071e2d97f211b2d96a3d05b54e37ed0448ffa82f56d7c0ffdf0c724`
- `PT_UI_TREE.tsv` — `07eca31a4a09c261a29fdc6f0a80cec14a7d619b82568424e0322e71f5d5dcbb`
- `physique_audit_current.json` — `8624b7c8025b1e03074d200fc6abe350063f4d9f1024b076ed917aadffb4a1f6`
- `assetsFamilys.md` — `b96a732a77863e378620900af681ee47ae91d517d5ca7fac76761589403601e4`
- `Texto colado (20260902-105200).txt` — `2d39e51b2d4d62fc87609e535f7b5000d64e3bb890c55563b126a927d9ba41bc`


Principais usos:

- `Ahin.zip` / `monsters.zip`: animação, INX/SMB, bindings e fixtures reais;
- `profiles.zip`: evidência histórica de LOD/profile;
- Stage bundles: corpus Stage0.72;
- rare outliers: classificação/outlier handling;
- `PT_ENTITY_CATALOG.zip`: 351 entidades NPC/Monster;
- `PT_UI_TREE.tsv`: taxonomia física da UI;
- `physique_audit_current.json`: prova de zero Mixed-Physique;
- `assetsFamilys.md`: taxonomia semântica definida com base no client/reverse;
- `Texto colado (20260902-105200).txt`: observações da fase 2 de teste do utilizador que motivaram UX/GUI/docs/census fixes.

---

## 19. Estrutura deste snapshot

```text
PT_Asset_Tool_dev_snapshot_2026-09-02_r7_current/
├── app/                         # checkout atual sem .git/cache/pt_build/config local
├── docs/                        # documentação técnica e de uso atual
├── legacy_reference/            # pipelines antigos mantidos como referência
├── RETOMADA_DESENVOLVIMENTO.md  # este documento
├── CURRENT_READINESS.json       # maturity/blockers gerados pelo código atual
├── CURRENT_GIT_STATUS.txt       # modified/untracked relativo ao commit base
├── CURRENT_DIFF.patch           # diff das alterações tracked relativo ao commit base
├── BASE_COMMIT.txt
└── VALIDATION_STATUS.md
```

O snapshot contém também módulos untracked do checkout atual. Eles estão fisicamente dentro de `app/` mesmo quando não aparecem em `CURRENT_DIFF.patch`; `CURRENT_GIT_STATUS.txt` é a referência para identificar esses arquivos.

---

## 20. Ponto de retomada em uma frase

> **Continuar pelo contexto rigid multi-INX: tornar o INX/model-info + skeleton + LOD escolhido parte explícita e verificável do authoring manifest/build provenance; depois executar os candidates static/rigid/Stage e a fila de animação no Blender real antes de promover qualquer writer ou habilitar deploy no client.**

---

## 21. Atualização R9 — audit real multi-INX e profile-driven import

O gap descrito originalmente na seção 7 foi fechado em R8 e, em R9, validado contra o audit real `rigid_model_info_contexts` fornecido pelo utilizador.

Resultado real:

```text
1952 rigid assets
1762 single-config
106 multi-config
51 multi-config semanticamente equivalentes
55 AMBIGUOUS_MODEL_INFO_CONFIG
84 sem model-info utilizável
```

A nova decomposição R9 reclassificou as 106 rows sem divergência e mostrou que todos os 55 casos ambíguos divergem em `LOD_GROUPS`; nenhum deles troca `motion_smb` entre as choices do report. Isso **não** autoriza auto-selection: os 55 continuam a exigir `--model-info` explícito.

Profiles/LOD avançou um nível de workflow, mas não de produção:

```bash
python3 pt_asset.py profiles authoring-plan <profile_id> --lod default
python3 pt_asset.py import <asset> --profile <profile_id> --lod default --no-open
```

O authoring plan por profile exige target exato + contexto INX/skeleton/LOD único e persiste a seleção no `selected_context`. Writer/build de produção permanece não autorizado.

Além disso, reuse de workspace rigid é agora context-bound: alterar `--model-info`, LOD explícito ou profile exige `--reset`, evitando reutilização silenciosa de um `.blend` criado sob outro contexto.

### Novo ponto de retomada em uma frase

> **Usar o contexto multi-INX real já classificado para executar profiles/candidates no Blender real e fechar pose-space/runtime; não ampliar parser nem promover writer antes dessa evidência.**

---

## Atualização R11 — scope do candidate rigid e prova de edit

A confirmação manual R10 validou `status=PASS`, `smoke=PASS` e o preflight host-side de `Bcn02f.inx` antes do Blender.

O candidate rigid foi endurecido novamente: a elegibilidade física do writer já não basta. O `--object` precisa também pertencer a `selected_context.selected_lod_nodes`, isto é, ao LOD exato salvo no workspace. Isso impede que um SMD que carrega vários LODs/variantes exponha objetos fora do contexto importado como alvo candidate.

Além disso, `build --candidate` para static/rigid passa a reportar `edit_observed`. A opção `--require-edit` transforma um no-op byte-idêntico em `TARGET_EDIT_NOT_OBSERVED`, permitindo que um teste manual de edição controlada prove que o caminho de escrita realmente observou a alteração Blender.

Essas mudanças continuam `CANDIDATE_PT_BUILD_ONLY`; não alteram produção, runtime ou deploy.

---

## R13 automated rigid profile devtest — continuação 2026-09-02

A estratégia de repeated manual rigid micro-witnesses foi substituída por `validate rigid-profile-auto`. O comando roda em `pt_build/devtest`, aplica edições determinísticas em todos os meshes HIGH/DEFAULT/LOW dos profiles canónicos, gera um candidate combinado, exige edit coverage/Physique/non-target invariants e reimporta/verifica HIGH/DEFAULT/LOW headless. Use `--all` para o gate de desenvolvimento completo.

A evidência real R12 `priestess_c01_m5/default/MsmC01` chegou a `BLENDER_CANDIDATE=PASS + HUMAN_VISUAL=PASS` no mesmo artifact SHA e `context_pass=true`; preservada como external reported evidence porque candidate/provenance/review bytes não foram anexados ao snapshot.

**Retomar daqui:** executar `python3 pt_asset.py validate rigid-profile-auto --all` no ambiente real. Se ambos os profiles passarem, usar o batch JSON como gate para ampliar automaticamente a cobertura rigid (NPC/Monster e depois runtime/game), sem voltar a testes manuais por vértice. Produção/deploy apply continuam bloqueados.
