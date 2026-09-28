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

Texture enhancement usa como workspace canônico `app/pt_build/texture_upscale/`. Tanto essa árvore quanto um eventual diretório legado `enhancement/` são **dados locais do usuário/runtime**: ficam fora do Git/snapshot e nunca são apagados recursivamente por `READY_TO_DEPLOY`. Um archive de distribuição não deve embuti-los.

## Preparar commit limpo

Na raiz do repositório:

```bash
python3 READY_TO_DEPLOY.py --check
python3 READY_TO_DEPLOY.py --message "chore: ready to deploy"
```

O fluxo roda a regressão, remove somente caches reproduzíveis (`__pycache__`, `.pytest_cache`, `.pyc/.pyo`), **preserva `app/pt_build` e `enhancement/`**, atualiza o snapshot (que já exclui runtime), executa `VERIFY_PACKAGE.sh`, faz `git add -A`, `git diff --cached --check` e cria o commit. A higiene de release verifica que runtime não está versionado; não exige apagar dados locais.

## Integração Summit asset-retention / cooked DDS

O General Asset Census inclui uma projeção fail-closed de retenção física e importa o manifest V2 do Summit DDS cooker. A integração reutiliza ContractGraph, source evidence, client manifests e dependency graph existentes; não cria uma segunda autoridade de assets e não autoriza delete/quarantine. Consulte `docs/tematicos/ASSET_RETENTION_AND_COOKED_DDS.md`.

O V2.6 adiciona quarantine reversível em duas camadas: Q0 pode mover somente documented invalid orphans com zero linkage/root/evidence; Q1 é review-only por componente `URC-*`. Não existe delete automático. Consulte `docs/tematicos/ASSET_QUARANTINE_WORKFLOW.md`.

O V2.7 adiciona ranking read-only dos componentes Q1 (`A/B/C/BLOCKED`). O score prioriza revisão de componentes pequenos/isolados com membros inválidos documentados; nunca autoriza move/delete e `quarantine apply` continua restrito ao Q0.

O V2.8 adiciona quarantine **manual e explícita** de um único componente Q1 estritamente elegível por `quarantine apply-component`. O componente precisa ser banda A, pequeno (máx. 10 membros), sem proteção/entity/evidência positiva, sem edges externos, conter inválido documentado e ter SHA-256 físico capturado no plano. O score continua sem autoridade de move/delete; a operação exige `--component` exato + confirmação separada e permanece 100% restaurável.


## Effect runtime coverage / root-unreachable components (V2.5)

O Censo geral resolve roots de efeitos a partir de loaders legacy conhecidos e agrupa
subgrafos client não alcançados por strong roots em componentes `URC-xxxxx`. A camada é
read-only e serve para reduzir falsos órfãos antes de qualquer workflow de quarantine.

## Catálogo semântico de authoring (V2.9)

O Management Legacy agora empacota `contracts/priston_asset_name_map_v1.json` como contrato de nome visível → identidade interna para criação/edição. A identidade primária de authoring é `canonical_id`; `code` continua sendo identidade runtime onde o formato exige código sITEM. Isso evita colapsar variantes que compartilham o mesmo code.

A UI usa o catálogo em ITEM, MONSTER, NPC e MAP/Field; SPM oferece seletor de mob para actor e SPC oferece seletor de NPC fixo. Mapas resolvem nome → field/stage → SPM/SPP/SPC, incluindo a correção `Ricarten → village-2`. Nomes visíveis ambíguos permanecem marcados e nunca são resolvidos silenciosamente.
