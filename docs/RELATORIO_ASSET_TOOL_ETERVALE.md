# PT Asset Tool → Etervale: inventário horizontal e análise vertical

**Data de referência:** 2026-11-09  
**Escopo examinado:** `assetTool.zip` (código, 97 documentos Markdown, contratos e testes), árvore atual informada da pasta `/home/gabriel/Transferências/Etervale-git`, e árvore histórica fornecida em `Texto colado(20261109-071622).txt`.  
**Limitação fundamental:** o conteúdo real do repositório Etervale não foi anexado; só sua listagem `tree -L 2`. Esta revisão **não** é uma certificação de compatibilidade com os leitores, pipelines ou o runtime C# do jogo. Nenhum arquivo do projeto local foi alterado.

## 1. Conclusão de arquitetura

O Asset Tool atual foi construído para uma disposição legada com três autoridades distintas: **cliente de assets**, **servidor de dados** e **código-fonte C/C++**. O Etervale reúne os recursos físicos em `assets/` e distribui sua implementação em `Client/`, `Server/`, `Shared/`, `Persistence/`, `tools/` e `scripts/`, sob uma única raiz de projeto. A migração correta substitui **três caminhos configurados pelo usuário por uma raiz de solução**, mas conserva múltiplas **funções lógicas derivadas dessa raiz**. Não é seguro apontar indiscriminadamente os três antigos campos para a pasta superior.

Mapeamento pretendido, sujeito a verificação dos arquivos reais:

| Papel lógico | Origem Etervale proposta | Cuidado |
|---|---|---|
| `game_root` (novo) | `/home/gabriel/Transferências/Etervale-git` | Valor único solicitado na UI |
| `asset_root` / client físico | `<game_root>/assets` | Inventário, SMD, SMB, INX, texturas, wav, efeitos, field etc. |
| Dados legados de servidor | `<game_root>/assets/GameServer`, quando a árvore real e os leitores confirmarem | Os parsers atuais esperam caminhos relativos a `GameServer/...` sob `server_root`; adaptar com *resolver* de namespace |
| Código do cliente | `<game_root>/Client` | C#; não é client_root físico |
| Código do servidor | `<game_root>/Server` | C#; não é server_root de assets |
| Código comum / contratos | `<game_root>/Shared` | C#; construir extratores específicos |
| Persistência | `<game_root>/Persistence` | Código e state fora do domínio de assets editáveis |
| Conversores / ferramentas do jogo | `<game_root>/tools`, `<game_root>/scripts` | Integração declarativa, sem executar arbitrariamente |
| Artefatos 3D auxiliares | `<game_root>/3d_glb/blender` | Produto de apoio, não publicar automaticamente |
| Build do Asset Tool | `pt_build` persistente **fora de `<game_root>/assets`** | Nunca misturar staging/backups e conteúdo rastreado do jogo |
| Canonical Summit V2.11–V2.12 | Habilitar só se `Content/CANONICAL_SOURCE.json` e toolchain de packs existirem | A árvore Etervale fornecida não mostra essa estrutura |
| Source C/C++ de referência/donors | Configuração opcional separada | Não precisa fazer parte do fluxo principal de uso |

## 2. Análise horizontal — matriz de funcionalidades

**Legenda:** `RO`: lê/analisa; `STAGE`: produz em workspace; `EXT`: ferramenta externa; `TX`: publicação transacional com confirmação; `DIAG`: diagnóstico/evidência; `COND`: função dependente de formato, fonte, pesos, runtime ou gate. `Verificado` refere-se apenas ao pacote e/ou a testes de exemplo, **não ao Etervale real**.

| # | Área | Funcionalidades e propósito | Entradas e saídas principais | Estado e migração |
|---:|---|---|---|---|
| 1 | Inicialização | Status, doctor, smoke, dependências | JSON/diagnósticos e capacidade | RO; raiz única **não implementada** |
| 2 | Configuração | Roots persistentes, Blender, donors, perfis | `pt_build/state/pt_asset_app_config.json` | Configuração separada legada; refatorar |
| 3 | Registry | Indexar assets, normalizar paths, famílias e pares | `asset_inventory.json`, `inx_physical_pairing.csv` | RO/STAGE; varrer `assets/` |
| 4 | Catálogo | Filtros, galeria, favoritos, seleção e ações contextuais | Estado local, detalhes e previews | RO; UI existente |
| 5 | Entidades | Characters, itens, monsters, NPCs, effects, maps | Catálogo físico/relacional e evidence | DIAG; contratos novos precisam conferência |
| 6 | Preview SMD | Pré-visualizações unitárias e em lote | Thumbnails/cache e relatórios | STAGE/EXT conforme caminho |
| 7 | Perfis / LOD | Corpos, cabeças, variações, INX/SMB, root skeleton | Relatórios de binding/profile | RO; exige semântica do loader real |
| 8 | Model 0.62 | Parse de static, rigid Physique, materiais, texlinks e textura | Evidências, SMD candidates | RO/STAGE, writers limitados |
| 9 | Object-local | Inspeção e roundtrip de transforms animados | SMD/relatórios de corpus/witness | STAGE/COND |
| 10 | Rare rigid | Casos cross-object, large, multibone extent, witness | SMD candidates, `.blend`, evidência | STAGE/EXT; políticas por caso |
| 11 | Mixed Physique | Diagnósticos sintéticos e pesquisa | Relatórios e candidatos | Não certificado para produção 1.0 |
| 12 | Stage 0.72 | Parse de stage, materiais, geometria, normais, UV e paint | SMD candidates, `.blend`, auditorias | STAGE/EXT; validar no renderer C# |
| 13 | INX | Inspeção e edição allowlisted de MotionInfo | INX candidato e relatório roundtrip | STAGE; variantes modern/legacy |
| 14 | SMB | Inspeção de tracks e modificação de chaves existentes | SMB candidato e relatório | STAGE; não cria/remove keys |
| 15 | Animação | Resolução de motion, pose e actions Blender | `.blend`, relatórios de pose/action | EXT/COND; não equivale a teste in-game |
| 16 | Texturas legadas | Diagnóstico BMP/TGA protegidos, alpha, codecs | Relatórios, imagens candidatas | RO/STAGE; casos especiais |
| 17 | Texture Upscale | Lanczos ou Real-ESRGAN, 2×–4×, lote/resume | `texture_upscale/runs/**/overlay`, manifest | STAGE; TX separada e alto risco de atlas |
| 18 | Material Lab 1× | Restauração, denoise/IA, mapas height/normais, parallax demo, revisão | `texture_material/runs/**` | STAGE offline; testado com PNG sintético |
| 19 | Mesh repair | Auditoria SMD, ajustes de normais/smooth em cópia Blender | JSON, novo `.blend`, manifest | RO/EXT; export/runtime não certificados |
| 20 | Partículas | `.part` inspect, draft, diff, verify, preview aproximado | Draft + plano + `.blend`/PNG | STAGE/EXT; nunca equivalência runtime implícita |
| 21 | Source evidence | Busca de literals, skills, áudio, headers, handlers | Contract JSON/graphs | DIAG; **scanner C/C++ incompatível com C# sem adaptação** |
| 22 | Server inventory | Lifecycle, arquivos estáticos, compartilhados, persistência | `server_inventory/result.json` | RO; layout `GameServer` legado |
| 23 | Server bundles | Monster/NPC, Field, OpenItem, ZHOON e closures | JSON de coverage/gaps | DIAG; adequar paths e contratos |
| 24 | Field Editor | SPM, SPP 200×12, SPC 100×504 | Drafts e manifests em `server_field_editor` | STAGE; layout específico e typed gates |
| 25 | Legacy Management | Inspeção de contratos históricos, planos de tarefa, APIs locais | Relatórios, planos SQLite / staging | RO/STAGE; não executa EXEs históricos |
| 26 | Legacy Authoring | ITEM/MONSTER/NPC/SPM/SPP/SPC criar/editar | Overlay + manifest, TX explícita | Condicionado a source/runtime e formato |
| 27 | Summit Canonical | Semantic Catalog V2, edição JSON e packs | `Content/canonical`, `.sres/.scfg/.sfld/...`, BUILD | COND: não comprovado no Etervale |
| 28 | Grafo de contratos | Caminhos client/server/source, referências e closure | JSON graphs, TSV evidence | DIAG; adaptar leitores C# |
| 29 | General Census | Cobertura, dependências, gaps e relatórios agregados | `general_asset_census/**`, ZIP | RO/STAGE; resultados dependem das roots |
| 30 | Retenção / cooked DDS | Reachability, órfãos e estado cook | `asset_retention/**`, `cooked_texture_evidence/**` | RO; órfão **não autoriza delete** |
| 31 | Quarentena | Q0 e Q1 com seleção estrita, hashes e restore | `quarantine_store`, plano e transação | TX reversível; não há delete |
| 32 | Donors / recovery | Localização, hashes, fechado/recoverable, overlays | Inventários, recover, proveniência | RO/STAGE; fonte opcional |
| 33 | Agregação | player classes, client/server/summit superset | Overlays, manifests, conflitos, bundle ZIP | STAGE; sem bulk deploy |
| 34 | Asset Compiler | Receitas tipadas, multiasset bundles e validação | Overlay compilado, plan, manifest | STAGE; depende de contratos efetivos |
| 35 | Deploy | Planejar, simular, publicar bundle, reverter | Backups, hashes, transações | TX; proteger Git e evitar client/server alias |
| 36 | Tree compare | Comparar árvores por hash, extensão e namespace | Diferenças JSON | RO; pode comparar snapshots do Etervale |
| 37 | Jobs / Reports | Fila, console, cancelamento, revisão humana | `pt_build` reports/jobs | UI/BUILD; melhorar rastreio outputs |
| 38 | Gates / certificação | Corpus, roundtrip, release, provenance, code/doc/package checks | JSON/JSONL, evidence | **passagem unitária ≠ runtime válido** |
| 39 | Aplicação portátil | PyInstaller, cache/state XDG, SHA snapshot | executável Linux + payloads + manifesto | Condicionado ao rebuild e dependências nativas |

## 3. Análise vertical — funcionamento e propósito

### 3.1 Bootstrap, configuração e fronteiras de escrita

**Arquivos:** `app/pt_asset.py`, `app/pt_asset_gui.py`, `pt_asset_tool/app_config.py`, `config.py`, `runtime_paths.py`, `deployment.py`. `pt_asset.py` agrega CLI moderno e comandos de compatibilidade. `app_config.py` conserva `client_root`, `server_root`, `source_root` e `reference_source_root` como campos independentes; a busca automática ainda testa disposições históricas `cliente`, `client`, `Servidor`. `Settings.discover` gera registry em `pt_build/state/asset_registry` depois de resolver o cliente. O app congelado usa caminho XDG / `PT_ASSET_HOME`; a versão source mantém `app/pt_build`. O novo design precisa de `game_root`, ressolução de papéis e relatórios de resolução; *não* uma substituição textual cega de paths.

**Prova de incompatibilidade atual:** num clone sintético com `Client/*.cs`, `Server/*.cs` e `assets/GameServer`, o scanner de source encontrou **0/2** arquivos `.cs` e os candidatos de descoberta de client/server **não incluíram** `<repo>/assets`. Este teste verifica o comportamento do Asset Tool, não inspeciona o repositório Etervale real.

### 3.2 Indexação, catálogo e navegação

**Arquivos:** `registry_bootstrap.py`, `registry.py`, `resolver.py`, `semantic_path.py`, `ui_catalog.py`, `entity_catalog.py`, `ui_capabilities.py`. Um root de assets é indexado fisicamente; os caminhos podem ser resolvidos com respeito a caixa e contexto de pasta. O registry classifica assets e monta relações entre SMD/INX/SMB, personas e funções. A UI consulta índices e só expõe ações cuja combinação `kind`, `family`, bindings e estado físico satisfaz os pré-requisitos; ações ainda são revalidadas no backend. **Resultado:** lista navegável, facetas, entidades e cartões de inspeção, não um arquivo novo no jogo.

### 3.3 Assets Model0.62, rig e materiais

**Arquivos:** `model062_*`, `physique_audit.py`, `profile_registry.py`, `rigid_*`, `rare_rigid_*`, `object_local_*`, `multilayer_texlink.py`, `material_group_compiler.py`. A ferramenta reconstrói estruturas binárias observadas e transporta candidatos controlados ao Blender. Os writers não aceitam mudança arbitrária: preservam layouts e identidades quando necessário, com no-op/roundtrip e testemunhos de modificação. Rigid Physique pode depender de INX/SMB externos, então um SMD presente não prova animação jogável. Mixed Physique físico continua fora da cobertura de produção declarada. **Resultado:** SMD/relatórios/arquivos Blender em staging; carregar no runtime continua gate separado.

### 3.4 Stage0.72

**Arquivos:** `stage072_compiler.py`, `stage072_geometry.py`, `stage072_normals.py`, `stage072_material_writer.py`, `stage072_roundtrip.py` e scripts `blender/open_stage072_*`, `write_stage072_*`. O pipeline lê stage, avalia materiais e UV, gera workspace Blender para preview/paint e recompila mudanças delimitadas, com recalculo de dados derivados quando suportado. **Resultado:** SMD candidate e JSON de validação. **Limite:** comprovação do parser/writer não demonstra automaticamente compatibilidade com o código `Client/PristonTale.Engine3D` / `Shared/PristonTale.Assets` do Etervale.

### 3.5 Motion INX, SMB e Blender

**Arquivos:** `motion_core.py`, `inx_writer.py`, `smb_writer.py`, `animation_corpus.py`, `animation_certification.py`, `blender_workspace.py` e bridges Blender. O INX aponta para motion e contexto; o SMB armazena tracks. O asset tool resolve ação, duração e skeleton para importar, validar frames e produzir alteração controlada de MotionInfo/chave existente. **Resultado:** writer candidate, `.blend`, relatórios de pose e regressão. **Limite:** ausência de teste em runtime Etervale e operação allowlisted.

### 3.6 Texturas e pipelines IA

**Arquivos:** `texture_upscale.py`, `texture_overlay.py`, `texture_material_pipeline.py`, `texture_material_maps.py`, `texture_material_quality.py`, `texture_model_runner.py`, `texture_ncnn_runner.py`, `texture_mesh_fix_blender.py`. Dois fluxos diferentes: **upscale 2×–4×** (Lanczos/Real-ESRGAN) e **Material Lab 1×** (restauro/denoise/mapas offline). O primeiro tem publish/restore transacional de texturas; o segundo **não** publica mapas parallax/normal no jogo nem altera shaders. Backend IA depende de modelos, hashes, binários e GPU configurados. A futura movimentação dos arquivos de IA e o empacotamento são uma frente separada, conforme combinado.

**Smoke real feito nesta análise:** com um PNG RGBA 24×16, `texture-material run --denoise off --maps from-diffuse` terminou com status `staged`, escala 1, sem modificar o input, e criou: `manifest.json`, `overlay/Image/Field/stone.png`, `maps/...height.png`, `normal_dx.png`, `normal_gl.png`, `parallax_demo.png`, `previews/...before.png`, `after.png`, `difference.png`, `review_001.html`. O source SHA-256 e output SHA-256 foram idênticos. O teste comprova **estrutura de produção e não-mutação para esse caso**, não qualidade visual, GPU, shader ou integração in-game.

### 3.7 Partículas `.part`

**Arquivos:** `particle_service.py`, `pt_part_editor.py`, `pt_effect_preview.py` e UI. Parse textual/semântico → seleção de ocorrência → draft → diff/verify → plano determinístico → preview Blender opcional. **Resultado:** draft, JSON, PNG e `.blend` isolados. O preview tem o rótulo `BLENDER_PREVIEW_APPROXIMATE`: não representa equivalência com blend/timing/billboard do runtime do jogo.

### 3.8 Dados server legados e Field

**Arquivos:** `server_inventory.py`, `server_lifecycle.py`, `server_environment_validation.py`, `server_bundle_census.py`, `server_item_census.py`, `server_field_census.py`, `server_field_editor.py`, `legacy_authoring.py`. O server clássico é tratado como árvore de `GameServer`, `char`, `Field`, `Configs` e dados de persistência. O auditor conserva a distinção entre asset estático, shared 3D, config de revisão, logs e estado sensível. O Field usa SPM textual, SPP 2.400 bytes (200×12), SPC 50.400 bytes (100×504). Editores trabalham em draft e publicação é transação explícita quando habilitada. **Problema de migração:** `Server/` na nova árvore é um **projeto C#**; os recursos legados aparecem sob `assets/GameServer`, logo os caminhos precisam de um adaptador e os writers precisam de compatibilidade com a semântica atual.

### 3.9 Source contracts / C#

**Arquivos:** `source_catalog.py`, `source_evidence.py`, `source_contract_census.py`, `skill_contract_census.py`, `contract_graph.py`. O scan existente percorre somente `.c`, `.cc`, `.cpp`, `.cxx`, `.h`, `.hh`, `.hpp`, `.hxx`, `.inl`, `.inc`, `.rc`, e seus detectores são em boa parte regex para funções/macros da engine C/C++. O novo Etervale exige detectar referências C# (fontes de assets em `.cs`, `Content`/pipeline, contratos do `Shared`, identificadores, import/export) com análise explícita e regras de confiança. Apenas adicionar `.cs` à lista de extensões **não torna as regras antigas corretas**. **Resultado atual:** sem adaptação, relatórios de source podem omitir referências verdadeiras e induzir falsos órfãos.

### 3.10 Entidades, closure e recuperação

**Arquivos:** `general_asset_census.py`, `contract_graph.py`, `asset_retention.py`, `cooked_texture_evidence.py`, `general_asset_recovery.py`, `donor_recovery_explorer.py`, `superset_aggregation.py` e `enrichment_vendor_adapter.py`. O fluxo faz inventário físico, resolve dependências e source evidence, constrói grafo, computa strong-root reachability, classifica gaps e prepara overlays de donors autorizados. Relatórios podem conter `PRESENT_TARGET`, `RECOVERABLE_REFERENCE`, `CONFLICT`, `MISSING_UNKNOWN`, `ORPHAN_CANDIDATE`, componentes `URC-*`. **Ponto de segurança:** desconhecido não é órfão confiável; nem `ORPHAN_CANDIDATE` nem rank Q1 autorizam delete. A versão para C# deve impor uma categoria `SOURCE_BINDINGS_INCOMPLETE` e não promover órfãos enquanto o scanner C# não estiver comprovado.

### 3.11 Authoring canônico V2.11/V2.12

**Arquivos:** `summit_canonical.py`, `canonical_authoring.py`, `legacy_name_catalog.py`; docs `SUMMIT_CANONICAL_SOURCE_V211` e `SUMMIT_CANONICAL_EXTENDED_DOMAINS_V212`. Quando `Content/CANONICAL_SOURCE.json` existe, a fonte autoritativa é `Content/canonical/**`; o writer tipado preserva schema/diretivas e compila packs. São distintos `maps_client.smap` e `maps_server.smap`, `field_runtime.sfld`, `definitions_client.scfg`, `definitions_server.scfg`, `text_resources.sres`, `localization.sloc`, `gameplay_config.sgcf`, `gameplay_reference.sgrf` e `coin_shop.scsp` (10 arquivos na lista de código atual, após extensão V2.12). O publish é em fases: canonical source → packs/BUILD → deploy de runtime separado. **Não assumir presença** dessa arquitetura no Etervale, porque a árvore apresentada não contém `Content/`.

### 3.12 Publicação, hashes, restore e isolamento

**Arquivos:** `asset_bundle_deploy.py`, `workspace_bundle_deploy.py`, `deployment.py`, `asset_quarantine.py`, `asset_compiler.py`, `build_provenance.py`. Staging grava source/candidate hash e manifesto; publish confere drift e exige token de operação, gera backup, escreve atomicamente, verifica os bytes e disponibiliza restore. A UI possui arms separados para workspace/build, client e server. No repo unificado, client/server podem compartilhar a mesma `assets/`: isso obriga a verificar o papel do arquivo, proibir conflito de destino e proteger `.git`, `.sln`, dados de persistência, certificados, ferramentas e o próprio `pt_build` contra qualquer write por uma rotina de assets.

### 3.13 Interface e orquestração

**Arquivos:** `ui_static/index.html` (742 linhas), `ui_static/app.js` (572 linhas de JavaScript densas), `ui_static/app.css`, `ui_app.py` (servidor HTTP/API), `ui_actions.py` (allowlist/command building), `ui_capabilities.py` (ações permitidas), `ui_jobs.py` (execução/revisão). Abas físicas encontradas: **Catalog, Entities, Client / Enrichment, Server / Enrichment, Management Legacy, Particles, Comparar, Jobs, Reports, Help / Guides, Settings**. A UI já mistura fluxos de auditoria, edição e deploy; há textos EN/PT. O redesign deve partir da validação de contrato dos resultados de cada job, não de uma troca cosmética.

### 3.14 Documentação, testes e empacotamento

O ZIP contém **899 entradas**, **97 documentos Markdown**, **271 módulos Python** dentro de `app/pt_asset_tool` (incluídos helpers `blender/`) e **126 arquivos de testes `app/dev_tests/test_*.py`**, além de testes externos. A documentação inclui material autoritativo em `docs/en`, histórico em português, manuais de CLI, tabela de writers, planos de integração e um inventário de símbolos gerado.

A distribuição traz evidência histórica de versões/status distintos; por isso **o cabeçalho de versão ou o `CURRENT_READINESS.json` não deve ser tratado como prova de funcionamento atual**. Testes realizados agora neste ZIP extraído:

- **Pytest selecionado:** `166 passed, 1 failed` em 18,17 s. Falha em `tests/test_texture_ncnn_pipeline.py::test_tile_cache_inside_input_client_is_rejected`: o teste substitui o módulo `texture_material_profiles` por stub sem `ADAPTIVE_PROFILE`, mas o código de produção consulta essa constante. A primeira correção deve ser atualizar o stub e repetir a proteção que o teste pretende verificar; o resultado não demonstra que o cache real pode ser escrito dentro do client.
- **`VERIFY_PACKAGE.sh`:** `PACKAGE_VERIFY=FAIL missing=.gitattributes`. O ZIP distribuído está incompleto em relação ao snapshot manifest; confirmar no repositório original se o arquivo existe antes de alterar o verificador.
- **Documentação:** `DOC_AUDIT files=85 errors=1`, com `docs/en/engineering/SOURCE_API_REFERENCE.md` desatualizado em relação ao código atual. Regenerar a referência pelo gerador oficial e validar, sem editar o arquivo gerado manualmente.
- **Material Lab 1× com PNG sintético:** execução CLI `EXIT=0`, `staged=1`, `upscale_performed=false`, `client_modified=false`, hashes originais preservados; gerou os 10 arquivos listados acima.
- **Teste de layout C# sintético:** 2 arquivos C# físicos, 0 arquivos identificados pelo scanner atual; `assets/` não descoberto automaticamente nem como client nem como server a partir da app.

Nenhuma dessas execuções usou o repositório real do jogo nem certificou Vulkan/NCNN real, Blender, runtime MonoGame, builds `.NET`, dados reais de `assets/` ou publicações transacionais contra a source do usuário.

## 4. Ordem recomendada para adaptação e redesenho da UI

1. **Criar `EtervaleProjectLayout`:** um único `game_root` configurável; identificar `assets`, `Client`, `Server`, `Shared`, `Persistence`, `tools`, `scripts`, `3d_glb`. Exibir diagnóstico de presença e não habilitar funcionalidades sem pré-condições.
2. **Separar papéis de disco:** `asset_root`, `server_data_namespace`, `client_code_roots`, `server_code_roots`, `shared_code_roots`, `toolchain_roots`; preservar roots legadas opcionais e donors sem exigir três inputs na tela.
3. **Adaptar catálogo e parsers:** varrer `assets/` e auditar amostra real de cada extensão, casing e resolução; comparar cabeçalhos e bytes com o novo `PristonTale.Assets`/`PristonTale.Engine3D` antes de aceitar writer.
4. **Implementar evidência C# válida:** extração de asset IDs, paths, loaders, processamento de `MonoGameRuntime.targets`, geradores de `tools/`, e novos tipos de edges; proteger retenção/quarentena enquanto coverage do C# for desconhecida.
5. **Construir testes de contrato de output por script:** input real versionado ou fixture, comando, artefatos esperados, schema, SHA-256, dimensões, diff, determinismo, parser de volta e loader do jogo; três estados **GERADO**, **VALIDADO PELO TOOL**, **VALIDADO NO RUNTIME**.
6. **Auditar e corrigir divergências existentes:** mock `ADAPTIVE_PROFILE`, `.gitattributes` do snapshot, API reference gerada, status históricos, documentação de formatos/source.
7. **Somente então redesenhar UI:** entrada única *Selecionar projeto Etervale*; inventário do projeto; seções *Explorar*, *Criar/Editar*, *Validar*, *Publicar/Reverter*, *Histórico/Relatórios*, com status de cada etapa e previews antes/depois. Diferenciar leitura, geração de candidato e operação efetiva no Git.
8. **Tratar IA/empacotamento em fase posterior:** definir resolução de modelos/payloads, hashes, versões, ncnn Vulkan/PyTorch, compartilhamento XDG e distribuição portátil, sem misturar com a validação de formatos.

## 5. Contrato proposto para a futura UI de validação

Para cada ferramenta/processador, apresentar:

| Campo | Exemplo / regra |
|---|---|
| Origem | `assets/Field/...` ou definição do `Shared/` |
| Processador | `stage072_compiler` com versão/sha do código |
| Operação | `inspect`, `roundtrip`, `edit`, `export` |
| Estado 1 | `INPUT_VALID` ou causa precisa |
| Estado 2 | `GENERATED`; lista completa do que saiu |
| Estado 3 | `PARSER_ROUNDTRIP_PASS`; hashes, deltas e schema |
| Estado 4 | `CLIENT_LOADER_PASS`; evidence do projeto C# em teste, não inferência |
| Estado 5 | `RUNTIME_VISUAL_PASS` / `NOT_TESTED`, quando aplicável |
| Destino | Workspace isolada e artefato de candidato |
| Autorização | `READ_ONLY`, `STAGE_ONLY`, `PUBLISH_ARMED` (nunca automática) |
| Segurança | Target unchanged, backup e restore auditáveis |

A transformação física para o Etervale deve ser dirigida por testes de compatibilidade entre **bytes que o Asset Tool produz** e **bytes que o projeto C# consome**. Sem esse cruzamento, uma UI renovada corre o risco de apresentar um output como pronto mesmo que o jogo não o aceite.

## Apêndice — índice dos documentos Markdown localizados no ZIP

Este índice registra o corpus documental considerado, inclusive documentação histórica e a referência de API gerada.

| Documento | Linhas | Título de abertura |
|---|---:|---|
| `docs/CURRENT_STATUS_2026-09-14.md` | 43 | PT Asset Tool R14 1.0.0 — Estado Atual Final |
| `docs/README.md` | 33 | PT Asset Tool Documentation |
| `docs/cobertura_funcional/FEATURE_MATRIX_1_0.md` | 49 | PT Asset Tool R14 1.0.0 — Matriz de Funcionalidades |
| `docs/cobertura_funcional/FORMATS_WRITERS_1_0.md` | 119 | PT Asset Tool R14 1.0.0 — Formatos, Parsers e Writers |
| `docs/cobertura_funcional/RECOVERY_AGGREGATION_DEPLOYMENT_1_0.md` | 50 | PT Asset Tool R14 1.0.0 — Aggregation, Recovery, Build e Deploy |
| `docs/cobertura_funcional/REPORTS_OUTPUTS_1_0.md` | 50 | PT Asset Tool R14 1.0.0 — Relatórios, Evidence e pt_build |
| `docs/cobertura_funcional/SECURITY_SAFETY_1_0.md` | 123 | PT Asset Tool R14 1.0.0 — Modelo de Segurança e Autoridade |
| `docs/cobertura_funcional/SERVER_ENRICHMENT_1_0.md` | 125 | PT Asset Tool R14 1.0.0 — Manual Server / Asset Enrichment |
| `docs/cobertura_funcional/TROUBLESHOOTING_1_0.md` | 145 | PT Asset Tool R14 1.0.0 — Troubleshooting |
| `docs/comece_aqui/CLI_REFERENCE_1_0.md` | 1796 | PT Asset Tool R14 1.0.0 — Referência CLI Completa |
| `docs/comece_aqui/DEPENDENCIES.md` | 61 | Dependências do PT Asset Tool |
| `docs/comece_aqui/GUI_MANUAL_1_0.md` | 209 | PT Asset Tool R14 1.0.0 — Manual da GUI |
| `docs/comece_aqui/INSTALLATION_QUICKSTART_1_0.md` | 150 | PT Asset Tool R14 1.0.0 — Instalação e Quick Start |
| `docs/comece_aqui/MANUAL_UTILIZADOR.md` | 2889 | PT Asset Tool R14 1.0.0 — Manual Completo do Utilizador |
| `docs/en/README.md` | 58 | PT Asset Tool — English Documentation |
| `docs/en/engineering/ARCHITECTURE.md` | 30 | Architecture |
| `docs/en/engineering/DEVELOPER_MANUAL.md` | 51 | Developer Manual |
| `docs/en/engineering/MODULE_REFERENCE.md` | 33 | Module Reference |
| `docs/en/engineering/SOURCE_API_REFERENCE.md` | 5751 | Source API Reference |
| `docs/en/engineering/SUMMIT_GAME_ASSET_ENRICHMENT.md` | 53 | Summit Game Asset Enrichment |
| `docs/en/engineering/VALIDATION_RUNBOOK.md` | 61 | Validation Runbook |
| `docs/en/functional/FEATURE_MATRIX.md` | 21 | Feature Matrix |
| `docs/en/functional/FORMATS_AND_WRITERS.md` | 24 | Formats and Writers |
| `docs/en/functional/RECOVERY_AGGREGATION_DEPLOYMENT.md` | 21 | Recovery, Aggregation, and Deployment |
| `docs/en/functional/REPORTS_AND_OUTPUTS.md` | 22 | Reports and Outputs |
| `docs/en/functional/SECURITY_AND_SAFETY.md` | 19 | Security and Safety |
| `docs/en/functional/SERVER_ENRICHMENT.md` | 17 | Server Enrichment |
| `docs/en/functional/TROUBLESHOOTING.md` | 29 | Troubleshooting |
| `docs/en/getting_started/CLI_REFERENCE.md` | 109 | CLI Reference |
| `docs/en/getting_started/DEPENDENCIES.md` | 26 | Dependencies |
| `docs/en/getting_started/GUI_MANUAL.md` | 54 | GUI Manual |
| `docs/en/getting_started/INSTALLATION_QUICKSTART.md` | 62 | Installation Quick Start |
| `docs/en/getting_started/USER_MANUAL.md` | 174 | User Manual |
| `docs/en/release/KNOWN_LIMITATIONS.md` | 7 | Known Limitations |
| `docs/en/release/RELEASE_NOTES.md` | 13 | Release Notes — English Localization V2.10 |
| `docs/en/topics/ASSET_CONTRACT_GRAPH.md` | 18 | Asset Contract Graph |
| `docs/en/topics/ASSET_ENRICHMENT.md` | 13 | Asset Enrichment Guide |
| `docs/en/topics/ASSET_QUARANTINE_WORKFLOW.md` | 52 | Asset Quarantine Workflow |
| `docs/en/topics/ASSET_RETENTION_AND_COOKED_DDS.md` | 23 | Asset Retention and Cooked DDS Evidence |
| `docs/en/topics/CLIENT_SERVER_WORKFLOW.md` | 34 | Client / Server End-to-End Workflow |
| `docs/en/topics/DESIGN_TOOL.md` | 14 | Design Tool Guide |
| `docs/en/topics/EFFECTS_AND_PARTICLES.md` | 15 | Effects and Particles |
| `docs/en/topics/FIELD_METADATA_EDITOR.md` | 11 | Field Metadata Editor |
| `docs/en/topics/LEGACY_MANAGEMENT_AUTHORING.md` | 52 | Legacy Management Authoring |
| `docs/en/topics/PORTABLE_APP.md` | 11 | Portable Application |
| `docs/en/topics/SEMANTIC_AUTHORING_CATALOG.md` | 38 | Semantic Authoring Catalog |
| `docs/en/topics/SUMMIT_CANONICAL_EXTENDED_DOMAINS_V212.md` | 31 | Summit Canonical Source V2.12 — Extended Domains |
| `docs/en/topics/SUMMIT_CANONICAL_SOURCE_V211.md` | 46 | Summit Canonical Source Integration — V2.11 |
| `docs/en/topics/SUPERSET_AGGREGATOR.md` | 5 | Superset Aggregator |
| `docs/en/topics/TEXTURE_MATERIAL_LAB_POST_UPSCALE.md` | 10 | Material Lab: AFTER existing upscale |
| `docs/en/topics/TEXTURE_UPSCALE_PIPELINE.md` | 49 | Texture Upscale Pipeline |
| `docs/en/validation/LOCALIZATION_EN_V210.md` | 31 | English Localization Validation — V2.10 |
| `docs/engenharia/ARCHITECTURE_1_0.md` | 101 | PT Asset Tool R14 1.0.0 — Arquitetura |
| `docs/engenharia/LEGACY_MANAGEMENT_INTEGRATION_2026-09-20.md` | 140 | Integração das ferramentas legacy Management — 2026-09-20 |
| `docs/engenharia/MANUAL_DESENVOLVEDOR.md` | 1291 | PT Asset Tool R14 1.0.0 — Manual Completo do Desenvolvedor |
| `docs/engenharia/MAPA_MODULOS_SCRIPTS.md` | 782 | PT Asset Tool — Mapa de Módulos e Famílias de Scripts |
| `docs/engenharia/MODULE_REFERENCE_1_0.md` | 168 | PT Asset Tool R14 1.0.0 — Referência de Módulos |
| `docs/engenharia/REVERSE_ENGINEERING_FORMATOS.md` | 371 | PT Asset Tool — Referência de Formatos e Layouts Reversados |
| `docs/engenharia/SNAPSHOT_MANIFEST_POLICY.md` | 36 | Snapshot Manifest Policy |
| `docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md` | 137 | Summit Tale — Asset Enrichment integrado ao PT Asset Tool |
| `docs/engenharia/VALIDACAO_TESTES_DESENVOLVIMENTO.md` | 224 | Validação, Testes e Preparação de Release |
| `docs/engenharia/VENDOR_BOUNDARY.md` | 21 | Boundary de vendor/ |
| `docs/release/FINAL_CERTIFICATION_EVIDENCE.md` | 52 | Evidência Final de Certificação — PT Asset Tool R14 1.0.0 |
| `docs/release/KNOWN_LIMITATIONS_1_0.md` | 42 | PT Asset Tool R14 1.0.0 — Known Limitations |
| `docs/release/RELEASE_1_CERTIFICATION.md` | 30 | PT Asset Tool R14 1.0.0 — Certification |
| `docs/release/RELEASE_1_READINESS.md` | 35 | Release 1.0 Readiness — FINAL |
| `docs/release/RELEASE_NOTES_1_0.md` | 33 | PT Asset Tool R14 1.0.0 — Release Notes |
| `docs/tematicos/ASSET_CONTRACT_GRAPH.md` | 212 | Asset Contract Graph — source-backed completeness |
| `docs/tematicos/ASSET_QUARANTINE_WORKFLOW.md` | 137 | Asset Quarantine Workflow |
| `docs/tematicos/ASSET_RETENTION_AND_COOKED_DDS.md` | 455 | Asset Retention + Cooked DDS — integração com o ecossistema existente |
| `docs/tematicos/EFFECTS_PARTICLES.md` | 42 | Effects / Particles .part |
| `docs/tematicos/FIELD_METADATA_EDITOR.md` | 65 | Field Metadata Editor — SPM / SPP / SPC |
| `docs/tematicos/GUIA_ASSET_ENRICHMENT.md` | 467 | Guia do Summit Asset Enrichment |
| `docs/tematicos/GUIA_DESIGN_TOOL.md` | 250 | Guia do PT Asset Tool / Design Tool |
| `docs/tematicos/GUIA_WORKFLOW_CLIENT_SERVER.md` | 111 | Guia integrado — Client + Server |
| `docs/tematicos/LEGACY_MANAGEMENT_AUTHORING.md` | 418 | Management Legacy + Legacy Authoring Python |
| `docs/tematicos/MATERIAL_LAB_GUIA_FINAL_PATCH_CUMULATIVO.md` | 159 | PT Asset Tool — Material Lab: guia de instalação e utilização (patch cumulativo) |
| `docs/tematicos/MATERIAL_LAB_PERFIS_SEGUROS_1X.md` | 153 | Material Lab — perfis seguros para restauro por IA 1× (Summit / Priston Tale) |
| `docs/tematicos/PORTABLE_APP.md` | 88 | PT Asset Tool — Portable App |
| `docs/tematicos/SEMANTIC_AUTHORING_CATALOG.md` | 35 | Catálogo semântico de authoring — V2.9 |
| `docs/tematicos/SUMMIT_ASSET_MIGRATION_AUDIT.md` | 92 | Summit canonical asset migration audit |
| `docs/tematicos/SUMMIT_CANONICAL_SOURCE_V211.md` | 82 | PT Asset Tool V2.11 — Summit Canonical Source Integration |
| `docs/tematicos/SUPERSET_AGGREGATOR.md` | 325 | Summit Superset Aggregator — 0.17.0 |
| `docs/tematicos/TEXTURE_MATERIAL_LAB_POS_UPSCALE.md` | 135 | PT Asset Tool — Material Lab após upscale (Fases 3–6) |
| `docs/tematicos/TEXTURE_UPSCALE_PIPELINE.md` | 321 | Texture Enhance / Upscale — pipeline seguro |
| `docs/validation/INTEGRATION_ASSET_QUARANTINE_Q1_MANUAL_V28_2026-09-27.md` | 27 | Integration Validation — Asset Quarantine Q1 Manual V2.8 — 2026-09-27 |
| `docs/validation/INTEGRATION_ASSET_QUARANTINE_Q1_RANK_V27_2026-09-27.md` | 31 | Asset Quarantine Q1 Review Ranking V2.7 — 2026-09-27 |
| `docs/validation/INTEGRATION_ASSET_QUARANTINE_V26_2026-09-27.md` | 12 | Integration validation — Asset Quarantine V2.6 — 2026-09-27 |
| `docs/validation/INTEGRATION_ASSET_RETENTION_COOKED_DDS_2026-09-27.md` | 41 | Integration validation — Asset Retention + Cooked DDS — 2026-09-27 |
| `docs/validation/INTEGRATION_ASSET_RETENTION_COOKED_DDS_V23_2026-09-27.md` | 40 | Validation — Asset Retention + Cooked DDS metadata revision 3 — 2026-09-27 |
| `docs/validation/INTEGRATION_ASSET_RETENTION_ROOT_REACHABILITY_V24_2026-09-27.md` | 67 | Asset Retention Root Reachability V2.4 — integração 2026-09-27 |
| `docs/validation/INTEGRATION_EFFECT_RUNTIME_COMPONENTS_V25_2026-09-27.md` | 41 | Integração V2.5 — Effect Runtime Roots + Root-Unreachable Components |
| `docs/validation/INTEGRATION_LEGACY_AUTHORING_NAME_CATALOG_V29_2026-09-28.md` | 22 | Integration Validation — Legacy Authoring Semantic Catalog V2.9 |
| `docs/validation/INTEGRATION_SUMMIT_CANONICAL_V211_2026-10-01.md` | 75 | Integration Validation — Summit Canonical Source V2.11 |
| `docs/validation/PATCH_2026-09-16_FRESH_INSTALL_STATE.md` | 82 | Patch 2026-09-16 — Fresh install and runtime-state separation |
| `docs/validation/PATCH_2026-09-16_PACKAGE_RUNTIME_ALIGNMENT.md` | 19 | Patch 2026-09-16 — Package/runtime alignment |
| `docs/validation/PATCH_2026-09-16_VERIFY_DIAGNOSTICS.md` | 32 | Patch 2026-09-16 — Snapshot diagnostics and Blender availability |
