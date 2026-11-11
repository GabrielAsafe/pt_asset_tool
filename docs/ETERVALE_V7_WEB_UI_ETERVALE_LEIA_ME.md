# Etervale V7 — UI nativa, AI_enhcance e Particles

**Pré-requisito:** PT Asset Tool com V6 já aplicada. O patch altera somente `pt_asset_tool`, nunca a source `Etervale-git`.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V7_WEB_UI_ETERVALE_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v7.py --project-root "$PWD" --dry-run
# Só após confirmar que não há LOCAL_FILE_CONFLICT:
python3 patches/aplicar_etervale_v7.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_v7_native_ui_ai_particles.py
python3 app/pt_texture_upscale.py capabilities
```

Reinicie o processo web do Asset Tool e recarregue o browser com Ctrl+Shift+R. Se aparecer `LOCAL_FILE_CONFLICT`, não utilize `unzip` sobre os arquivos internos, não use `--force`, e envie o resultado do `--dry-run` para revermos a versão local.

## Conferências

- Server/Client não devem solicitar source Summit/Reference EU na navegação normal. Configuração de donors permanece em **Management Legacy > Fontes externas e donors**.
- `Server > Advanced Evidence` documenta que a tabela de 61 contratos não comprova que Etervale implemente todos os formatos.
- `Client > Texture Enhancement` mostra backend, modelos NCNN detectados e opção de UI/atlases (off por defeito). Detectar um binário não implica Vulkan válido.
- `Particles` usa 100 arquivos por página e layout que adapta à largura; preview Blender pode ter apenas imagens amostradas, não simulação física real.

## Provas

125 testes Python aprovados na cópia reconstruída, incluindo 5 testes novos V7; Chromium com APIs simuladas sem erro JavaScript a 390px. **Ainda é necessária validação funcional na source da sua máquina.**

Documentação integral: `docs/etervale/V7_WEB_ETERVALE_NATIVE_AI_PARTICLES.md`.
