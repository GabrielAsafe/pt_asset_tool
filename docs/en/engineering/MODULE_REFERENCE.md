# Module Reference

This is a compact map of first-party modules relevant to current operation.

## UI and API

- `ui_app.py` — HTTP API, safety endpoints, workflow orchestration.
- `ui_catalog.py` — catalog descriptors and physical-file presentation metadata.
- `ui_actions.py` — per-asset action/capability descriptions.
- `server_ui.py` — server/enrichment review summaries and handoffs.
- `ui_static/index.html` / `app.js` / `app.css` — first-party web UI.

## Asset analysis

- General Census and contract-graph modules — cross-root evidence and reachability.
- `asset_retention.py` — physical retention projection and root reachability.
- effect runtime coverage modules — known legacy loader roots and component grouping.

## Quarantine

- `asset_quarantine.py` — Q0/Q1 planning, review ranking, manual component quarantine, transactions, restore.

## Legacy Management

- `legacy_management_web.py` — World Closure review model and authoring handoffs.
- `legacy_apps/` — Python ports for content/persistence workflows.
- semantic authoring catalog module/contracts — stable display-name/identity mapping.

## Texture / preview

- texture upscale and DDS evidence modules — staged enhancement/cooker evidence.
- SMD/Blender preview modules — cached preview generation and certified validation paths.
- particle modules — `.part` parser/editor/preview integration.
