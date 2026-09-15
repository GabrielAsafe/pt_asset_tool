# Guia integrado — Client + Server

> **Documentação 1.0:** Guia integrado 1.0. Para índice completo veja `README.md`; para comandos exaustivos veja `CLI_REFERENCE_1_0.md`.

Este guia mostra como as duas ferramentas trabalham juntas.

## 1. Regra de ouro

O **Design Tool** prova e constrói assets/client/shared-3D. O **Asset Enrichment** prova a cadeia server-side e as dependências do bundle. Nenhum deles, sozinho, prova que um conteúdo completo está pronto para produção.

## 2. Setup recomendado

```bash
cd app
python3 pt_asset.py config set-client-root "/caminho/cliente"
python3 pt_asset.py config set-server-root "/caminho/Servidor"
```

Depois:

```bash
python3 pt_asset.py --client-root "/caminho/cliente" validate environment-auto
python3 pt_asset.py --client-root "/caminho/cliente" --server-root "/caminho/Servidor" validate server-environment-auto
```

## 3. Fluxo Monster/NPC

### Passo A — encontrar a definição server-side

Use Servidor / Enrichment → Explorador → Monster/NPC.

Verifique:

- definição INF/NPC;
- ZHOON;
- model lógico;
- INX resolvido no server/client;
- motivos de REVIEW/BLOCKED.

### Passo B — validar o pacote visual

No Catálogo/Entidades do Design Tool, valide:

- SMD;
- INX;
- SMB/skeleton;
- texturas;
- pose-space quando animado;
- roundtrip/writer quando houver edição.

### Passo C — fechar gameplay

Confirme spawn/evento/SPM/SPC/quest/shop conforme o tipo de entidade.

### Passo D — runtime

Carregue a entidade no jogo e verifique visual, animação, colisão/comportamento e referências server-side.

## 4. Fluxo Field

1. No Enrichment, encontre o basename do Field.
2. Verifique SPP/SPC/SPM e o stage escolhido.
3. Se houver `AMBIGUOUS_STAGE_BASENAME`, resolva explicitamente; não escolha pela primeira ocorrência.
4. No Design Tool, valide o Stage SMD físico e texturas.
5. No server, confirme os NPC/Monster referenciados.
6. Faça runtime review do mapa.

## 5. Fluxo Item

1. Enrichment: OpenItem + code + ZHOON.
2. Verifique colisões `DUPLICATE_CODE`.
3. Resolva code map/catalog do server/client.
4. Design Tool: modelo/drop/icon/texturas.
5. Verifique drops/shops/eventos que usam o code.
6. Faça runtime review.

## 6. Qual gate rodar em cada momento

| Momento | Gate |
|---|---|
| Instalação / máquina nova | `environment-auto` |
| Server root novo | `server-environment-auto` |
| Mudança nos parsers server | `server-design-auto` |
| Mudança recente client+server | `integration-regression-auto` |
| Mudança física mais ampla | `physical-regression-auto` |
| Candidate de Release 1.0 | `release-1-auto --resume` |
| Antes de publish | runtime/game + publish/restore |

## 7. O que significa “pronto para 1.0”

A 1.0 exige mais do que unit tests verdes:

- regressões integradas PASS;
- release gate automático completo;
- Mixed-Physique físico quando houver representante autoritativo;
- runtime/game acceptance de um conjunto representativo;
- promotion/publish/restore com rollback comprovado;
- documentação e UI refletindo a política real;
- client/server sources permanecendo protegidos por padrão.

## 8. Checklist rápido para um conteúdo novo

- [ ] Definição server-side existe e parseia.
- [ ] ZHOON/links obrigatórios resolvem.
- [ ] INX correto resolve.
- [ ] SMD/SMB/texturas passam no Design Tool.
- [ ] Spawn/placement/uso gameplay existe.
- [ ] Não há colisão de identidade/code.
- [ ] Gates automáticos relevantes passam.
- [ ] Runtime review passa.
- [ ] Manifest/proveniência/rollback estão registrados antes de publish.
