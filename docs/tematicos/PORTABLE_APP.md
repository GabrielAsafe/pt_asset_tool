# PT Asset Tool — Portable App

O porte separa três áreas:

- **bundle root**: código/HTML/contracts/scripts somente leitura, dentro do executável PyInstaller;
- **state root**: `pt_build` persistente, fora do executável;
- **config/cache roots**: configuração e cache persistentes por XDG.

No executável Linux, `pt_build` é projetado para `~/.local/share/pt-asset-tool/pt_build`. Pode-se fixar tudo num diretório próprio com `PT_ASSET_HOME=/caminho` ou definir `PT_ASSET_STATE_ROOT`, `PT_ASSET_CONFIG_ROOT` e `PT_ASSET_CACHE_ROOT` separadamente.

O programa não depende do diretório atual (`cwd`). Jobs internos reinvocam o próprio executável e scripts Python auxiliares rodam pelo interpretador embutido. Python do sistema deixa de ser requisito no release congelado.

## Dependências

Em build `--onefile`, Pillow, NumPy, stdlib/SQLite e os módulos da aplicação entram no executável. Real-ESRGAN é incluído quando existe em `tools/realesrgan/`. `pyodbc`, pytest/bs4 e módulos `bpy/mathutils` não são incluídos: ODBC é legado, pytest/bs4 são desenvolvimento e `bpy/mathutils` pertencem ao Blender externo.

Blender continua externo por design. Wine e o driver Vulkan são capacidades do sistema operacional e não podem ser transformados de forma confiável em módulos Python embutidos; funções que dependem deles continuam diagnosticadas pela página de dependências.

## Build Linux x86_64

Build local:

```bash
cd app
./build_portable_linux.sh
```

Build reproduzível com baseline glibc 2.17:

```bash
./build_portable_container.sh
```

Saída:

```text
dist-portable/pt-asset-tool
```

Uso:

```bash
./pt-asset-tool                 # GUI
./pt-asset-tool gui             # GUI explícita
./pt-asset-tool doctor          # CLI
./pt-asset-tool dependencies    # diagnóstico
```

O build container usa `manylinux2014_x86_64` para evitar compilar na glibc muito nova do Fedora. Builds para ARM64, Windows e macOS devem ser gerados separadamente nas respetivas plataformas/arquiteturas.

## Limite de portabilidade

O artefacto Linux x86_64 continua a depender do kernel Linux e da ABI glibc do sistema. O build de release usa manylinux2014/glibc 2.17 para maximizar compatibilidade entre distribuições glibc. Alpine/musl, ARM64, Windows e macOS precisam de builds próprios.

O driver Vulkan permanece uma capacidade do sistema para Real-ESRGAN. Quando Vulkan/Real-ESRGAN não estiverem disponíveis, o restante programa continua funcional e o upscale pode usar o backend não-AI suportado. Blender continua opcional e externo.

<!-- PT_PORTABLE_BUILD_WHEELS_V10_1_2026-09-24 -->

### Matriz de wheels do release V10.1

O build de release usa CPython 3.11 dentro de `manylinux2014_x86_64` e fixa `Pillow==10.4.0` e `numpy==1.26.4`, versões com wheels `manylinux_2_17`/`manylinux2014` para x86_64. O instalador do build força binários (`PIP_ONLY_BINARY=:all:`) para impedir fallback para compilação source e dependências acidentais de headers/bibliotecas do container.

`build_portable_linux.sh` é apenas um build de desenvolvimento e aceita Python 3.11/3.12. O artefacto distribuível deve ser produzido por `./build_portable_container.sh`.

<!-- PT_PORTABLE_SHARED_PYTHON_V10_2_2026-09-24 -->
### Runtime Python do build onefile

O release Linux x86_64 continua a ser construído numa baseline manylinux2014/glibc 2.17. Os intérpretes `/opt/python/*` da imagem manylinux são destinados à construção de wheels e não fornecem o `libpython` partilhado exigido pelo PyInstaller. O build de release usa por isso CPython 3.11.16 `python-build-standalone` (`x86_64-unknown-linux-gnu`, release 20260825), fixado por SHA-256, mantendo a baseline glibc 2.17.

Antes de instalar dependências ou executar PyInstaller, o Containerfile valida `libpython3.11.so.1.0`, `Py_ENABLE_SHARED=1` e rejeita uma shared library marcada com executable stack. Pillow, NumPy e PyInstaller continuam restritos a wheels binárias fixadas; compilação source permanece proibida. Blender continua externo ao executável.

<!-- PT_PORTABLE_ENTRYPOINT_V10_3_2026-09-24 -->

### V10.3 — entrypoint one-file e payload Real-ESRGAN

O entrypoint portátil agora adapta os argumentos para o overlay consolidado `pt_asset.py`, que historicamente lê `sys.argv`. O wrapper restaura `sys.argv` após a chamada, mantendo source mode e subprocessos internos compatíveis.

O executável `realesrgan-ncnn-vulkan` é empacotado como payload executável opaco, e não como biblioteca ligada ao ELF do PT Asset Tool. Assim o PyInstaller não tenta coletar as dependências de runtime Vulkan/glibc do NCNN durante o build. O build informa explicitamente o maior símbolo GLIBC exigido pelo payload Real-ESRGAN encontrado. A baseline do executável principal continua glibc 2.17; o backend NCNN continua sujeito ao driver Vulkan e à ABI exigida pelo binário Real-ESRGAN empacotado.

<!-- PT_PORTABLE_RUNTIME_V10_4_2026-09-24 -->

## Portable V10.4 — runtime fora do bundle

O executável one-file mantém o código e o Python dentro do bundle, mas trata programas do sistema como processos externos. Em Linux congelado, o PT Asset Tool restaura o `LD_LIBRARY_PATH` original antes de iniciar Blender, Wine, Real-ESRGAN ou `xdg-open`; isto impede que bibliotecas extraídas em `_MEI...` sejam injetadas nesses executáveis.

A descoberta de client/server em modo frozen não usa a pasta temporária `_MEI` nem percorre `/tmp`. A prioridade é configuração explícita (`PT_CLIENT_ROOT`/`PT_SERVER_ROOT` ou config persistente) e, depois, pastas adjacentes ao executável. Um estado portátil novo sem registry é reportado pelo Doctor como `SETUP_REQUIRED`, com a ação de configurar o client ou executar `registry rebuild`, em vez de lançar exceção.

O Real-ESRGAN é armazenado no one-file como `payloads/realesrgan_payload.tar.gz` e materializado no cache persistente apenas quando necessário. O executável principal continua com baseline glibc 2.17; o payload Real-ESRGAN atual requer glibc 2.29 e, em hosts mais antigos, somente esse backend AI fica indisponível enquanto Lanczos continua funcional.
