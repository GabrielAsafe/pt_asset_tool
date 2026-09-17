# Patch 2026-09-16 — Snapshot diagnostics and Blender availability

This follow-up hardens two diagnostics discovered while validating a fresh installation.

## Snapshot manifest diagnostics

`VERIFY_PACKAGE.sh` previously delegated to `sha256sum -c` while discarding normal output. When a digest differed, the user only saw `PACKAGE_VERIFY=FAIL snapshot_manifest` and a checksum warning, without the path that diverged.

`app/update_snapshot_manifest.py` now supports a non-mutating `--check` mode. It compares the complete static package tree against `SNAPSHOT_SHA256SUMS.txt` and reports missing, extra, and mismatched paths with expected and actual SHA-256 values. `VERIFY_PACKAGE.sh` uses this check directly.

Use:

```bash
python3 app/update_snapshot_manifest.py --check
```

Regenerate the manifest only after reviewing any reported divergence:

```bash
python3 app/update_snapshot_manifest.py
./VERIFY_PACKAGE.sh
```

Runtime state under `app/pt_build/` remains excluded from the static snapshot.

## Blender launcher availability

The smoke check previously considered Blender available whenever the first launcher executable existed. With the default Flatpak command this meant the presence of `/usr/bin/flatpak` could incorrectly produce `blender_launcher_available=true` even when `org.blender.Blender` was not installed.

The smoke check now verifies the configured Flatpak application with `flatpak info`. A missing Blender Flatpak therefore reports `blender_launcher_available=false`; Blender remains optional for the general smoke/environment gate and required only by Blender-dependent workflows.

Regression coverage is provided by `app/dev_tests/test_blender_launcher_detection.py`.
