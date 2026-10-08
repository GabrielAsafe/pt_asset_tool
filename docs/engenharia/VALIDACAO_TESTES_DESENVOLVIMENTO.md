# Validação, Testes e Preparação de Release

<!-- PT_DOC_VALIDATION_RUNBOOK_2026-09-25 -->

Este é o **runbook canónico** para validar alterações no PT Asset Tool. Outros documentos podem mostrar comandos específicos de uma feature, mas não devem redefinir a política geral de testes/release.

## 1. Escolher o Python de validação

A suíte deve ser executada com um Python que tenha `requirements-dev.txt` instalado. Não presuma que `/usr/bin/python3` possui `pytest`.

No diretório `app/`:

```bash
cd ~/Transferências/pt_asset_tool/app

PY="${PT_ASSET_TEST_PYTHON:-python3}"

# Exemplo de venv externo:
# export PT_ASSET_TEST_PYTHON="$HOME/Transferências/.venv-pt-asset-tests/bin/python"
# PY="$PT_ASSET_TEST_PYTHON"

"$PY" --version
"$PY" -m pytest --version
```

Se `pytest` não estiver disponível, instale as dependências de desenvolvimento **a partir do diretório em que está**:

```bash
# estando em .../pt_asset_tool/app
"$PY" -m pip install -r requirements-dev.txt

# OU, estando na raiz .../pt_asset_tool
"$PY" -m pip install -r app/requirements-dev.txt
```

Não misture os dois paths: dentro de `app/`, `-r app/requirements-dev.txt` procuraria `app/app/requirements-dev.txt`.

## 2. Evitar bytecode/caches durante pytest

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest ...
```

`PYTHONDONTWRITEBYTECODE=1` evita que imports normais criem `__pycache__/*.pyc`. Ele **não substitui** a limpeza de `.pytest_cache` e não impede `python -m compileall` de criar bytecode, porque `compileall` escreve `.pyc` deliberadamente.

## 3. Granularidade de pytest

### Um teste específico

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q \
  dev_tests/test_consolidation_v3.py::test_realesrgan_discovers_bundled_binary
```

### Um arquivo de testes

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q \
  dev_tests/test_consolidation_v3.py
```

### Um conjunto focado

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q \
  dev_tests/test_legacy_authoring_pipeline.py \
  dev_tests/test_legacy_management_web_ui.py
```

### Regressão principal

A partir de `app/`:

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q dev_tests tests
```

### Suíte descoberta pelo pytest

```bash
PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q
```

Não declare “suite verde” usando apenas um teste focado. Registre separadamente o resultado focado e o resultado da regressão/suíte completa que realmente foi executada.

## 4. Sintaxe/imports

### Python sem gerar cache

```bash
"$PY" - <<'PYAST'
from pathlib import Path
import ast
root = Path('pt_asset_tool')
count = 0
for path in root.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    count += 1
print(f'AST syntax PASS: {count} Python files')
PYAST
```

### `compileall`

```bash
"$PY" -m compileall -q pt_asset_tool
```

`compileall` **cria `__pycache__`/`.pyc`**. Use-o somente quando quer testar geração de bytecode e limpe o estado gerado antes da certificação do snapshot.

### JavaScript da Web UI

```bash
node --check pt_asset_tool/ui_static/app.js
```

## 5. Package verification

Da raiz:

```bash
cd ~/Transferências/pt_asset_tool
./VERIFY_PACKAGE.sh
```

Se código/documentação mudou intencionalmente, não regenere `SNAPSHOT_SHA256SUMS.txt` para esconder um diff: revise primeiro a alteração e siga `SNAPSHOT_MANIFEST_POLICY.md`.

## 6. Ordem recomendada

```text
mudança intencional
→ teste específico
→ testes focados
→ pytest dev_tests tests
→ checagens sintáticas
→ revisão do diff/documentação
→ arquivar runtime state necessário
→ clean/snapshot/package verification
→ READY_TO_DEPLOY
```

Exemplo:

```bash
cd ~/Transferências/pt_asset_tool/app
PY="${PT_ASSET_TEST_PYTHON:-python3}"

PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q dev_tests tests

node --check pt_asset_tool/ui_static/app.js

cd ..
./VERIFY_PACKAGE.sh
```

Só depois das gates aplicáveis estarem verdes:

```bash
python3 READY_TO_DEPLOY.py --message 'chore: ready to deploy'
```

`READY_TO_DEPLOY.py` é uma gate final de uma árvore já revisada; não substitui teste focado/regressão.

## 7. Runtime/build state

`app/pt_build/`, `.pytest_cache/`, `__pycache__/` e `.pyc` são estado gerado.

Texture Upscale usa atualmente:

```text
app/pt_build/texture_upscale/
```

como runtime canónico. O antigo root `enhancement/` é legado e não deve coexistir como segunda fonte de estado.

Se runtime state contém transações, manifests ou dados necessários para rollback/auditoria futura, **arquive/exporte-o antes de qualquer clean**. “Gerado” não significa “descartável sem revisão”.

## 8. Interpretação de resultados

- `passed`: contrato executado e satisfeito;
- `skipped`: teste não executado naquele ambiente; não converta automaticamente em PASS;
- `failed`: contrato quebrado ou expectativa desatualizada; investigue antes de release;
- teste físico que exige client/server/Blender não deve ser artificialmente promovido por mock apenas para ficar verde.

Sempre registre a contagem real da execução usada como evidência. Depois de qualquer correção, **rerode** a suíte aplicável antes de atualizar a evidência.

## 9. Referência exaustiva da source Python

A referência de módulos/classes/métodos/funções da implementação first-party mantida é derivada por AST e versionada em `docs/en/engineering/SOURCE_API_REFERENCE.md`. Depois de alteração intencional em Python first-party mantido:

```bash
cd ~/Transferências/pt_asset_tool
python3 docs/validation/generate_source_api_reference.py
python3 docs/validation/generate_source_api_reference.py --check
python3 docs/validation/validate_documentation.py
```

O `--check` deve falhar quando a referência estiver stale. Testes (`dev_tests`/`tests`) não entram nessa API runtime, mas continuam cobertos por pytest/AST/compileall.

## 10. Contrato documental

- este runbook é a referência canónica de testes/release;
- exemplos de pytest usam `"$PY" -m pytest` ou deixam explícito qual Python está sendo usado;
- `requirements-dev.txt` é relativo ao diretório atual;
- não há headings gravados com `\\n` literal por patches;
- Texture Upscale aponta para `app/pt_build/texture_upscale` como runtime atual;
- documentos históricos de release permanecem históricos.
