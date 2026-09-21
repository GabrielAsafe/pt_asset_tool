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

Leia `docs/README.md`, depois `docs/comece_aqui/INSTALLATION_QUICKSTART_1_0.md`.

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

## Dependências

Antes de testar features que usam aplicações externas, rode:

```bash
cd app
python3 pt_asset.py dependencies
```

O diagnóstico informa o que falta, **por que** a dependência é necessária e como instalar/configurar. Veja `docs/comece_aqui/DEPENDENCIES.md`.

## UI consolidada

O editor de partículas `.part` é first-party e está integrado na aba **Partículas** da UI principal. O launcher `app/pt_part_ui.py` permanece apenas por compatibilidade e reutiliza o mesmo serviço do core.

Texture enhancement usa como workspace canônico `app/pt_build/texture_upscale/`; o diretório raiz legado `enhancement/` não faz parte de uma release limpa.

## Preparar commit limpo

Na raiz do repositório:

```bash
python3 READY_TO_DEPLOY.py --check
python3 READY_TO_DEPLOY.py --message "chore: ready to deploy"
```

O fluxo roda a regressão, remove somente artefatos/runtime conhecidos explicando o motivo de cada limpeza, atualiza o snapshot, executa `VERIFY_PACKAGE.sh`, faz `git add -A`, `git diff --cached --check` e cria o commit.
