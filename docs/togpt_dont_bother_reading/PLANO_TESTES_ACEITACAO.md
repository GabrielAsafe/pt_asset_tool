# PT Asset Tool R14 1.0.0 — Plano de Testes de Aceitação

## Objetivo

Validar uma instalação/distribuição 1.0 sem confundir capability do tool com qualidade do conteúdo target.

## A. Pacote

1. `./VERIFY_PACKAGE.sh` → PASS.
2. `cd app && python3 pt_asset.py --version` → `1.0.0`.
3. `python3 pt_rc6_12_verify.py --current-root ..` → PASS.
4. Confirmar ausência de `app/pt_build` pré-populado no pacote limpo (salvo se criado após a instalação).

## B. Configuração e ambiente

1. `config show`.
2. configurar client root.
3. `validate environment-auto` → PASS no ambiente suportado.
4. se server estiver em uso, configurar server root e `validate server-environment-auto`.

## C. Smoke da aplicação

`python3 pt_asset.py smoke` deve validar os contratos internos e escrever apenas probe temporário em `pt_build`.

## D. GUI

1. abrir `pt_asset_gui.py`;
2. Catálogo carrega e pesquisa;
3. Entidades carrega Monster/NPC;
4. preview de imagem quando há sample;
5. Comparar executa tree compare;
6. Tarefas mostra jobs/reviews;
7. Relatórios encontra JSONs em `pt_build`;
8. Settings mostra roots;
9. safety arm só habilita workspace/build, não target write.

## E. Formatos

Selecionar samples físicos reais apropriados e executar:

- Model0.62 structural + static/rigid/material/object-local/TexLink conforme aplicável;
- Stage0.72 preview/UV/geometry;
- INX no-op roundtrip;
- SMB no-op roundtrip;
- proprietary texture codec/corpus;
- animation source/Blender validation quando aplicável.

## F. Server/enrichment

- server inventory;
- Monster/NPC bundles;
- Fields;
- Items;
- enrichment plan/graph;
- server-design-auto.

Nenhuma etapa deve modificar server/client.

## G. Recovery/build/deploy

- aggregation escreve somente overlay em `pt_build`;
- recovery exige CLOSED bundles/expected roots;
- `build --plan` bloqueia rotas sem writer;
- `build --candidate` fica em pt_build;
- deploy prepare/verify/simulate/state/restore-plan não faz apply no client.

## H. Release gate

Em workstation com client/server/Blender equivalentes à certificação:

```bash
python3 pt_asset.py --client-root CLIENT --server-root SERVER validate release-1-auto --resume
```

Aceitação da capability: `automatic_gate_status=PASS` e `blockers=[]`. `status=BLOCKED_EXTERNAL` é aceitável quando a única pendência é `WRITER_PROMOTION_AND_PUBLISH_RESTORE`.

## I. Critérios de reprovação

Reprovar distribuição se:

- package/snapshot verifier falhar;
- writer hash certificado divergir;
- client/server for modificado durante audit/certification;
- uma ação tenta promover basename/donor guess a recovery;
- `automatic_gate_status` for FAIL;
- blockers automáticos não estiverem vazios;
- documentação indicar write authorization que o pacote não possui.
