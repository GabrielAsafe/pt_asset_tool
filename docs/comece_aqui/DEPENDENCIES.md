# Dependências do PT Asset Tool

Use o diagnóstico central antes de testar uma funcionalidade:

```bash
cd app
python3 pt_asset.py dependencies
```

A saída não informa apenas que algo está ausente: ela explica **qual funcionalidade depende da ferramenta, por que ela é necessária e como instalar/configurar**.

## Python

A base suportada é Python 3.11+. As dependências Python first-party estão declaradas em:

```bash
python3 -m pip install -r app/requirements.txt
```

Para desenvolvimento/testes:

```bash
python3 -m pip install -r app/requirements-dev.txt
```

## Blender

Blender é necessário somente para funcionalidades que realmente executam Blender: preview 3D, validação visual, import/edit de modelos, checks de animação e preview de partículas. `bpy`, `bmesh` e `mathutils` fazem parte do runtime do Blender e **não** devem ser instalados por `pip`.

Instalação nativa (quando disponível):

```bash
sudo apt install blender
export PT_BLENDER_COMMAND='blender'
```

Ou Flatpak:

```bash
sudo apt install flatpak
flatpak install flathub org.blender.Blender
```

O default do projeto continua compatível com `flatpak run --filesystem=home org.blender.Blender`.

## Real-ESRGAN e Vulkan

O PT Asset Tool procura primeiro o executável no `PATH` e depois a cópia bundled em `tools/realesrgan/`. Portanto, **não é necessário colocar manualmente o bundled no PATH**.

O backend Real-ESRGAN usa Vulkan. Para diagnóstico em Ubuntu/Debian:

```bash
sudo apt install vulkan-tools
vulkaninfo --summary
```

Se a stack Vulkan/Real-ESRGAN não estiver disponível, o enhancement pode usar `--backend lanczos`, desde que Pillow esteja instalado.

## Git

Git não é necessário para ler/validar assets, mas é necessário para o fluxo `READY_TO_DEPLOY.py`, que verifica, limpa, atualiza o snapshot e cria o commit final.
