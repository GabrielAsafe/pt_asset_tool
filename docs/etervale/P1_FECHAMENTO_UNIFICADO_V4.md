# Etervale — P1 consolidado V4 (Asset Tool)

**Escopo:** evidências de P1/03 (dependências), P1/04 (qualidade estrutural), P1/05 (Fields) e P1/06 (UI). Sem alteração em C# nem em `Etervale-git/assets/`.

## O que foi acrescentado

- `p1-full-audit`: lê os formatos reais Stage 0.72 e Model 0.62 com os parsers já existentes, todas as referências regulares/animadas/opacity dos materiais usados, a geometria/UV, uma amostra estrutural de efeito `.part` (primeira do acervo, ou `--effect` explícito), Field SPM/SPP/SPC e a resolução das texturas segundo `PristonSmdReader` (BaseName) e `PristonTextureLoader.ResolvePath` (case-insensitive + extensões alternativas locais).
- `--execute`: valida os SMD/SMB/INX/BMP/TGA no `PristonTale.AssetDump` C#. Pixels de BMP/TGA somente aprovados quando o log informa dimensões válidas. `--build`: compila o AssetDump uma vez.
- `--world-import`: executa o `WorldImport` nativo com `--source` apontando a `assets/GameServer`, `--assets` à raiz real (somente leitura) e `--sqlite` exclusivo dentro de `pt_build/etervale/p1_world_import/<id>/isolated.sqlite`. Compara todos os arquivos da árvore GameServer antes/depois. Não toca no banco do jogo.
- `p1-closure-audit`: consolida prova de dependências locais, leitura C# de ambos os SMD + SMB/INX + pixels, importação SQLite e apresentação na UI; recusa relatórios referentes a assets cujos hashes ficaram obsoletos.
- `ui-board`: cartão de fechamento P1, continuando estritamente somente leitura.

## Execução recomendada

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_asset.py etervale p1-full-audit --execute --build --world-import
python3 app/pt_asset.py etervale p1-closure-audit
python3 app/pt_asset.py etervale ui-board
```

Os padrões cobrem `Field/Ricarten/village-2.smd`, Acero e Arcuda (SMD/SMB/INX/TGA), além de `Field/Dcave.ase.spm/.spp/.spc`. Use `--asset`, `--field` e `--effect` repetidos para amostras diferentes. Se `--asset` for usado, substitui *todos* os caminhos padrão; inclua Stage e Model, SMB, INX e imagem para reunir todas as evidências.

**Os resultados e logs completos ficam em:** `app/pt_build/etervale/p1_full/*.json`, `p1_world_import/` e `p1_closure/`. A saída do terminal é resumida. Mesmo em `--execute`, o auditor não publica ou altera assets do jogo.

## Status e decisões

| Estado | Significado |
|---|---|
| `P1_OFFLINE_PARSED_NATIVE_PENDING` | Parsing estrutural concluído, leitor C# ainda não executado |
| `P1_REVIEW_DEPENDENCIES` | Há uma ou mais referências sem prova de resolução local |
| `P1_READERS_PASSED_WORLDIMPORT_PENDING_RUNTIME_PENDING` | Leitores aceitam amostra, mas importação completa não foi executada |
| `P1_AUTOMATED_GATES_PASSED_RUNTIME_PENDING` | Todas as provas automáticas exigidas passaram, **não** é certificação visual |
| `P1_AUTOMATED_GATES_PASSED_WITH_ACKNOWLEDGED_GAPS_RUNTIME_PENDING` | Gaps documentados, mas **não reparados** |
| `P1_TECHNICAL_FAILURE` / `SOURCE_CHANGED` | Bloqueio de segurança/compatibilidade; revisar antes de publicar |

`p1-closure-audit` só retorna `P1_AUTOMATED_GATES_PASSED_RUNTIME_REVIEW_PENDING` com dependências resolvidas, readers, Field/WorldImport e UI íntegros. Referências declaradas como `--known-missing` continuam a contar como pendências; esse parâmetro registra ciência, não conserta o asset.

## Limitações conhecidas

1. O inventário de referências abrange os materiais associados a faces dos SMD selecionados, incluindo todas as camadas serializadas; não é uma auditoria global dos 39.956 assets nem dos efeitos externos.
2. Arquivo resolvido em outra pasta pelo mesmo basename é **candidato não confirmado**, não prova de carregamento. O Etervale baseia a textura no diretório do próprio SMD.
3. O material legado pode conter 3+ estágios, embora o renderer atual só carregue uma camada extra. Isso depende de trabalho posterior no motor.
4. A tela não mostra imagem renderizada nem valida alpha, colisão dinâmica, VFX, animações ou FPS por conta própria. A verificação `.part` é somente estrutural (não há certificado de renderização).
5. O `tem_wall04.bmp` é uma ausência conhecida na cena Ricarten. Sem o arquivo correto (ou uma decisão explícita de correção com testes visuais), não se deve registrar P1/03 como integralmente encerrado.
6. Os 80 unresolved refs do WorldImport são a base histórica. O novo fluxo com `--assets` real gera relatório próprio; diferenças precisam ser interpretadas por domínio, não equiparadas a problemas de textura.
7. Sem dotnet nesta máquina de empacotamento, a prova nativa definitiva é a execução na source do usuário.

**Aceitação de runtime:** ver `docs/etervale/P1_RUNTIME_CHECKLIST_V4.md`. Não alterar readers, runtime ou banco de produção para satisfazer o painel.
