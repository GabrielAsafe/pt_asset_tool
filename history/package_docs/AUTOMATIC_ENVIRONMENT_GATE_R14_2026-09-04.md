# PT Asset Tool R14 — Automatic Environment Gate

This cumulative patch is intended to be extracted at the root of
`PT_Asset_Tool_R14_WORKING_HANDOFF_2026-09-03`, not inside `app/`.

## Fast environment validation

From `app/` run:

```bash
python3 pt_asset.py --client-root "/path/to/client" validate environment-auto
```

The command writes only under `app/pt_build` and never attempts a client write.
It validates, fail-closed:

1. project/client/inventory/pairing existence and registry bootstrap;
2. Python runtime and UTF-8/path round-trip;
3. `pt_build` isolation from the client, write/read/delete probe and free space;
4. SHA-256 of the four certified rare writers;
5. real physical inventory samples for Model0.62, Stage0.72, INX, SMB, BMP and TGA, including size match;
6. real Blender headless launch through the configured command/Flatpak;
7. Blender visibility/readability of both a unicode/space `pt_build` probe and a real client SMD;
8. SHA-256 agreement between host Python and Blender for those files;
9. sampled client files unchanged after the preflight.

Report:

`app/pt_build/devtest/environment_auto/result.json`

## Full Release 1.0 automatic gate

`validate release-1-auto` now runs the same environment preflight before any
heavy corpus work. If the environment fails, the expensive gate does not start.
After a PASS environment gate, run:

```bash
python3 pt_asset.py --client-root "/path/to/client" validate release-1-auto --resume
```

The release result embeds an environment summary and remains candidate-only.
