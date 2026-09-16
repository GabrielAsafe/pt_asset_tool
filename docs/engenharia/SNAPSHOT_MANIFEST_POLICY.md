# Snapshot Manifest Policy

Stable project artifacts are certified; Python bytecode is not.

Excluded from `SNAPSHOT_SHA256SUMS.txt`:
- every path containing `__pycache__/`;
- every `*.pyc`;
- `app/pt_build/`;
- `app/certifications/assets.jsonl` (mutable journal).

`.pyc` files may change when unchanged Python sources are imported or tested, so their bytes are not a release-integrity signal. Source `.py` files remain hash-certified. `VERIFY_PACKAGE.sh` rejects future snapshot manifests that contain `__pycache__` or `.pyc`.

## Regeneração após mudança autorizada

Depois de concluir uma alteração intencional de código/documentação/estrutura, regenere a baseline atual com:

```bash
python3 app/update_snapshot_manifest.py --current-root .
```

O gerador exclui `.git/`, caches de ferramentas (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`), `*.pyc`, qualquer `pt_build/`, o próprio `SNAPSHOT_SHA256SUMS.txt` e os paths declarados em `SNAPSHOT_MUTABLE_PATHS.txt`. Não regenere o manifest para esconder diferenças inesperadas; primeiro revise o diff.
