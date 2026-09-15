# PT Asset Tool R14 — START HERE

## Estado autoritativo

- versão: **1.0.0**;
- release: **CERTIFIED**;
- automatic gate: **PASS**;
- automatic blockers: **0**;
- safety: **LOCKED BY DEFAULT**;
- client/server modificados pela certificação: **não**;
- target-content gaps: documentados e não bloqueantes para capability do tool;
- writer promotion/publish/restore: operação externa, não ativada pelo pacote.

## Instalação em 4 passos

```bash
./VERIFY_PACKAGE.sh
cd app
python3 pt_asset.py config set-client-root "/path/cliente"
python3 pt_asset.py validate environment-auto
```

Opcionalmente configure o server com `config set-server-root` e rode `validate server-environment-auto`.

## GUI

```bash
python3 pt_asset_gui.py
```

## Documentação

- `docs/README.md` — índice autoritativo;
- `docs/MANUAL_UTILIZADOR.md` — manual operacional completo;
- `docs/CLI_REFERENCE_1_0.md` — referência exaustiva dos comandos;
- `docs/GUI_MANUAL_1_0.md` — GUI;
- `docs/MANUAL_DESENVOLVEDOR.md` — engenharia/reverse engineering;
- `docs/FEATURE_MATRIX_1_0.md` — capability completa;
- `docs/SECURITY_SAFETY_1_0.md` — regras de segurança;
- `docs/KNOWN_LIMITATIONS_1_0.md` — limitações conhecidas.

## Importante

A release estar certificada não significa que todo conteúdo do target esteja perfeito. Missing/corrupt target textures permanecem visíveis nos audits. Não faça recovery/copias manualmente para “zerar” relatórios.
