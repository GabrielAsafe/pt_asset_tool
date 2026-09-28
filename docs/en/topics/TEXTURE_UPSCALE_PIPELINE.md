# Texture Upscale Pipeline

Texture enhancement works on staged candidates and preserves source safety.

## Workspace

Canonical runtime workspace:

```text
app/pt_build/texture_upscale/
```

## Safety

- Enhancement generation does not overwrite the source client.
- Alpha and protected legacy headers are preserved where required.
- Publication validates that the candidate matches the current source/hash contract.
- Publication creates backup and verifies post-write state.
- Restore refuses unknown drift.

## Global vs individual

Use **Client / Enrichment** for the global batch. Use **Catalog** for enhancement of a specific asset.
