# Snapshot Manifest Policy

Stable project artifacts are certified; Python bytecode is not.

Excluded from `SNAPSHOT_SHA256SUMS.txt`:
- every path containing `__pycache__/`;
- every `*.pyc`;
- `app/pt_build/`;
- `app/certifications/assets.jsonl` (mutable journal).

`.pyc` files may change when unchanged Python sources are imported or tested, so their bytes are not a release-integrity signal. Source `.py` files remain hash-certified. `VERIFY_PACKAGE.sh` rejects future snapshot manifests that contain `__pycache__` or `.pyc`.
