# Etervale V6 — UI web, agrupamento e correções funcionais

Patch incremental sobre o **PT Asset Tool V5** testado. Não altera assets do jogo nem a BD.

## Conteúdo

- `patches/etervale_V6_WEB_UI_AUDITORIA_patch.zip`: 7 arquivos, cinco alterados e dois novos.
- `patches/aplicar_etervale_v6.py`: instalador com dry-run, SHA-256, backups, reaplicação e conflito local.
- `docs/etervale/V6_AUDITORIA_WEB_UI_E_API.md`: relatório técnico detalhado.
- `V6_WEB_UI_API_CALL_GRAPH.csv` e `V6_WEB_UI_STATIC_API_AUDIT.json`: inventário de chamadas/seletores.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V6_WEB_UI_AUDITORIA_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v6.py --project-root "$PWD" --dry-run
```

Se não aparecer `LOCAL_FILE_CONFLICT`, aplique:

```bash
python3 patches/aplicar_etervale_v6.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_v6_web_focus.py
python3 -m pytest -q app/dev_tests/test_etervale_p0_*.py app/dev_tests/test_etervale_p1_*.py app/dev_tests/test_etervale_native_pipeline.py app/dev_tests/test_etervale_unified_bridge.py app/dev_tests/test_etervale_texture_audit_bridge.py app/dev_tests/test_data_type_migration_etervale.py app/dev_tests/test_etervale_v5_migration_evidence.py app/dev_tests/test_etervale_v6_web_focus.py
```

**Reinicie o processo web** para carregar Python, HTML e JS. Abra `http://127.0.0.1:<porta>/` e use Ctrl+Shift+R na primeira visita para renovar o JS/CSS. O instalador altera apenas `pt_asset_tool`, nunca o checkout Etervale.

## Checklist manual após reiniciar

1. Workspaces: alternar entre Client / Enrichment, Server / Enrichment, Management Legacy e Comparar.
2. Support: Etervale Validation, Help/Guides e Settings na mesma área.
3. Catalog: testar zoom 100%/150%/200%, marcar estrela na tabela e galeria, filtrar Favorites; abrir Advanced.
4. SMD: verificar total/prontos/restantes, não apenas 0/0 do job.
5. Entities: `MAP_FIELD`, extensão `.spm`, origem `server/linked`; verificar Field normalizado e retorno ao Catalog.
6. Cache: alternar entre tabs sem reiniciar downloads de imagens; após alterar o ficheiro, verificar revalidação ETag.
7. Particles: selecionar `.part`, gerar Blender preview e testar Play/Pause se houver 2+ imagens. Isto ainda NÃO é simulação do motor.

## Limites e cautelas

- O catálogo de nomes descritivos depende de uma associação comprovada na BD existente, **não** de Content JSON.
- 21 seletores JS antigos não têm controles no HTML, porque exploradores/publishers históricos foram removidos da UI ativa. Esses fluxos requerem triagem antes de habilitação.
- O grafo API é auditoria estática, não cobertura runtime de todas as chamadas/rotas.
- `tem_wall04.bmp` continua ausente e deve permanecer como exceção conhecida, sem reconstrução inventada.
- No teste de SMD, a condição visual de animação depende do jogo/Blender, não do browser smoke.
