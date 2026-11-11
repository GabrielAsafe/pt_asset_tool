# Etervale — Diagnóstico de texturas e GLB em staging

A implementação de `PristonTale.GltfExport` do Etervale fornecido em novembro de 2026
já possui uma opção interna de rastreamento: `PTGLTF_DEBUG=1` imprime as texturas
que não foram encontradas ou decodificadas. A ponte do Asset Tool agora ativa essa
opção somente no processo do exportador e registra as ocorrências no JSON de saída.
Não modifica os binários originais nem o repositório do jogo.

## Diagnosticar o mapa Ricarten

```bash
cd ~/Transferências/pt_asset_tool
python3 app/pt_asset.py etervale export-glb \
  --asset 'Field/Ricarten/village-2.smd' \
  --output 'glb/village-2-texture-audit.glb' \
  --execute
```

O relatório de exportação inclui `texture_fallbacks` (nome e motivo),
`missing_or_invalid_texture_count`, `texture_trace_complete` e
`texture_diagnostic_status`. O argumento `--strict-textures` torna a execução
não aprovada (código de saída 3) quando o exportador registra texturas ausentes
ou não consegue comprovar cobertura. O GLB gerado permanece somente no staging.

```bash
python3 app/pt_asset.py etervale export-glb \
  --asset 'Field/Ricarten/village-2.smd' \
  --output 'glb/village-2-strict.glb' \
  --strict-textures --execute
```

**Não reaproveite o nome de um output existente:** o Asset Tool não sobrescreve
arquivos de staging por padrão. Use outro nome ou mova o output para arquivo.

## Inspecionar um GLB já exportado

```bash
python3 app/pt_asset.py etervale inspect-glb \
  --file "$HOME/Transferências/pt_asset_tool/app/pt_build/etervale/glb/village-2.glb"
```

O comando lê o cabeçalho, as tabelas de chunks, o JSON glTF 2.0 e referências
internas de cenas, nós, meshes, primitivas, accessors, materiais e imagens.
Não usa Blender nem .NET e não altera o arquivo.

**Níveis de prova:** `GLB_VALID_STRUCTURAL_ONLY` prova estrutura do contêiner
verificável pela rotina Python, não reprodução perfeita de materiais, coordenadas,
iluminação, animação, colisão nem carregamento nativo no jogo. O estágio completo
continua exigindo visualização humana e regressão no runtime do Etervale.

## Limites

- A lista de fallbacks é capturada do log de diagnóstico do exportador C#;
  não substitui uma inspeção completa de toda dependência de textura do mapa.
- Se o log exceder o tamanho retido pela ponte, o campo
  `texture_trace_complete` será falso.
- Correções devem ser feitas em uma área de staging e validadas antes de qualquer
  publicação. Não invente uma textura substituta no `assets/`.
