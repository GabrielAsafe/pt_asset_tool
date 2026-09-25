# Evidência Final de Certificação — PT Asset Tool R14 1.0.0

<!-- PT_HISTORICAL_RELEASE_CONTEXT_2026-09-25 -->

> **Contexto histórico:** este documento preserva evidência/claims da Release 1.0 na data indicada. Para validar o checkout atual, use `docs/engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md` e não trate contagens/flags históricas como resultado de uma execução nova.

Data do run físico final: 2026-09-14.

## Gate físico pós-version bump

- `automatic_gate_status=PASS`
- `blockers=[]`
- `release-1-auto rc=0`
- `PACKAGE_VERIFY=PASS version=1.0.0`
- `RELEASE10_ASSERT=PASS`
- `AUTOMATIC_BLOCKERS=0`
- `PRODUCTION_AUTHORIZED=0`
- `CLIENT_WRITE_AUTHORIZED=0`
- `SERVER_WRITE_AUTHORIZED=0`
- `RELEASE10_CLEAN_EXTRACT_VERIFY=PASS`

## Runner final

Todas as cinco etapas retornaram zero:

```text
01_finalize_release10:0
02_release_1_auto_post_version:0
03_verify_package:0
04_assert_release_contract:0
05_rebuild_clean_release:0
```

Estado esperado do pacote original certificado: `RELEASE_1_0_CERTIFIED_SAFETY_LOCKED`.

## Archive original certificado

`PT_Asset_Tool_R14_1.0.0_2026-09-14.tar.gz`

SHA-256 final do rebuild pós-gate original:

`eb1ab03a6fdf64c41f921aae3592b3ae6874bf4e1a4c2bf7c26e92faf9d92ce9`

A distribuição ZIP `COMPLETE` é um repackaging da mesma base de código 1.0.0 com documentação expandida; por isso possui checksum próprio e o pacote é verificado novamente após a atualização documental.

## Conteúdo target

- proprietary texture capability: PASS;
- codec failures: 0;
- target-content invalid payloads: 2;
- Model0.62 texture audit capability: PASS;
- target-content readiness: permanece FAIL/documentado, não blocker da capability.
