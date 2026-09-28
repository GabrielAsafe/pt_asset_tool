# Integration validation — Asset Quarantine V2.6 — 2026-09-27

Escopo:

- Q0 somente para documented invalid orphan com zero linkage/root/evidence;
- Q1 component review sem write automático;
- apply com confirmação explícita, stale-plan guard e hash preflight;
- storage fora do client em `pt_build/quarantine_store`;
- restore transacional com verificação SHA-256;
- nenhum delete.

Gates do pacote devem incluir testes de plan/apply/restore/stale-plan, regressão asset-retention e `VERIFY_PACKAGE.sh` em árvore limpa.
