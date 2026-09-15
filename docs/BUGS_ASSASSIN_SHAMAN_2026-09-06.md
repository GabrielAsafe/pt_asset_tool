# Bugs e gaps — implementação Assassin e Shaman

Data: 2026-09-06  
Escopo: source/runtime Summit + assets/client contracts  
Objetivo: documento operacional separado para a migração dos jobs 9/10.

## Convenções

Cada item é classificado como:

- **CONFIRMADO** — observado diretamente no source/runtime contract ou em run físico;
- **GAP DE MIGRAÇÃO** — feature da referência não encontrada/ativa no current source;
- **RISCO** — incompatibilidade capaz de produzir comportamento incorreto;
- **PENDENTE DE PROVA** — evidência parcial; não tratar como bug até confirmar.

## Resumo executivo

Os assets físicos conhecidos de Assassin/Shaman estão muito mais completos do que a implementação runtime. No run real 0.16.0, o agregador obteve `core_unresolved_count=0`, mas `runtime_ready=false` para as duas classes.

Blockers reportados:

```text
Assassin
  RUNTIME_DISABLED_BY_MAX_JOBNUM
  CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES

Shaman
  RUNTIME_DISABLED_BY_MAX_JOBNUM
  CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES
```

Portanto o principal trabalho restante é source/runtime, não caça indiscriminada de assets.

---

## AS-001 — `MAX_JOBNUM` bloqueia os slots 9 e 10

**Severidade:** blocker  
**Estado:** CONFIRMADO

O current source possui capacidade estrutural para 10 jobs (`MAX_JOB_CAPACITY=10`) e referências/rows para Assassin/Shaman nos slots 9/10, mas o runtime audit encontrou `MAX_JOBNUM=8`.

Impacto esperado:

- criação/seleção de personagem pode rejeitar slots 9/10;
- loops que usam `MAX_JOBNUM` podem ignorar as classes;
- tabelas dimensionadas por capacity podem existir, mas caminhos runtime baseados em job count continuam desligados.

Correção não deve ser apenas trocar `8 -> 10`. Antes de promover:

1. localizar todos os usos de `MAX_JOBNUM`;
2. classificar cada uso como loop de UI, validation, packet, persistence, skill, equipment, ranking, etc.;
3. confirmar que arrays/tabelas associados têm 10 entradas válidas;
4. executar criação/login/save/relog com jobs 9/10.

---

## AS-002 — Registry `SkillDataCode[]` atual não é compatível com os índices físicos M6/M7

**Severidade:** blocker  
**Estado:** CONFIRMADO

Os motion roots físicos das duas classes usam `MotionInfo.SkillCodeList[]` como índices na registry de skills. O run do agregador reporta:

```text
CURRENT_REGISTRY_INCOMPATIBLE_WITH_REFERENCE_INX_INDICES
```

A referência EU coloca o bloco Assassin/Shaman em posições próprias; o current Summit possui uma registry ativa diferente, e as entradas das classes novas não estão ativas no mesmo layout.

Impacto:

- asset INX/SMB pode estar perfeito;
- `SetMotionFromCode(CHRMOTION_STATE_SKILL)` pode interpretar o mesmo byte como outra skill;
- animação errada ou ausência de motion pode ocorrer mesmo sem ficheiro missing.

Não corrigir remapeando motions “pela ordem”. O mecanismo correto deve respeitar `SkillCodeList`.

Estratégia recomendada:

- preservar registry Summit existente quando possível;
- alocar índices livres para Assassin/Shaman;
- remapear `SkillCodeList` de M6/M7 de forma explícita e validada;
- ou, se a registry reference for restaurada, auditar todas as classes Summit afetadas.

A ferramenta deve produzir um Migration Plan antes de qualquer write.

---

## AS-003 — Entradas Assassin/Shaman existem no source atual, mas não estão ativas na registry usada

**Severidade:** blocker/alta  
**Estado:** CONFIRMADO no corpus analisado

Foram encontradas entradas/linhas relativas às duas classes no current source, porém não participam da registry ativa da mesma forma que a referência EU. O audit current reportou registry legacy ativa com 196 entradas e nenhuma contagem de classe atribuída a Assassin/Shaman.

Isto é diferente de “não existe código”: há material de migração, mas ele não está ligado ao caminho runtime final.

Ação:

- tratar comentários/legacy blocks como donor source, não runtime ativo;
- comparar semanticamente cada row com a referência;
- gerar patch planejado, não simplesmente descomentar blocos.

---

## AS-004 — Motion assets estão prontos, mas skill->motion só funciona depois da registry

**Severidade:** alta  
**Estado:** CONFIRMADO

Prova física atual:

```text
Assassin
  M6Bip.inx
  m6.smb
  17 MotionInfo state=SKILL
  SMB validation=PASS

Shaman
  M7Bip.inx
  m7.smb
  18 MotionInfo state=SKILL
  SMB validation=PASS
```

Os `LinkFile` dos configs foram verificados por link code/SpeedSum. Isto elimina a hipótese de que os motion roots estejam apenas “adivinhados pelo nome”.

O bug não é ausência do container de animação; é o binding runtime entre skill e record.

---

## AS-005 — Implementação client/server das skills está incompleta no current source

**Severidade:** alta  
**Estado:** GAP DE MIGRAÇÃO

Nos audits iniciais do source ativo, Assassin/Shaman não apresentavam cobertura runtime equivalente à referência. A referência EU contém handlers específicos e vários call sites; o Summit current preserva partes da migração, mas não fecha o caminho moderno completo.

Foi observado na referência:

- Assassin: cobertura server-side completa no handler moderno para o conjunto analisado;
- Shaman: cobertura server-side parcial no handler moderno, com paths delegados/legacy que precisam de tracing adicional;
- client-side também usa handlers/delegates variados.

Não usar “arquivo C++ existe” como critério de implementação. A prova deve seguir:

```text
SkillID
 -> dispatch/call site
 -> handler
 -> packet/data
 -> server validation/effect
 -> client effect/audio/animation
```

---

## AS-006 — Alterar apenas Job ID não garante creation/login/persistence

**Severidade:** alta  
**Estado:** RISCO CONFIRMADO POR ARQUITETURA; runtime end-to-end ainda pendente

Mesmo depois de `MAX_JOBNUM`, é necessário verificar todos os boundaries que serializam ou validam job/class:

- character creation;
- login/select;
- save/relog;
- database/user records;
- packet fields;
- class restrictions;
- equipment/spec;
- skill point tables;
- rank/quest progression.

Acceptance test obrigatório:

1. criar Assassin;
2. relogar;
3. equipar item permitido;
4. aprender skill;
5. usar skill;
6. mudar mapa;
7. salvar/relogar;
8. repetir para Shaman.

---

## AS-007 — Assets completos conhecidos não certificam classe completa

**Severidade:** lógica de integração  
**Estado:** CONFIRMADO

A 0.14.0 inicialmente podia induzir a conclusão “assets completos” porque todos os assets descobertos estavam presentes. Isso foi corrigido a partir de 0.14.1.

No run 0.16.0:

- core asset unresolved = 0;
- runtime ready = false.

A UI/integrador deve manter estes indicadores separados permanentemente.

---

## AS-008 — Variantes de head/body/costume não são blockers de classe

**Severidade:** baixa para runtime / média para completeness visual  
**Estado:** CONFIRMADO

O primeiro aggregation run classificou 44 divergências e 112 ausências como problemas duros. A análise mostrou que eram variantes individuais de INX/head/body/costume/seasonal.

Política corrigida:

- escolher donor prioritário quando o target não tem o path;
- guardar todas as variantes em `reference_variants/`;
- gaps ficam como `OPTIONAL_MISSING`;
- não bloquear playable core.

Ainda assim, estes gaps devem ser revistos antes de declarar “todas as variantes oficiais recuperadas”.

---

## AS-009 — Algumas head configs de Shaman são recuperáveis apenas em donor

**Severidade:** baixa/média  
**Estado:** CONFIRMADO no corpus analisado

Foram observados configs de head Shaman que não existiam no Summit target mas estavam presentes no PT_EU, com `LinkFile` verificado para `M7Bip`.

Isto valida a estratégia donor-based, mas também mostra que “M7 existe” não implica que todas as aparências/head variants estejam no target.

O agregador já trata isso como recuperação/variante, não runtime blocker.

---

## AS-010 — Source archived/build pode produzir falso positivo de implementação

**Severidade:** tooling/investigação  
**Estado:** CORRIGIDO NA FERRAMENTA

`old_src_antes_do_porte/`, build dirs, deps e tooling apareciam inicialmente como evidência do current source. Isto fazia código histórico parecer runtime ativo.

A partir de 0.14.1 estes namespaces são excluídos da evidência ativa.

Regra para integração manual: código em archive é donor/reference, nunca prova de que o executável atual o usa.

---

## AS-011 — Áudio não é blocker físico atual, mas skill attribution ainda pode ser parcial

**Severidade:** baixa para presença / média para semântica  
**Estado:** CONFIRMADO

A família source-backed identificada contém 51 WAVs e estava presente no target no run 0.14.1:

- Assassin 17/17;
- Shaman 34/34.

Nem todo WAV foi inicialmente associado a uma skill específica. Alguns são class-level audio conhecidos pelo range/tabela, enquanto apenas subset possui call site direto já provado.

A aplicação deve distinguir:

- `CLASS_AUDIO`;
- `SKILL_DIRECT_AUDIO`;
- `PARTICLE_TRANSITIVE_AUDIO`;
- `UNATTRIBUTED_CLASS_AUDIO`.

---

## AS-012 — Effects `.part` conhecidos estão presentes, mas coverage do contrato ainda deve crescer

**Severidade:** média  
**Estado:** PENDENTE DE PROVA COMPLETA

Os effects diretamente provados pelos handlers e as dependências transitivas auditadas estavam presentes. Porém ausência de referência descoberta não prova que a skill não usa outro effect por ASM/legacy/event path.

Não declarar `effects_complete=true` até o runtime call graph ou uma tabela authoritative fechar todas as skills.

---

## AS-013 — Shaman reference registry/classification requer cuidado de parser

**Severidade:** tooling  
**Estado:** PENDENTE/OBSERVAÇÃO

Um run 0.14.3 reportou `reference entry_count=208`, `Assassin=20` e `Shaman=25` na classificação de registry. O catálogo de skills usado pelos contracts possui 20 skills de Shaman. A diferença deve ser tratada como sinal de que classificação de registry por faixa/nome pode capturar entradas relacionadas adicionais e não deve substituir o catálogo de skill definitions.

A regra é:

- índice físico da registry é evidência para motion selectability;
- catálogo `shared/skill.h`/definitions é evidência para o conjunto de skills;
- não inferir quantidade de skills apenas por `class_counts` da registry.

---

## Ordem recomendada de correção

### Etapa 1 — Migration planner read-only

Gerar automaticamente:

```text
current job table
reference job table
current skill registry
reference skill registry
M6 SkillCodeList usage
M7 SkillCodeList usage
free/current indices
collisions
proposed mapping
```

Nenhum write.

### Etapa 2 — Patch source em branch/staging

Tratar:

- `MAX_JOBNUM` e todos os call sites dependentes;
- registry rows;
- client handlers;
- server handlers;
- packet/data boundaries.

### Etapa 3 — Remap INX apenas se necessário

Se a estratégia escolhida preservar a registry Summit e alocar novos índices, produzir novos M6/M7 com writer certificado e validar:

- parse roundtrip;
- MotionInfo count;
- `SkillCodeList` esperado;
- SMB pairing;
- no unintended diff fora dos bytes autorizados.

### Etapa 4 — Runtime acceptance

Executar a matriz de testes de criação/login/skill/combat/equipment/map/relog para as duas classes.

## Critério para encerrar este documento

Assassin/Shaman só deixam de estar “em migração” quando:

- jobs 9/10 aceitos no runtime;
- registry compatível com M6/M7;
- skills ativas client/server verificadas;
- creation/login/save/relog PASS;
- equipment restrictions PASS;
- 20 skill definitions por classe auditadas;
- skill animations selecionadas corretamente;
- áudio/effects/UI presentes;
- nenhum core missing no aggregate;
- runtime smoke PASS em ambas.
