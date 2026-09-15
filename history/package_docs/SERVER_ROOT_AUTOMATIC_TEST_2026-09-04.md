# Server-root automatic validation

Run only after the currently running client `physical-regression-auto` has finished, to avoid competing for the same disk/CPU.

```bash
cd app
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  validate server-design-auto
```

Primary report:

`app/pt_build/devtest/server_design_auto/result.json`

Subreports:

- `server_environment_auto/result.json`
- `server_bundle_census/result.json`
- `server_field_census/result.json`
- `server_item_census/result.json`

This gate does not traverse all 124k+ LogItemData entries. It samples the tree for lifecycle enforcement and scans only the content roots needed for Monster/NPC/Field/OpenItem design catalogs.

Optional later deep census:

```bash
python3 pt_asset.py \
  --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" \
  --server-root "/home/gabriel/Área de Trabalho/summit/Servidor" \
  audit server-inventory
```

The deep census walks the whole server tree, including file metadata for logs/state, but never parses them as assets and never writes the server.
