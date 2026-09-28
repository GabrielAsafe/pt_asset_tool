# Integração V2.5 — Effect Runtime Roots + Root-Unreachable Components

Data: 2026-09-27

## Objetivo

Reduzir falsos `ORPHAN_CANDIDATE` no client legacy sem relaxar a política fail-closed.
A revisão adiciona roots derivados apenas de loaders de efeito conhecidos e agrupa
subgrafos ligados, porém sem strong root, para revisão por componente.

## Contratos de segurança

- read-only sobre client/server; outputs somente em `pt_build`;
- source literal isolado não vira runtime root;
- basename ambíguo não vira runtime root;
- ContractGraph edge isolado continua REVIEW quando nenhuma strong root alcança o componente;
- component membership não autoriza quarantine/delete;
- Monster/NPC conserva bundle/catalog guard fail-closed;
- `deletion_authorized=false`.

## Outputs

```text
pt_build/effect_runtime_coverage/result.json
pt_build/asset_retention/components.tsv
pt_build/asset_retention/components.json
```

## Validação de desenvolvimento

Os testes focados cobrem resolução pelo namespace `Effect/AnimationData`, paths completos
de loaders conhecidos, chamadas multiline, ambiguidade de basename, agrupamento de
componentes e filtro CLI/API por `component_id`. A regressão focada e o package verifier
devem ser rerodados no pacote final desta revisão.

## Validação aproximada sobre material fornecido

Uma simulação read-only usando a árvore de paths do client fornecida pelo projeto e o
source consolidado disponível encontrou centenas de roots de efeito resolvíveis, incluindo
famílias Return, ScoutHawk, SkillExtremeShield e BrutalSwing. Esse número é evidência de
cobertura da heurística, não substitui o Censo no checkout atual do usuário.
