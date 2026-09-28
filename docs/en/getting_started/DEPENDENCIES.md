# Dependencies

PT Asset Tool is intentionally usable without every optional external tool. Capabilities report missing dependencies and fail closed when required.

## Python

Use the package requirements files under `app/` for the exact baseline.

## Blender

Blender is used for certified visual preview/validation and selected authoring/roundtrip workflows. Configure `PT_BLENDER_COMMAND` when automatic discovery is not sufficient.

Missing Blender must not block catalog/census/report workflows that do not require rendering.

## Real-ESRGAN

`realesrgan-ncnn-vulkan` is optional. Texture enhancement can use supported non-AI fallbacks where exposed. The application reports when the executable is unavailable.

## Diagnostics

```bash
cd app
python3 pt_asset.py dependencies
```

The dependency report explains status, purpose, and configuration/install guidance.
