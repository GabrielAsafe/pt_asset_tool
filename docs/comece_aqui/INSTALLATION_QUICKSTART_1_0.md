# PT Asset Tool R14 1.0.0 — Instalação e Quick Start

## Estrutura do ZIP

Depois de extrair:

```text
PT_Asset_Tool_R14_1.0.0_COMPLETE_2026-09-14/
├── README.md
├── docs/README.md
├── CURRENT_READINESS.json
├── VERIFY_PACKAGE.sh
├── SNAPSHOT_SHA256SUMS.txt
├── SNAPSHOT_MUTABLE_PATHS.txt
├── docs/
├── vendor/
└── app/
    ├── VERSION.txt
    ├── pt_asset.py
    ├── pt_asset_gui.py
    ├── pt-asset-gui
    ├── pt_asset_tool/
    ├── data/
    └── dev_tests/
```

`pt_build/` não é distribuído no pacote limpo; será criado quando necessário.

## 1. Verificar integridade

Na raiz extraída:

```bash
chmod +x VERIFY_PACKAGE.sh
./VERIFY_PACKAGE.sh
```

Resultado esperado:

```text
PACKAGE_VERIFY=PASS version=1.0.0 vendor=v9-fix136 ...
```

## 2. Confirmar versão

```bash
cd app
python3 pt_asset.py --version
```

Esperado: `1.0.0`.

## 3. Requisitos

- Linux;
- Python 3;
- browser moderno para GUI;
- leitura ao client/server que será analisado;
- escrita na pasta da ferramenta para `pt_build`;
- Blender é opcional para catálogo, inspeção, UI e validações que não dependem dele. Workflows Blender e `release-1-auto` exigem Blender disponível; `validate environment-auto` reporta essa capability separadamente.

O bridge aceita `PT_BLENDER_COMMAND` quando Blender não usa o comando padrão da workstation. Se Blender não estiver instalado, o preflight geral pode passar com a capability Blender em `SKIP`, mas gates que dependem dela continuam bloqueados.

### Dependências opcionais de Texture Upscale

O resto da aplicação não depende destas ferramentas. Para **Upscale textura**:

- instale `Pillow` no ambiente Python para habilitar Lanczos;
- opcionalmente instale `realesrgan-ncnn-vulkan` para o backend AI/Vulkan.

`python3 pt_asset.py status` mostra `optional_capabilities.texture_upscale` sem transformar a ausência dessas dependências num failure do ambiente geral.

## 4. Configurar roots

```bash
python3 pt_asset.py config set-client-root "/caminho/cliente"
python3 pt_asset.py config set-server-root "/caminho/Servidor"
python3 pt_asset.py config show
```

Também é possível passar `--client-root`/`--server-root` por execução.

## 5. Primeiro gate

```bash
python3 pt_asset.py --client-root "/caminho/cliente" validate environment-auto
python3 pt_asset.py --client-root "/caminho/cliente" --server-root "/caminho/Servidor" validate server-environment-auto
```

## 6. Abrir GUI

```bash
python3 pt_asset_gui.py
# ou
./pt-asset-gui
```

## 7. Smoke completo da aplicação

Com o client configurado:

```bash
python3 pt_asset.py smoke
```

O smoke lê o client e usa apenas `pt_build` para probes temporários.

## 8. Não faça isto

- não execute scripts copiando assets para o target como forma de “corrigir” um audit;
- não trate donor basename/casefold como autoridade de recovery;
- não habilite client/server write simplesmente editando flags de readiness;
- não confunda `BLOCKED_EXTERNAL` com falha automática do tool;
- não use documentos históricos de `docs/validation/` como estado atual.
