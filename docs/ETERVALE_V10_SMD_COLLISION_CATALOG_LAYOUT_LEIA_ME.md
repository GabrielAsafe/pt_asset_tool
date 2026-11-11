# ETERVALE V10 — Correção de colisão SMD e layout do Catalog

Atualização incremental segura sobre a V9, sem alterações nos assets reais do Etervale.

**Ficheiros:** 3 modificados, 2 novos. Patch com hashes, backups e instalação idempotente.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V10_SMD_COLLISION_CATALOG_LAYOUT_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v10.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v10.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_v10_smd_collision_catalog_layout.py
```

Se aparecer `LOCAL_FILE_CONFLICT`, **não sobrescrever**: o instalador detectou código local diferente das versões esperadas.

Depois reinicia o servidor web, força a atualização (`Ctrl+Shift+R`) e inicia **Generate SMD previews**. Em **Diagnóstico do lote e erros**, a colisão Bonbori deve aparecer como `BLOCKED`, enquanto os outros assets continuam a ser processados.

O estado no fim pode ser `COMPLETE_WITH_BLOCKED`; isso significa lote concluído com colisões ainda pendentes, não que a textura tenha sido corrigida. Se o lote falhar por outro motivo, guardar o log de job.

Em janela desktop, a tabela Catalog e a coluna Detail passam a ocupar a mesma altura. Os scrolls pertencem à tabela/galeria e à coluna Detail; sob zoom estreito, a grelha adapta-se a uma coluna.

**Documentação técnica:** `docs/etervale/V10_SMD_COLLISION_CATALOG_LAYOUT.md`.

**Limitações:** C# e runtime não executados nesta sandbox. Nenhum ficheiro do Etervale alterado. Não publicar assets ambíguos.
