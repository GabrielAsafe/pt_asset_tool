# P1/03 — Auditoria de texturas usadas no cenário

O relatório `asset-gaps` usa o `AssetDump --matbounds` do próprio Etervale para descobrir o número de faces por material e procurar a textura primária na pasta do SMD. Mantém a saída completa do processo (não apenas o tail de 12 KB), importante para mapas com centenas de materiais.

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale asset-gaps --asset 'Field/Ricarten/village-2.smd' --execute --build --strict
```

Relatórios JSON e CSV ficam em `app/pt_build/etervale/asset_gaps/`. `--strict` retorna código de erro se uma textura primária usada estiver ausente. A saída do comando continua com evidência mesmo diante do erro.

**Ocorrência já comprovada anteriormente (09/11/2026):** `tem_wall04.bmp`, material 173, 1 face, em `Field/Ricarten/village-2.smd`; não encontrada nas fontes pesquisadas. Não substituir por `lost_temple_wall04.bmp`: é outro asset.

**Escopo explícito:** apenas a textura primária listada em `--matbounds` e ligada a material com face. Cobertura de textura secundária, alpha maps, referências de INX/efeitos, JSON e relações de runtime exigirá outras auditorias. Este comando não declara o catálogo inteiro sem dependências.
