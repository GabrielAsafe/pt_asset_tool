# Etervale V14 — UV binary32 e diagnóstico de `pilai` / `dark_boss`

**Atualização incremental sobre V13.** Apenas código do Asset Tool e documentação, sem escrever nos ficheiros do cliente ou nas bases de dados.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V14_STAGE072_UV_TRIAGEM_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v14_stage072_uv.py --project-root "$PWD" --dry-run
# Se não houver SOURCE_FILE_CONFLICT:
python3 patches/aplicar_etervale_v14_stage072_uv.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_uv_f32_v14.py
```

## Diagnóstico dos dois problemas que ainda não podem ser classificados como defeito da ferramenta

```bash
python3 app/pt_stage072_v14_residual_triage.py --project-root "$PWD" \
  --output /tmp/etervale_v14_residual.json
```

Recolhe, sem alterar o cliente:

- `pilai`: quais **ficheiros presentes** tiveram erro de preparação, com `status`, `physical` e log de descodificação;
- `dark_boss`: contadores, modos e nomes de textura do material associado a `hTexture=0`, e erros do parser.

## Retomar Blender apenas nos pendentes

Quando nenhum outro trabalho Blender estiver a decorrer:

```bash
python3 app/pt_stage072_batch_audit.py --blender --timeout 360
```

O checkpoint V13 reutiliza as **52 importações PASS** e volta a testar apenas os workers que falharam. As quatro falhas UV deverão desaparecer caso fossem exclusivamente quantização binary32; outras diferenças reais continuam a reprovar. `pilai` pode continuar a falhar enquanto o erro de descodificação não estiver esclarecido. `dark_boss` mantém-se bloqueado pelo parser estrito.

Não use `--fresh`, não apague checkpoints nem substitua texturas para tentar obter um PASS.

Documento detalhado: `docs/etervale/V14_STAGE072_UV_F32_TRIAGE.md`.
