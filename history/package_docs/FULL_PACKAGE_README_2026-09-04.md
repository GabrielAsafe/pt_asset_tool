# PT Asset Tool R14 — Design Tool + Asset Enrichment RC4

Este diretório é uma distribuição **autocontida** do Design Tool com o **Summit Asset Enrichment v6** integrado. Não é overlay.

## Comece aqui

1. `./VERIFY_PACKAGE.sh` — verifica a integridade do ZIP sem tocar no client/server.
2. Leia `docs/README.md` para escolher o guia certo.
3. Configure `client_root` e `server_root` na UI ou CLI.
4. Rode `validate integration-regression-auto` para o gate físico focado.
5. Quando ficar PASS, rode `validate release-1-auto --resume` para a matriz completa.

No ambiente Summit:

```bash
cd app
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate integration-regression-auto
```

## O que está integrado

- edição/validação client-side SMD/SMB/INX/Stage/texturas;
- raiz server separada e read-only;
- inventário/lifecycle server-side;
- bundles Monster/NPC, Field e OpenItem;
- Explorador de bundles na UI;
- planner e grafo do Asset Enrichment v6 em modo read-only;
- gates environment, server-design, integration-regression e release-1;
- Ajuda/Guias dentro da UI e documentação Markdown completa.

## Segurança

Os gates desta RC não autorizam escrita no client ou server. Candidates e relatórios ficam em `app/pt_build`. Persistência, logs e estado de segurança do servidor permanecem fora da superfície de autoria.

## Documentação

- `docs/GUIA_DESIGN_TOOL.md`
- `docs/GUIA_ASSET_ENRICHMENT.md`
- `docs/GUIA_WORKFLOW_CLIENT_SERVER.md`
- `docs/RELEASE_1_READINESS.md`
- `CHANGELOG.md`

A distribuição continua sendo **RC**, não Release 1.0, até fechar os gates físicos/runtime descritos em `docs/RELEASE_1_READINESS.md`.

## Estado local desta RC

- dev tests sem `fixture_client`: **232/232 PASS**;
- `VERIFY_PACKAGE.sh`: PASS;
- hashes dos quatro writers raros: preservados;
- último rerun físico confirmou parser server PASS e safety read-only; o gate integrado continuou vermelho, mas o terminal antigo perdeu o bloco inicial de failures; esta RC adiciona `failure_summary.json` e resumo final compacto;
- nenhuma escrita em client/server/produção autorizada.

## Diagnóstico compacto

`validate integration-regression-auto` não imprime mais os rows completos dos censos server-side. Em vez disso, termina com `required_failures`, `gate_statuses`, `failure_summary` e os caminhos dos relatórios. O JSON completo permanece salvo em `app/pt_build`.

O self-test affine desta RC também usa o conversor oficial Local→Pose do Blender para construir o target sintético antes de inserir o helper; uma falha deixa matrizes diagnósticas no build report.


## RC4 — affine Blender-aware

O affine split não assume mais que a multiplicação algébrica dos dois `matrix_basis` reproduz automaticamente a hierarquia de PoseBones. O primeiro factor continua vindo do SVD; o segundo é resolvido com `Bone.convert_local_to_pose(..., invert=True)` contra o target global. Rank-deficient + non-TRS permanece bloqueado na camada Blender até existir representação física certificada.
