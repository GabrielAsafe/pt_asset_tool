#!/usr/bin/env bash
set -euo pipefail
# Escolhe Python 3.11 do projeto, do sistema, ou chaiNNer enquanto este estiver instalado.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CANDIDATES=("$ROOT/.runtime/venv-gpu/bin/python" )
if command -v python3.11 >/dev/null 2>&1; then
  CANDIDATES+=("$(command -v python3.11)")
fi
CANDIDATES+=("$HOME/.config/chaiNNer/python/python/bin/python3.11")
for candidate in "${CANDIDATES[@]}"; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys,numpy,PIL; assert sys.version_info[:2]==(3,11)' >/dev/null 2>&1; then
    exec "$candidate" "$@"
  fi
done
echo 'ERRO: Python 3.11 com numpy e Pillow não encontrado. Consulte ENTREGA_REFOCUS.md' >&2
exit 127
