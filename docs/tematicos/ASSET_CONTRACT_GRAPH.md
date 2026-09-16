# Asset Contract Graph — source-backed completeness

> Handoff corrente e próximos passos: `HANDOFF_TECNICO_CONSOLIDADO_2026-09-06.md` e `ROADMAP_POS_0.17.1.md`.

## Objetivo

A ferramenta deixa de tratar “ficheiro existente” como sinónimo de “conteúdo completo”. O novo Asset Contract Graph representa entidades do jogo e as relações comprovadas entre client, server e source C/C++.

A primeira integração cobre **Assassin** e **Shaman** e usa o source Summit atual como estado runtime, com o source EU apenas como referência read-only para relações que faltam no Summit.

## Princípios

1. **Source é evidência, não destino de escrita.** Nenhum audit modifica C/C++, client ou server.
2. **Relações comprovadas ficam separadas de obrigatoriedade.** Uma referência encontrada no EU prova uma ligação; não prova automaticamente que o asset é obrigatório no Summit.
3. **Sem bulk merge.** O motor classifica `PRESENT_TARGET`, `RECOVERABLE_REFERENCE`, `CONFLICT` e `MISSING_UNKNOWN`; copiar/gerar continua sendo uma fase posterior e explícita.
4. **Closure transitiva.** `.part` usa o parser já existente e segue referências internas para texturas, modelos, áudio e outros `.part`.
5. **Proveniência.** Cada edge do grafo registra evidence/source e confidence.

## Fontes configuráveis

- `source_root`: source C/C++ Summit atual.
- `reference_source_root`: source C/C++ de referência (EU).
- `contract_donor_clients`: zero ou mais clients read-only no formato `LABEL=PATH`.

CLI:

```bash
python3 pt_asset.py config set-source-root /path/to/summit-source
python3 pt_asset.py config set-reference-source-root /path/to/eu-source
```

Os donor clients podem ser configurados pela GUI em **Servidor / Asset Enrichment → Asset Contracts** ou passados ao audit:

```bash
python3 pt_asset.py audit player-class-contracts \
  --donor-client OFFICIAL=/home/gabriel/old/velho \
  --donor-client PT_EU=/path/to/reference/client
```

## Source contracts

```bash
python3 pt_asset.py audit source-contracts
```

Produz:

- `pt_build/asset_contracts/source_contract_census.json`
- `pt_build/asset_contracts/source_contract_graph.json`

O scanner extrai atualmente:

- `SKILL_SOUND_* -> numeric id -> WAV`;
- referências literais a assets;
- `SkillPlaySound(...)` nos handlers;
- `.part` carregados pelos handlers de Assassin/Shaman;
- catálogo Assassin/Shaman do `shared/skill.h` de referência;
- `MAX_JOBNUM`, `MAX_JOB_CAPACITY` e rows de jobs;
- templates source-proven de `DorpItem -> it%s.ASE/SMD`, ícones de item e companions `SPP/SPC/SPM` de Field.

No source fornecido em 06/09/2026, o census confirma `MAX_JOBNUM=8`, `MAX_JOB_CAPACITY=10`, jobs Assassin/Shaman nos slots 9/10, 40 skills Assassin/Shaman na referência e ausência dos handlers `CAssassinSkillHandler.cpp` / `CShamanSkillHandler.cpp` no source Summit atual.

## Player class contracts

```bash
python3 pt_asset.py audit player-class-contracts
```

Produz:

- `pt_build/asset_contracts/player_class_contract_census.json`
- `pt_build/asset_contracts/player_class_contract_graph.json`

O grafo parte de:

```text
PLAYER_CLASS
  -> SKILL
      -> button normal/hover
      -> TGA explícito
      -> AUDIO (via SkillPlaySound -> sound map -> WAV)
      -> PART (e closure transitiva do PART)
```

### Required vs evidence-only

Nesta fase:

- buttons normal/hover são `required=true`, porque fazem parte do catálogo explícito de skill;
- TGA, áudio e `.part` permanecem `required=null` até o runtime Summit ou uma regra certificada provar obrigatoriedade;
- `RECOVERABLE_REFERENCE` significa “há uma cópia física num donor”, não “autorizar copiar”.

## Estado runtime de Assassin/Shaman

O audit não confunde “assets presentes” com “classe funcional”. Ele reporta separadamente o estado do source. Exemplo de blocker atual:

```text
MAX_JOBNUM = 8
Assassin slot = 9
Shaman slot = 10
```

Portanto uma classe pode ter 100% dos assets físicos e continuar `RUNTIME_DISABLED_BY_MAX_JOBNUM`.

## Próxima camada

A mesma infraestrutura deve ser usada, sem criar scanners paralelos, para:

- `PLAYER_CLASS -> MOTION_CONTRACT -> INX/SMB`;
- `SKILL -> animation/action -> sound/effect`;
- `ITEM -> OpenItem -> client catalog -> DorpItem -> model/icon -> drop/shop/quest`;
- `FIELD -> SMD/source authoring -> SPP/SPC/SPM`, respeitando companions opcionais;
- geração de asset/server definition apenas quando `generator` + invariantes estiverem certificados.

O alvo final é um comando por entidade, por exemplo:

```text
pt_asset audit class Assassin
pt_asset audit item WA108
pt_asset audit field ruin-1
```

que retorne `PRESENT`, `RECOVERABLE`, `GENERATABLE`, `CONFLICT` ou `MISSING` por componente, com evidência e proveniência.

## 0.14.1 — coverage is not completeness

`PRESENT_TARGET` means only that a discovered physical expectation is present. It no longer implies that the class contract itself is fully discovered or migrated.

PLAYER_CLASS reports now separate:

- `proven_required_assets_complete` — currently the source-proven required UI buttons;
- `source_contract.reference_state` — how much of the 20-skill client/server implementation is visible in the EU reference source;
- `source_contract.migration_state` — how much corresponding class-specific runtime source exists in the active Summit source tree;
- `overall_status` — fail-closed synthesis of the above.

The active source scanner excludes archived/build/dependency/tooling directories such as `old_src_antes_do_porte`, `build_*`, `dist_*`, `deps`, `Dependency`, `vendor`, and `pt_asset_tool`.

### Class audio families

The EU source reserves contiguous skill-audio blocks anchored by source symbols:

- Assassin: `SKILL_SOUND_STINGGER` through `SKILL_SOUND_STORM` — 17 resolved WAV paths in the supplied reference source.
- Shaman: `SKILL_SOUND_DARK_BOLT1` through `SKILL_SOUND_G_NAIL2` — 34 resolved WAV paths.

These 51 WAVs are audited as `CLASS_AUDIO`. A WAV is linked to a particular skill only when direct source evidence proves that edge; otherwise it remains a class-level asset rather than being guessed.

## 0.14.2 — Player Class Motion Contract

A cadeia de animação de Assassin/Shaman passa a ser auditada como contrato próprio:

```text
PLAYER_CLASS
  -> BODY/HEAD config lógico (.ini/.inf no source)
  -> config físico .inx
  -> LinkFile verificado por SpeedSum/link code
  -> motion root .inx
  -> MotionInfo states
  -> paired motion .smb
```

### Evidência e fail-closed

- `CHARACTERCLASS_Assassin/Shaman` e as tabelas `saAssassinHeadModel` / `saShamanHeadModel` fornecem os caminhos de configuração.
- `.ini` e `.inf` são normalizados para o payload runtime `.inx`, conforme a convenção já usada pelos bundles.
- Um `LinkFile` só entra no grafo se `verified_inx_link_target()` validar o código SpeedSum. Basename, diretório e nome da classe não certificam um link.
- Se o próprio config INX possui `MotionInfo`, ele pode ser `SELF_MOTION_OWNER`.
- O root dominante usa primeiro maioria entre `BODY_BASE_CONFIG`; configs de costume/cabeça são evidência adicional, não voto prioritário.
- `ANIMATIONTYPE_Skill` prova apenas que a skill solicita o estado de classe `SKILL` (`0x150`) quando esse estado existe. Não prova qual dos records `SKILL` é a animação da skill.
- `specific_skill_motion_record_certified` permanece `false` até aparecer evidência source/runtime que selecione um record concreto.

### Estados do audit

- `TARGET_CLASS_SKILL_MOTION_READY` — root INX + estado `SKILL` + SMB estão presentes no Summit e a validação não falhou.
- `CLASS_SKILL_MOTION_RECOVERABLE` — a cadeia é provada mas algum componente físico vem de donor.
- `MOTION_SMB_NOT_PAIRED` / `MOTION_SMB_UNAVAILABLE` — MotionInfo existe mas a ligação física ao SMB ainda não está fechada.
- `SKILL_MOTION_STATE_NOT_DECLARED` — o root existe, porém não declara o estado `SKILL`.
- `BODY_MOTION_ROOT_NOT_VERIFIED` / `MOTION_ROOT_UNRESOLVED` — a cadeia de LinkFile/config ainda não foi fisicamente provada.

O audit escreve `pt_build/asset_contracts/player_class_motion_contracts.json` e incorpora o mesmo resultado dentro de cada classe em `player_class_contract_census.json`.

## 0.14.3 — SkillCodeList / runtime motion registry

A resolução específica de animação deixa de depender da contagem/ordem dos records `SKILL`. O runtime seleciona o motion através de `MotionInfo.SkillCodeList[]`; cada byte endereça a registry de skills (`saSkillData` na referência EU, `SkillDataCode[]` no Summit legado). O audit usa o índice físico do INX como evidência e produz:

- `skill_motion_bindings`: associação skill → MotionInfo e o índice de registry que a provou;
- `registry_alignment`: o que o mesmo índice significa no Summit atual;
- `runtime_motion_selectability_status`: se a registry atual é estruturalmente compatível;
- `REFERENCE_SKILLCODELIST_EXACT`: binding físico certificado contra a referência, sem afirmar que o runtime Summit já consegue selecioná-lo;
- `CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES`: os assets estão presentes, mas a tabela runtime precisa de migração/remapeamento.

Os IDs numéricos de play-code entre famílias de source não são comparados ingenuamente: a ferramenta trata nomes/índices e evidência física separadamente, porque os enums/macros EU e legado podem usar valores diferentes.



## 0.15.0 — 10 classes + Aggregation Planner

O provider `PLAYER_CLASS` usa agora o mesmo pipeline para as dez classes. O agregador percorre apenas edges alcançáveis a partir das entidades selecionadas e transforma resoluções físicas em um plano explícito: `KEEP_TARGET`, `RECOVER`, `RECOVER_DEDUPED`, `CONFLICT`, `MISSING` ou review.

A materialização é um overlay em `pt_build/aggregate/player_classes/<selection>/client_overlay`; nunca escreve no client/server/source configurado. Conflitos de donor só são resolvidos automaticamente quando todos os candidatos vivos têm o mesmo SHA-256. O manifest mantém proveniência, razão de decisão e runtime blockers separados de asset staging readiness.


## 0.17.0 — Full Summit Superset

O ContractGraph continua sendo a camada de evidência; a 0.17.0 acrescenta materialização genérica de staging. `build_summit_superset()` combina o bundle semântico de PLAYER_CLASS/SKILL com superset path-based client/server. Isto permite aumentar o corpus sem transformar presença física em prova semântica: providers continuam responsáveis por `required/optional`, enquanto o agregador só resolve proveniência, variantes, staging e integridade.

O objetivo para ITEM/FIELD/MONSTER/NPC é reutilizar esta mesma camada, não criar novos copiadores.
