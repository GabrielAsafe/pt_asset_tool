# Etervale V18 — Posição Stage 0.72 em binary32

Patch incremental **sobre V16** (V17 foi só diagnóstico). O erro residual `vertex position mismatch 0.00390625` no `dark_boss` decorre da comparação de uma posição float32 Blender com o intermediário float64 Python; não é prova de corrupção do ficheiro.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V18_STAGE072_POSICAO_FLOAT32_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v18_stage072.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v18_stage072.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_position_f32_v18.py
```

Caso surja `SOURCE_FILE_CONFLICT`, **não usar `--force`**; preservar as modificações locais e verificar a divergência. O instalador verifica SHA-256 de origem/destino e faz backup automático.

## Retomar sem refazer 57 mapas

Depois dos testes, quando não houver outros jobs Blender:

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

Não usar `--fresh`. A auditoria deve reutilizar os 57 resultados em cache e voltar a tentar o `dark_boss`.

A aprovação de transporte de `dark_boss` **não resolve** a textura `field/boss/a_flag01.TGA` em falta nem certifica a aparência no jogo. O relatório global poderá continuar como `FAIL_OR_REVIEW_REQUIRES_ACTION` por dependências não resolvidas.

## Validado

- 29 testes Python V12–V18 aprovados na sandbox.
- Teste de diferença `0.00390625` e rejeição de alteração real de um ULP.
- Sem execução real do Blender Etervale disponível neste ambiente.
