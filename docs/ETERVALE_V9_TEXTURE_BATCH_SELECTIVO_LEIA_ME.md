# Etervale V9 — Seleção de categoria e ficheiros no Texture Enhancement

Atualização incremental **sobre a V8 instalada**. Não modifica assets reais, readers C#, WorldImport ou a BD. Instala 4 ficheiros modificados e 3 novos com backup e hashes SHA-256.

## Instalar

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V9_TEXTURE_BATCH_SELECTIVO_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v9.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v9.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_v9_texture_selection.py
```

**Atenção:** não escreva `grep summit` sozinho antes dos comandos; `grep` sem ficheiro/pipe aguarda entrada e os comandos colados são tratados como texto.

Reinicie o servidor web e faça `Ctrl+Shift+R`.

## Teste proposto

Abra **Workspaces → Client / Enrichment → Texture Enhancement**:

1. Em **Categoria**, escolha **UI / Atlases**.
2. Clique **Selecionar primeiros 4**. A interface deve informar `4 selecionada(s)`.
3. Selecione **Lanczos** para uma prova sem Vulkan. Escala 2 e sem denoise.
4. Confirme os avisos e inicie **Gerar candidatos selecionados**.
5. No Activity, confira que o comando usa 4 `--include-exact` e nenhum `--all`.
6. Confirme quatro outputs no staging sem alterar as texturas originais.

Só então teste Real-ESRGAN num lote pequeno, se quiser verificar driver Vulkan e modelo. **Não publique UI/atlases sem inspeção visual dos recortes e do layout.**

## Estado de validação

Os testes Python, sintaxe JS e o pipeline CLI sintético foram verificados em sandbox. A interface/renderer/driver reais na máquina Etervale não estão certificados.
