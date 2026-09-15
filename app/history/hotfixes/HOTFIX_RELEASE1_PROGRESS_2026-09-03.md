# PT Asset Tool R14 — Release 1 progress/resume hotfix — 2026-09-03

## Motivo

O `validate release-1-auto` podia parecer congelado imediatamente depois dos witnesses `MULTILAYER_TEXLINK_ROUNDTRIP`.
A fase seguinte executava censos físicos de texturas/outliers sem progresso no terminal. Em particular, o censo TGA fazia uma travessia recursiva (`rglob`) de todo o client antes/de durante a classificação.

## Alterações

- o censo TGA passa a usar a lista canónica de ficheiros físicos já existente no registry, em vez de caminhar recursivamente pelo client inteiro;
- progresso explícito e `flush=True` para todos os gates principais do `release-1-auto`;
- progresso periódico no corpus proprietário BMP/TGA;
- progresso periódico no censo TGA;
- progresso periódico no corpus semântico INX/SMB;
- novo `validate release-1-auto --resume`.

`--resume` só reutiliza um batch Blender anterior quando:

- o report está em `app/pt_build` da mesma árvore de trabalho;
- o batch tem `status=PASS`;
- o número pedido coincide;
- o conjunto de assets PASS coincide exatamente (case-insensitive) com o plano atual;
- não existem failed assets;
- `client_modified`, `client_write_authorized` e `production_authorized` continuam false.

Os censos físicos/read-only do client são sempre repetidos. Não existe reuse de um censo antigo para pintar a matriz de verde.

## Aplicação sobre a execução atual

É seguro interromper a execução antiga com Ctrl+C: este runner mantém o client read-only e escreve candidates/reports apenas em `pt_build`.
Não apague `pt_build`, porque ele contém os batch reports usados pelo `--resume`.

Depois de extrair o hotfix por cima da pasta `app`, executar:

```bash
python3 pt_asset.py --client-root "/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente" validate release-1-auto --resume
```

A execução nova deve mostrar linhas `[release-1-auto] START/DONE`, `TEXTURE_CORPUS`, `TGA_CENSUS` e `MOTION_SEMANTIC`, eliminando fases longas sem indicação de progresso.

## Segurança

Este hotfix não altera os quatro writers raros certificados, não habilita `deploy apply`, não escreve no client e não promove candidate para production.
