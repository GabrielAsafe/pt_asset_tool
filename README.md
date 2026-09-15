# PT Asset Tool R14 1.0.0 — Distribuição Completa

Esta é a distribuição 1.0.0 com documentação consolidada e completa.

## Estado

- automatic gate: **PASS**;
- automatic blockers: **0**;
- package: **SAFETY LOCKED**;
- produção/client/server writes: **não autorizados por padrão**;
- código funcional: baseline certificado 1.0.0;
- documentação: referência CLI gerada do parser + manuais completos.

## Primeiro passo

Leia `START_HERE.md`, depois `docs/INSTALLATION_QUICKSTART_1_0.md`.

## Verificação

```bash
./VERIFY_PACKAGE.sh
```

## Aplicação

```bash
cd app
python3 pt_asset.py --help
python3 pt_asset_gui.py
```
