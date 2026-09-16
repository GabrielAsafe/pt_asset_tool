# Changelog consolidado — Asset Contracts / Aggregator

Este changelog cobre especificamente a linha de trabalho iniciada durante a reconstrução client/server do Summit. Para histórico antigo do Design Tool, consultar `../CHANGELOG.md`.

## 0.17.1 — Documentation Handoff

- documentação consolidada de contexto, descobertas e arquitetura;
- bugs/gaps Assassin/Shaman em documento separado;
- guia de integração;
- roadmap priorizado;
- atualização do índice de docs/START_HERE;
- nenhuma mudança na política de write nem no backend funcional 0.17.0.

## 0.17.0 — Full Summit Superset

- client-wide superset;
- server-wide superset;
- combined `summit-superset`;
- server namespace normalization;
- runtime-state/tooling exclusions;
- compact `reports_bundle.zip`;
- CLI/API/GUI no mesmo backend.

## 0.16.0 — Superset Aggregator

- core vs optional variants;
- preferred donor variant + archive de todas as variantes;
- optional gaps não bloqueiam playable core;
- runtime blockers separados de asset readiness.

## 0.15.0 — Aggregation MVP

- contracts das 10 classes;
- staging overlay;
- SHA-256 dedupe;
- provenance/manifest/conflicts/missing;
- GUI/CLI.

## 0.14.3 — Skill Motion Registry

- parse `SkillCodeList`;
- current/reference skill registry;
- binding por índice físico;
- runtime registry incompatibility detection.

## 0.14.2 — Motion Contracts

- class configs;
- verified INX LinkFile;
- motion root;
- MotionInfo state;
- paired SMB validation.

## 0.14.1 — Contract Coverage

- completeness fail-closed;
- exclusão de source archived/build/deps;
- 51 class WAVs Assassin/Shaman;
- melhoria de handler parsing.

## 0.14.0 — Source Contracts

- SourceTree current/reference;
- ContractGraph;
- skill/source census;
- Assassin/Shaman first-class audits;
- donor-aware resolution.

## Antes de 0.14 — descoberta que motivou a arquitetura

- diferenças de case/Thumbs criavam falsos positivos;
- basename/path/hash precisavam ser separados;
- server packaging precisava de normalização;
- runtime state precisava ser excluído do asset corpus;
- blind merge foi abandonado em favor de provenance + contracts + staging.
