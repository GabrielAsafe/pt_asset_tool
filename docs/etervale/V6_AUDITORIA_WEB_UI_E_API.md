# PT Asset Tool × Etervale — V6: auditoria e correções do cliente web

**Alvo:** instalação V5 sobre `~/Transferências/pt_asset_tool`; checkout unificado `~/Transferências/Etervale-git`.
**Escopo:** `ui_static/index.html`, `app.js`, `app.css`, `ui_app.py`, `entity_catalog.py`.
**Sem mudanças no jogo:** não altera readers/renderer C#, assets nem bases de dados. Não cria Content JSON nem escreve schema.

## 1. Navegação e fronteiras de responsabilidade

A barra lateral passou a apresentar **Workspaces**, com subtabs:

1. `Client / Enrichment`: inventário, diagnósticos e tratamento de imagens do cliente;
2. `Server / Enrichment`: validação, inventário de `GameServer`, dependências e evidências;
3. `Management Legacy`: ferramentas históricas e autoria que ainda necessitam validação funcional;
4. `Comparar`: comparação de árvores e relações entre raízes.

Uma área **Support** reúne `Etervale Validation`, `Help / Guides` e `Settings`. Os fluxos mantêm os seus IDs/rotas originais para não perder o backend. Secções Summit são explicitamente assinaladas como **históricas**, não fonte de verdade do Etervale. A BD existente é a autoridade de dados tabulares; os ficheiros físicos mantêm geometria/efeitos/texturas. Não há integração com Content JSON.

## 2. Catálogo

| Observação inicial | Alteração V6 | Prova | Estado |
| --- | --- | --- | --- |
| Filtros cortados pelo zoom | Grid fluida com mínimos adaptáveis, painel responsivo e sem overflow horizontal | Chromium 1440/1152/1024/900/720/600/390 px | Teste estático de layout passou |
| Atalhos Characters/Monsters/NPCs/Items/Maps/Effects redundantes | Removida a faixa de botões; seletor `category` permanece | Inspeção DOM e regressão JS | Corrigido |
| `Show system/operational` pouco compreensível | Movido para `Advanced · system files`, com descrição de OPERATIONAL/USER_DATA/INSTALLER_SYSTEM/NOISE | DOM | Corrigido |
| Favoritos não respondem | Estrela na tabela e cards é botão próprio; envia `POST /api/state/update`; checkbox filtra pelo campo persistido | Testes UIStateStore/CatalogIndex + teste Chromium com simulação API | Corrigido na amostra |
| `RUNNING · 0/0` | Exibir `prontos/total`, `remaining` (`MISSING`, `STALE`, `FAILED`) e progresso; estado `preparando lote` quando job ainda não atribuiu entradas | API + teste browser | Corrigido |

**Nota:** o estado final do preview requer execução Blender. Os contadores do inventário não devem ser confundidos com os contadores do lote ativo.

## 3. Entities — sem identidades fictícias

- `Field/AncientW` e `GameServer/Field/AncientW.ASE.{spm,spp,spc}` passam a partilhar **uma entidade lógica** `MAP_FIELD|field:ancientw`, apenas se estiverem nas árvores físicas com evidência específica.
- O agrupamento não depende de nome solto nem da extensão; casos de `Image/AncientW.spm` não se misturam automaticamente.
- Lista e detalhe mostram contagens por extensão e categoria, além da contagem de assets.
- Filtros de tipo de ficheiro e origem (`client`, `server`, `linked`) são avaliados no backend antes de aplicar o limite de resultados.
- A cache de Entities deixa de substituir `innerHTML` se a mesma lista já estiver apresentada; conserva os elementos `<img>` e os erros/fallbacks. A API de preview tem ETag com revisão por metadados.
- **Nomes descritivos:** ainda mostramos a identidade física comprovada (ex.: `AncientW`). Para mostrar o nome de mapa amigável, precisaremos identificar o registo e a relação na **BD Etervale**; não consumir uma lista JSON externa nem inventar a correspondência.

## 4. Preview e partículas

- `/api/preview`: preserva o cache interno do decodificador e adiciona ETag/If-None-Match, cache HTTP privado com versão por `stat`.
- `/api/smd-preview`: deixa de usar `Date.now()` na URL no painel de detalhe, usa ETag e revalidação condicional (HTTP 304); quando o preview é regenerado, o browser pode recuperar os novos bytes.
- Partículas `.part`: a interface agora percorre os **frames de imagem amostrados pelo Blender** em sequência, com Play/Pause e contador. Isto **não equivale a simular a partícula no MonoGame** (emissores, gravidade, blend, profundidade, lifetime e eventos em runtime). O painel explicita esse limite; o renderer de partículas em tempo real continua uma implementação separada.

## 5. Auditoria de chamadas e elementos

O inventário estático V6 do JavaScript/HTML/backend encontrou:

| Tipo | Contagem |
| --- | ---: |
| Elementos HTML com ID | 401 |
| Seletores de ID referenciados no JS | 424 |
| Funções JS nomeadas | 228 |
| Atribuições diretas de handlers `on*` | 197 |
| Literais únicos de chamada `/api/` no JS | 81 |
| Rotas literais GET no backend | 53 |
| Rotas literais POST no backend | 42 |
| Rotas prefixadas GET | 1 |
| Linhas da matriz de cruzamento | 99 |
| Seletores JS sem elemento no HTML atual | 21 |

Os **21 seletores ausentes** concentram-se em antigos controles do Asset Compiler, do Server Explorer, do Field Editor e do Legacy Management Root. Muitas dessas seções foram retiradas da superfície navegável para reduzir duplicações; os handlers continuam no código como legado e requerem triagem antes de remoção/reutilização. O scanner não considera `POST /api/canonical/<ação>` sem resposta: é um caminho dinâmico cujo prefixo não corresponde a um literal do `if` simples. Alguns endpoints backend não são chamados diretamente por literais, pois podem vir de chamadas dinâmicas, outras páginas ou integrações CLI.

A matriz `V6_WEB_UI_API_CALL_GRAPH.csv` identifica rota, linhas de chamadas, método inferido e correspondência no backend. Não é uma certificação funcional de cada endpoint.

### Fluxos principais cruzados

| Área | Entradas principais | Interfaces/handlers |
| --- | --- | --- |
| Catalog | `/api/catalog`, `/api/state/update`, `/api/asset`, `/api/preview`, `/api/smd-preview*` | filtro, favoritos, seleção, preview e jobs |
| Entities | `/api/entities`, `/api/entity` | grupo, extensão, origem, detalhe e ligação com catálogo |
| Client / Enrichment | `/api/client*`, `/api/enhancement/batch-*`, `/api/material-lab/*` | leitura, diagnósticos e jobs de processamento |
| Server / Enrichment | `/api/server*`, `/api/contracts*`, `/api/asset-retention*` | raízes, inventário e evidências |
| Management Legacy | `/api/legacy-*`, `/api/asset-compiler/*`, `/api/canonical/*` | revisão de dados; alguns fluxos são históricos Summit e **não são certificados Etervale** |
| Comparar | chamadas de comparação existentes | árvores cliente/servidor e verificações |
| Particles | `/api/particles*` | inspeção, staging e preview Blender amostrado |
| Support | `/etervale-readiness`, `/api/bootstrap`, endpoints de configuração existentes | evidências, guias e parâmetros |

## 6. Provas executadas

- Regressões **120 testes pytest** (`114` P0/P1/V5 + `6` testes V6), aprovados na cópia de trabalho.
- Browser Chromium: tabs Workspaces/Support, favoritos com `POST` e filtro, preservação do DOM de Entities, contador SMD.
- Browser Chromium: layout da toolbar sem overflow em **sete viewports** até 390 px.
- `node --check` JavaScript aprovado.

As interações browser usam **backend simulado** e o layout usa HTML/CSS isolados. Não certificam a execução de todos os comandos no servidor real, a qualidade do playback de partículas nem a integridade de publicação de assets.

## 7. Pendências concretas para validação integral da UI

1. **Teste de ponta a ponta por operação**, em navegador ligado ao processo real, para todas as secções. Cobrir leitura, parâmetros, estados, erros e cancelamento, sem armar escrita desnecessariamente.
2. **13 módulos legados ativos** identificados na V5 continuam sujeitos a validação funcional e isolamento por contexto.
3. **21 seletores/handlers históricos**: confirmar cada destino, remover código morto após aprovação ou restaurar somente operações justificadas; nunca reativar um publicador legado sem provar segurança.
4. **Mapas com nomes humanos**: pesquisar associação da BD existente antes de substituir `AncientW` por texto amigável.
5. **Partículas reais**: requer player/renderização temporal com semântica `.part`, não só sequência de imagens Blender.
6. **P1 dependências**: `tem_wall04.bmp` está comprovadamente ausente nas fontes locais (1 face, material 173). Manter exceção documentada; não inventar textura de substituição.
7. **BD/schema**: operações de leitura versionada, migração de schema e rollback devem ser projetadas e testadas posteriormente; **sem Content JSON**.

## 8. Arquivos de auditoria

- `V6_WEB_UI_STATIC_API_AUDIT.json` — contagens, seletores órfãos e ambiguidades;
- `V6_WEB_UI_API_CALL_GRAPH.csv` — rotas/handlers com localização no JavaScript;
- `V6_WEB_UI_API_CALL_GRAPH.csv` e testes web são um mapa de cobertura, não um atestado completo do backend.
