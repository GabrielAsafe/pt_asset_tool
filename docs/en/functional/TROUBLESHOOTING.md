# Troubleshooting

## UI says server root is required

Configure the actual Summit server directory. Do not infer a path from the client directory name.

## General Census is blocked

Review server/source/reference/donor preflight. The GUI uses persisted validated roots; one bad donor/root rejects the configuration instead of partially saving it.

## A query still shows an old retention state

`asset-retention-query` reads the persisted retention report. Regenerate General Census/asset retention after changing tool semantics or the physical client tree.

## A quarantine plan is stale

Regenerate `audit quarantine-plan`. Stale plans are intentionally rejected after retention reports or physical files change.

## Blender preview is unavailable

Run dependency diagnostics and configure `PT_BLENDER_COMMAND` or install a supported Blender runtime.

## Real-ESRGAN is unavailable

Use a supported fallback where available or install/configure `realesrgan-ncnn-vulkan`.

## A semantic catalog name is ambiguous

Choose by `canonical_id`/internal identity. The tool intentionally refuses silent resolution of ambiguous display names.
