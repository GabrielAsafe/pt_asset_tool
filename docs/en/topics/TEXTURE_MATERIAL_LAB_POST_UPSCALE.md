# Material Lab: AFTER existing upscale

Use `python pt_asset.py texture-material run --input-root PATH --include-exact RELATIVE_TEXTURE --denoise light --maps from-diffuse` from `app/`. This **does not resize images**. It creates a separate staging run, SHA-pinned candidate outputs, offline estimated normal/height/parallax preview PNGs and HTML review pages.

For a trained 1x DXT/BCn restoration model (for example DEDXT), install model weights separately and use the optional Spandrel inference adapter with `--denoise ai --model-config MODEL_CONFIG.json`, SHA-256 pinned. No weights are bundled; model support must be verified on the actual machine. For authored height, use `--maps from-height --height-root DIRECTORY`. For read-only mesh inspection, use `texture-material mesh-audit --mesh-root PATH`. For opt-in Blender workspace normals/shading adjustments, use the separate `texture_mesh_fix_blender.py` script.

Open `review_001.html` to export manually approved/rejected decisions, import with `texture-material review-import`, and audit with `texture-material audit`. **Even all-approved output remains blocked for client publication** until the specific renderer/shader/mesh runtime contract is established and tested in game. See the complete Portuguese guide at `docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md`.


For final cumulative patch installation and guarded offline candidate export, see `docs/tematicos/MATERIAL_LAB_GUIA_FINAL_PATCH_CUMULATIVO.md`. Offline export is NOT client deployment; current source hashes and all approvals are verified.
