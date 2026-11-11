# Entrega P0 + P1 — integração Etervale (09/11/2026)

**Destinada ao Asset Tool já atualizado com os três patches anteriores** (data-types, unified integration, texture diagnostics). Os seis novos patches têm dependência da base P0/01, e não modificam nenhum arquivo C# do Etervale.

| ID | Prioridade | Escopo real entregue | O que permanece pendente |
|---|---|---|---|
| P0_01 | P0 | Geração SMD model/stage com writers reais e probes INX/SMB, relatório e ponte C# | Provas runtime no jogo e variantes raras |
| P0_02 | P0 | Matriz de contratos Summit → Etervale; JSON → drafts GameServer em CP949 | Mapeamento completo dos packs Summit e import real em banco descartável |
| P1_03 | P1 | Auditoria dos materiais *usados* e texturas primárias ausentes, JSON/CSV | Segunda UV, alpha, efeitos, relações globais |
| P1_04 | P1 | Matriz de evidência geometria, materiais, animação, colisão e efeitos | Prova visual, física e VFX no runtime |
| P1_05 | P1 | Leitura/checagem SPM/SPP/SPC alinhada ao layout dos parsers C# | Import do WorldImport num banco isolado e semântica completa |
| P1_06 | P1 | Painel web read-only de evidências + link na UI | Redesenho completo dos editores e publicação |

**Sem falsas certificações:** teste de parser não significa funcionamento no jogo. Os patches implementam instrumentação, geração segura e diagnósticos; fechar os P0/P1 totalmente exige os testes executados no repositório Etervale real e decisões de mapeamento de dados. Este pacote não declara tudo concluído.

## Instalação no computador

Salve o ZIP desta entrega em `~/Downloads/` (ou outra pasta). Extraia sobre o Asset Tool preservando os arquivos já existentes:

```bash
cd ~/Transferências/pt_asset_tool
unzip -n ~/Downloads/ETERVALE_P0P1_PATCHES_2026-11-09.zip -d .
python3 patches/aplicar_p0p1_patch.py --all --dry-run
python3 patches/aplicar_p0p1_patch.py --all
```

O instalador faz preflight por hash, recusa conflitos, efetua backups em `patches/_backups/` e permite reaplicação idempotente. Para aplicar individualmente: `python3 patches/aplicar_p0p1_patch.py --id P0_01` (e assim sucessivamente).

## Testes de regressão

```bash
python3 -m pytest -q app/dev_tests/test_etervale_p0_writer_cert.py app/dev_tests/test_etervale_p0_content_compat.py app/dev_tests/test_etervale_p1_asset_gaps.py app/dev_tests/test_etervale_p1_quality_gates.py app/dev_tests/test_etervale_p1_field_contracts.py app/dev_tests/test_etervale_p1_ui_readiness.py app/dev_tests/test_etervale_unified_bridge.py app/dev_tests/test_etervale_texture_audit_bridge.py app/dev_tests/test_data_type_migration_etervale.py
```

## Primeiras execuções reais (do diretório Asset Tool)

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale writer-certify --mode stage --execute --build
python3 app/pt_asset.py etervale writer-certify --mode model --execute
python3 app/pt_asset.py etervale content-compat
python3 app/pt_asset.py etervale asset-gaps --asset 'Field/Ricarten/village-2.smd' --execute --strict
python3 app/pt_asset.py etervale quality-check --asset 'Field/Ricarten/village-2.smd' --execute
python3 app/pt_asset.py etervale ui-board
bash app/pt-asset-gui
```

Abrir na porta exibida: `/etervale-readiness`. Para INX/SMB e Fields, consultar a documentação específica, escolher arquivos existentes e executar os probes.

## Pendência de assets previamente confirmada

`Field/Ricarten/tem_wall04.bmp` — referenciado no material **173**, usado por **1 face** do `village-2.smd`. O exportador GLB usa fallback branco; `--strict-textures` retorna `FAILED_TEXTURE_FALLBACKS`. Não foi encontrado nas fontes pesquisadas. Ver `ASSETS_EM_FALTA_CONFIRMADOS.json`.

## Segurança e limitações

- Nenhum patch escreve em `Etervale-git/assets`, `Server`, `Client` ou `Shared`.
- `WorldImport import` modifica banco de dados e **não é chamado**.
- Saídas ficam no `app/pt_build/etervale` isolado; publicação não é autorizada.
- Código de loaders C# continua intocado; os binários Summit não são importáveis diretamente.
- Um `status: PASS` de contrato significa prova limitada àquele teste, não certificação em jogo.
