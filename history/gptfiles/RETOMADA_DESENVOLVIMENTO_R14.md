# PT Asset Tool — Retomada do desenvolvimento R14 (handoff 2026-09-03)

## Objetivo do produto 1.0

A versão 1.0 deve contemplar, de forma explícita e fail-closed, os domínios de conteúdo:

- PLAYER / personagens jogáveis
- NPC
- MONSTER / mobs
- WEAPON_ITEM / armas e items
- EFFECT
- MAP

E as capacidades técnicas:

- SMD Model 0.62 rigid Physique
- SMD Model 0.62 static
- SMD Model 0.62 mixed-Physique
- SMB existente
- INX moderno / legacy / outliers
- BMP/TGA proprietários
- Stage 0.72
- object-local animation
- multilayer TexLink
- LOD
- materiais
- texturas
- rigging
- animações existentes
- publish/restore somente após promoção segura dos writers

A estratégia acordada com o utilizador é: **desenvolvimento e dev tests automáticos; pedir intervenção manual apenas quando houver um gate visual/runtime ou dependência física externa inevitável. Não pedir microtestes de Blender por objeto/vértice.**

## Invariantes de segurança que não devem ser relaxados

- client original é read-only por padrão;
- outputs candidate ficam apenas em `pt_build`;
- candidate != production;
- nenhuma rota genérica escreve no client;
- não habilitar `deploy apply`;
- contexto/binding ambíguo falha fechado;
- troca de contexto em workspace existente exige `--reset`;
- writers certificados raros não devem ser alterados sem uma nova certificação explícita.

Hashes certificados preservados neste handoff:

- `pt_asset_tool/rare_rigid_edit.py`: `229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42`
- `pt_asset_tool/rare_rigid_multivertex.py`: `0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991`
- `pt_asset_tool/rare_rigid_multibone_bridge.py`: `010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0`
- `pt_asset_tool/rare_rigid_normal_bridge.py`: `67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96`

## Baseline antes da R14

R13 introduziu `validate rigid-profile-auto --all` e foi executado no client real pelo utilizador com PASS:

- 2/2 profiles: `pikeman_c01_m4`, `priestess_c01_m5`;
- 15/15 meshes rigid automaticamente editados;
- HIGH/DEFAULT/LOW reimportados com PASS;
- nenhum `non_target_changed`;
- nenhum `unknown_physique_bones`;
- production/client write/client modified continuaram false.

Isto encerrou a necessidade de continuar a testar manualmente meshes de Pikeman/Priestess.

## Trabalho implementado na R14 interna

### 1. Matriz executável Release 1.0

Novos módulos principais:

- `pt_asset_tool/release_1_coverage.py`
- `pt_asset_tool/release_1_auto.py`

A matriz cruza os seis domínios de conteúdo com as capacidades requeridas. O estado fica `PARTIAL` enquanto houver blockers; não pode reportar PASS apenas porque um módulo existe.

A classificação de domínio foi endurecida para combinar evidência de path estrutural com categoria semântica, evitando casos como arma em `Effect/` virar EFFECT e `Maplebear` virar MAP.

Snapshot de coverage offline mais recente está em:

- `app/pt_build/devtest/release_1_coverage_handoff.json`

Ele ainda fica `PARTIAL` porque os gates físicos/reais não foram executados neste ambiente sem o client completo.

### 2. Censo rigid corpus-wide

Novos/alterados:

- `pt_asset_tool/rigid_context_census.py`
- `pt_asset_tool/standalone_rigid_devtest.py`
- `pt_asset_tool/rigid_semantic_devtest.py`
- `pt_asset_tool/rigid_authoring_stress.py`
- `pt_asset_tool/validation.py`
- `pt_asset_tool/authoring.py`
- `pt_asset_tool/profile_authoring.py`

O objetivo é não certificar rigid apenas por representatives. Cada rigid deve cair em um caminho suportado:

- contexto model-info/LOD + skeleton;
- skeleton resolvido separadamente;
- standalone estrutural provado;
- caso contrário blocker nominal.

Foi adicionada a rota de contexto `--model-info + --skeleton` para equipamentos/rigid que têm LOD válido no INX mas recebem o skeleton por binding separado.

Também existe contexto rigid standalone por skeleton, com structural gate e identidade/SHA persistida no workspace/provenance. Não usar nome de arquivo como autorização; a hipótese só vira válida após structural PASS.

### 3. Semântica LOD/INX fixed-width

Arquivo central:

- `pt_asset_tool/rigid_model_info.py`

Foi descoberto que slots de nome de modelo em INX usam chave serializada de 16 bytes, enquanto NodeName do SMD pode ser maior. Implementou-se match determinístico `fixed16`, sem fuzzy matching nem aliases inventados.

Estado offline atual do censo LOD, regenerado no handoff:

- configs INX associados: **2036**;
- configs com LOD: **1940**;
- `IMPORTABLE`: **1906**;
- `IMPORTABLE_FIXED16_MODEL_KEY`: **22**;
- `AUTHORABLE_SINGLE_TIER_FULL_CONTAINER`: **10**;
- `MISSING_SMD_NODES_FAIL_CLOSED`: **2**;
- `NO_LOD_GROUPS`: **96**.

O relatório completo está em:

- `app/pt_build/devtest/rigid_lod_context_corpus_handoff.json`

Os dois mismatches reais que permanecem fail-closed são os contextos conhecidos ligados a:

- `char/npc/Bcn02/Bcn02.smd` / `Bcn02f.inx`;
- `char/tmABCD/tmbC03.smd` / `C004.inx`.

Não inventar aliases para estes casos sem evidência runtime/autoritativa.

### 4. Mixed-Physique

Novos módulos:

- `pt_asset_tool/mixed_authoring_candidate.py`
- `pt_asset_tool/mixed_synthetic_devtest.py`

Há pipeline sintético para container Model0.62 contendo objetos rigid + static, despacho combinado de writers, preservação de blocos não alvo e contexto/provenance.

**Blocker externo conhecido:** não existe amostra Mixed-Physique autêntica no corpus atual. A arquitetura está implementada, mas a capacidade não deve ser considerada fisicamente certificada até obter um arquivo real/autoritativo e executar o gate.

### 5. Object-local animation

Alterados/novos:

- `pt_asset_tool/object_local.py`
- `pt_asset_tool/object_local_corpus.py`
- `pt_asset_tool/object_local_writer.py`
- `pt_asset_tool/object_local_devtest.py`
- `pt_asset_tool/motion_core.py`
- `dev_tests/test_geometry_writer_object_local_contract.py`

O candidate writer cobre keys existentes de:

- ROT, com rebuild cumulativo de `TmPrevRot`;
- POS;
- SCALE;
- tracks segmentados por `TmFrame`.

A escrita continua allowlisted/fixed-layout; não criar tracks inexistentes de forma especulativa.

### 6. Animação existente / pose-space

Novos:

- `pt_asset_tool/animation_pose_devtest.py`
- `pt_asset_tool/standalone_animation_devtest.py`
- `pt_asset_tool/blender/check_baked_animation_pose.py`

Existe gate headless para comparar pose-space/matrizes do bake Blender com dados esperados de INX/SMB.

Também há caminho para SMB standalone sem INX, relevante para EFFECT/MAP: a presença de animação deve ser inferida pelos containers/tracks reais do SMB, não pela existência de MotionInfo.

Review humano deve ficar reservado ao gate final visual/runtime, não por motion individual.

### 7. Static Model0.62

Novos:

- `pt_asset_tool/static_semantic_devtest.py`
- `pt_asset_tool/blender/apply_static_semantic_devtest.py`
- `pt_asset_tool/blender/check_static_semantic_devtest.py`

O runner de static foi preparado para alteração automática semanticamente relevante, inclusive topologia no writer static, com reimport/verificação automática.

Domínios relevantes no corpus incluem PLAYER, MONSTER, WEAPON_ITEM, EFFECT e MAP.

### 8. Materiais

Novos:

- `pt_asset_tool/model062_material_writer.py`
- `pt_asset_tool/model062_material_devtest.py`
- `pt_asset_tool/stage072_material_writer.py`
- `pt_asset_tool/stage072_material_devtest.py`

A edição é candidate/fixed-size e deve provar que somente bytes autorizados de material mudaram.

Stage 0.72 tem gate material separado; não tratar “materiais” como se Model0.62 cobrisse mapas Stage.

### 9. Texturas BMP/TGA proprietárias

Novos/alterados:

- `pt_asset_tool/texture_codec_devtest.py`
- `pt_asset_tool/model062_texture_audit.py`
- `dev_tests/test_ship_bmp_writer.py`

Foi preparado roundtrip automático decode → alteração → rebuild para famílias proprietárias conhecidas, incluindo a segunda família BMP usada em chrselect/ships que antes tinha decode mas não build reverso.

A matriz deve atribuir PASS por **domínio + família física**, não por um único codec global.

### 10. Multilayer TexLink

Novo:

- `pt_asset_tool/texlink_devtest.py`

A cobertura deve ser baseada em assets que realmente possuem multilayer TexLink, não em toda a família static/rigid do domínio.

Profundidade/chain fora do contrato suportado deve bloquear explicitamente a 1.0; não considerar parse-only como authoring PASS.

### 11. Stage 0.72

Alterados/novos:

- `pt_asset_tool/stage072_authoring_candidate.py`
- `pt_asset_tool/stage072_geometry.py`
- `pt_asset_tool/blender/extract_stage072_saved_edit.py`
- `pt_asset_tool/stage072_semantic_devtest.py`
- `pt_asset_tool/blender/apply_stage072_semantic_devtest.py`

O candidate agora suporta deformação multi-vértice XYZ dentro da grade 1/256, reconstruindo StageArea e normais das faces incidentes. UV e material têm gates separados.

A R14 decidiu **não** adicionar alteração arbitrária de topology/face-count em Stage 0.72 para 1.0 sem necessidade explícita, porque isso exigiria reconstrução arriscada de arrays/pointers serializados. Topology count continua fail-closed. O escopo 1.0 já exige mapa, geometria, UV, materiais, texturas e runtime; não exige explicitamente criação estrutural de faces Stage.

Os audits corpus-wide existentes de todos os 63 Stage0.72 devem ser integrados ao `release-1-auto`:

- parser/corpus;
- StageArea/StageMapRect;
- provenance/rebuild de normais;
- presença/semântica de texturas.

### 12. Writer/corpus audits

Novo/alterado:

- `pt_asset_tool/model062_corpus.py`
- `pt_asset_tool/writer_corpus_audit.py`
- `dev_tests/test_writer_corpus_explicit_paths.py`

A intenção é separar presença de capability de prova corpus-wide e impedir falso PASS por representative isolado.

## Estado da matriz 1.0 no handoff

O coverage offline regenerado está `PARTIAL` e reporta 52 blockers, em grande parte porque este ambiente não possui o client real e portanto os gates físicos ainda não foram executados. Não interpretar os 52 como 52 features de código ausentes.

Blockers funcional/externo mais importantes neste momento:

1. executar no client real o runner consolidado `validate release-1-auto` quando ele estiver terminado/validado;
2. amostra real Mixed-Physique;
3. runtime/game acceptance representativo depois de todos os gates automáticos ficarem verdes;
4. publish/restore real somente depois da promoção por família;
5. os dois contextos LOD realmente incompatíveis devem continuar diagnosticados/fail-closed até haver evidência autoritativa.

## Validação no momento do handoff

- `python3 -m compileall -q .`: **PASS**.
- suíte focada das frentes mais alteradas na R14: **85 PASS / 0 FAIL**.
  Incluiu `release_1_auto`, `release_1_coverage`, LOD corpus, generic import, rigid census, object-local geometry contract, Model0.62 corpus/material/texture, standalone animation/rigid, static semantic e writer corpus paths.
- execução ampla `pytest dev_tests` no handoff: parou em `--maxfail=20` com **82 PASS + 20 FAIL**, e os 20 FAIL exibidos eram todos por ausência de `/mnt/data/pt_asset_r14_work/fixture_client`/arquivos dessa fixture.
- uma tentativa de rodar automaticamente todos os testes sem referência textual a `fixture_client` passou de 90% duas vezes, mas atingiu timeout antes do sumário; portanto **não declarar esse lote como PASS completo**.
- última regressão ampla confirmada antes das mudanças finais de LOD/coverage: **124/124 PASS** reproduzíveis.
- última baseline histórica confirmada antes das mudanças finais: **175 PASS / 1 SKIP**.
- recomenda-se repetir ambos antes do próximo snapshot formal.

## Onde o trabalho parou exatamente

O trabalho parou durante a auditoria de **falsos verdes do `release-1-auto`**.

O próximo foco deveria ser:

1. revisar cada célula MATERIALS / TEXTURES / OBJECT_LOCAL_ANIMATION / MULTILAYER_TEXLINK / STAGE072 para garantir que `PASS` só vem de execução real, e não de presença de módulo;
2. integrar ao `release-1-auto` os audits Stage corpus-wide;
3. integrar o censo LOD atual (1906 exact + 22 fixed16 + 10 single-tier full-container + 2 fail-closed) à matriz por domínio;
4. finalizar censo rigid corpus-wide no client real: cada rigid precisa cair em model-info+LOD+skeleton, resolved-skeleton, ou standalone structural PASS;
5. garantir que INX/SMB no-op/edit/semantic corpus gates pintem a matriz por domínio apenas depois de execução real;
6. garantir que proprietary texture gates cubram cada família presente em cada domínio;
7. rodar regressão reproduzível completa e baseline histórica novamente;
8. somente então gerar uma versão para o utilizador executar com **um único comando automático** (`validate release-1-auto` ou equivalente final).

## Interação esperada com o utilizador

O utilizador pediu explicitamente autonomia. Portanto:

- não enviar snapshots a cada incremento;
- não pedir edições manuais no Blender;
- não pedir testes por objeto/vértice/LOD;
- continuar autonomamente até um gate externo real;
- quando chegar ao gate, entregar uma única versão e preferencialmente um único comando automático;
- se a única lacuna física for Mixed, pedir especificamente uma amostra Mixed-Physique autêntica;
- gate humano posterior deve ser apenas visual/runtime integrado dentro do jogo.

## Arquivos importantes deste handoff

- `RETOMADA_DESENVOLVIMENTO_R14.md` — este arquivo.
- `VALIDATION_STATUS_R14_HANDOFF.md` — fotografia de validação.
- `R14_CHANGED_FILES.txt` — adicionados/alterados contra R13.
- `R13_TO_R14_WORKING.diff` — diff textual completo contra R13.
- `app/pt_build/devtest/release_1_coverage_handoff.json` — matriz offline regenerada.
- `app/pt_build/devtest/rigid_lod_context_corpus_handoff.json` — censo LOD atual.

