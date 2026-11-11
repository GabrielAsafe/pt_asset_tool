# P1/04 — Matriz de qualidade por evidência

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale quality-check --asset 'Field/Ricarten/village-2.smd' --execute --build
# Pode cruzar com evidência existente de exportação GLB:
python3 app/pt_asset.py etervale quality-check --asset 'Field/Ricarten/village-2.smd' --execute --texture-report 'app/pt_build/etervale/exports/ID.json' --strict
```

Aceita `.smd`, `.smb`, `.inx` e `.part` da source ou candidatos em `pt_build`. Para SMD/SMB/INX usa `AssetDump --full`; para `.part` faz somente inspeção estática limitada. A matriz separa geometria, materiais, texturas, animações, colisão, efeitos e prova visual. **Leitura do arquivo não certifica colisão física, timing de movimento, rendering, áudio ou partículas em runtime.**

Nenhuma alteração de `Client/`, `Server/`, `Shared/` ou arquivos de dados é feita. Logs completos e resultados ficam em `pt_build/etervale/quality/`.
