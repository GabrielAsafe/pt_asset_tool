# PT Asset Tool R14 1.0.0 — Manual da GUI

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Atualização GUI:** 2026-09-21 — Management Legacy, World Closure → Authoring e publish/restore capability-scoped.  
**Regra de precedência:** a seção “Atualização GUI 2026-09-21” no fim deste guia prevalece sobre descrições históricas incompatíveis.

> **Guia rápido.** Para tutoriais completos de todas as funcionalidades alcançáveis pela GUI principal e pelo Particle Editor `.part`, incluindo edição de modelos, textura/Stage0.72, animação, Server/Enrichment e Field SPM/SPP/SPC, use `MANUAL_UTILIZADOR.md`. Este ficheiro fica como mapa resumido das abas e ações.

## Iniciar

A partir de `app/`:

```bash
python3 pt_asset_gui.py
# ou
./pt-asset-gui
```

A GUI é uma aplicação local. O backend CLI é a autoridade para parsing, validação e writers; a GUI não implementa um segundo conjunto de regras.

## Abas

### Catálogo

- inventário e pesquisa do client;
- filtros por categoria/pasta/role/extensão;
- favoritos e vista tabela/galeria;
- preview de imagens suportadas;
- painel de inspeção do asset;
- ações contextuais calculadas por `ui_capabilities.py`.

### Entidades

- catálogo físico Monster/NPC;
- pesquisa por grupo/nome/path;
- evidência de registry e ligações físicas;
- inspeção sem promover guesses a bindings.

### Servidor / Enrichment

- configuração da raiz do servidor;
- server environment/design analysis;
- Asset Enrichment v9 Fix136;
- source contracts / player-class contracts;
- General Asset Census e T5 readiness;
- explorador de bundles Monster/NPC, Field e Item;
- staging do Field Metadata Editor (SPM/SPP/SPC);
- donor server roots apenas read-only.

Arquivos de persistência/log/segurança (`DataServer`, `PostBox`, `WAR`, `LogItemData`, `cpItem.dat`, `BlessCastle.dat`, `BlackUser`, `FuncBox`) não entram na superfície normal de autoria.

### Comparar

Executa tree compare read-only com filtros e hash opcional. Útil para comparar target/donor/snapshots sem copiar nada.

### Tarefas

- mostra jobs long-running;
- recebe prompts de review humano para visual/roundtrip/animação;
- permite responder/cancelar conforme contrato do job;
- jobs ficam sob `pt_build`.

### Relatórios

Descobre recursivamente JSONs de `pt_build`; permite inspecionar evidence sem navegar manualmente pela árvore.

### Ajuda / Guias

Mostra atalhos conceituais e aponta para a documentação distribuída em `docs/`.

### Configurações

Mostra roots resolvidos e glossário. A configuração persistente usa o mesmo mecanismo do CLI `config ...`.

## Safety arm

A GUI distingue ações read-only, BUILD e deploy. `ARM BUILD WRITES` autoriza somente workspace/build. **Publicar no jogo** e **Restaurar último deploy** usam um segundo arm one-shot: digite exatamente `ARM CLIENT DEPLOY`. Esse arm autoriza apenas a transação de bundle verificado; server write continua desabilitado.

Ações read-only comuns:

- Inspecionar;
- Plano de edição;
- Estrutural;
- Bindings;
- Animações/heads/TexLinks/Object Local;
- previews e validations que só geram evidence.

Ações BUILD comuns:

- Importar para Blender;
- Texture Paint Stage0.72;
- Upscale textura para BMP/TGA/PNG/JPG/JPEG em cópia sob `pt_build`;
- Editar rare model;
- Gerar SMD/writer em `pt_build`.

## 27 ações expostas pela UI - (RO deve ser readObject)

| Ação | Grupo | Natureza |
|---|---|---|
| Inspecionar | Analisar | RO |
| Plano de edição | Analisar | RO |
| Estrutural | Validar | RO |
| Bindings | Analisar | RO, long-running |
| Animações | Analisar | RO |
| Cabeças compatíveis | Analisar | RO |
| TexLinks | Analisar | RO |
| Object Local | Analisar | RO |
| Validar visual | Validar | Blender + review humano |
| Roundtrip Model | Validar | copy/build + review |
| Roundtrip Object Local | Validar | Blender + review |
| Roundtrip TexLink | Validar | BUILD temp |
| Stage Preview | Validar | Blender/headless |
| Stage UV Roundtrip | Validar | BUILD temp |
| Stage Geometria | Validar | BUILD temp |
| Animação | Validar | Blender + review |
| Diagnosticar animação | Analisar | Blender + review |
| Importar para Blender | Editar | BUILD workspace |
| Abrir no Blender | Abrir | preview |
| Abrir Stage0.72 | Abrir | preview |
| Texture Paint | Editar | BUILD workspace |
| Upscale textura | Editar | BUILD overlay em `pt_build`; client read-only |
| Editar no Blender | Editar | BUILD workspace |
| Gerar SMD | Build | BUILD writer |
| Publicar no jogo | Publicar | DEPLOY: modelo/texturas modificados; backup, drift gate, atomic write, post-validate e rollback |
| Restaurar último deploy | Publicar | DEPLOY: restore do último APPLIED_VERIFIED; recusa drift desconhecido |
| Doctor | Sistema | RO |

## API local interna

A UI possui endpoints locais para bootstrap, catálogo, asset, entidades, contracts, general census, server reports/editor, jobs, reports, preview, reindex, state/favorites, safety arm, tree compare e actions. Estes endpoints são detalhes de integração da aplicação local; não são uma API remota de produção.

## Encerrar

Use o botão **Parar servidor da UI** em Configurações ou encerre o processo que lançou `pt_asset_gui.py`.

---

## Atualização GUI 2026-09-21 — Management Legacy e Legacy Authoring

Esta seção prevalece sobre descrições antigas da GUI que tratem server write como indisponível em todos os casos.

### Aba Management Legacy

A aba tem duas áreas complementares:

1. **Legacy Authoring / Reescrita Python** — criação/edição real dos formatos promovidos;
2. **World Closure / auditoria Management** — census, correlação e evidência para localizar dependências e targets.

### Legacy Authoring / Reescrita Python

Kinds:

```text
ITEM MONSTER NPC SPM SPP SPC
```

Controles principais:

- `Kind`;
- `EDIT` / `CREATE`;
- path lógico;
- `Abrir / Inspecionar`;
- `Carregar template`;
- JSON spec;
- `Stage em pt_build`;
- `Publicar bundle`;
- `Restaurar bundle`;
- `Status transação`.

Fluxo recomendado:

```text
World Closure/target
→ Inspect
→ Edit/Create
→ ARM BUILD WRITES
→ Stage
→ revisar manifest
→ ARM ASSET DEPLOY
→ Publish
→ validar no runtime
→ Restore, se necessário
```

### World Closure Explorer → Authoring

Selecionar uma linha tenta preencher e inspecionar automaticamente o Authoring:

| Explorer | Authoring |
|---|---|
| Itens / visual closure | `ITEM / EDIT` |
| Maps / SPM | `SPM / EDIT` |
| Monster definition | `MONSTER / EDIT` |
| NPC definition | `NPC / EDIT` |

ITEM usa o path real de OpenItem vindo do census. Targets ambíguos não são escolhidos automaticamente. O spec anterior é resetado antes de carregar outro asset.

### Estados do World Closure

- `CLOSED`: closure esperada encontrada;
- `REVIEW`: revisão/dependência pendente, sem implicar automaticamente erro runtime;
- `RUNTIME_CATALOG_MISSING`: code não encontrado na runtime table source-verificada;
- `AMBIGUOUS`: múltiplos targets;
- `UNRESOLVED`: target não provado.

### Safety arms

`ARM BUILD WRITES` autoriza somente escrita de staging/build em `pt_build`.

`ARM ASSET DEPLOY` é uma autorização separada para publish/restore de bundles suportados; o backend ainda exige hashes, backup, drift gate e verificação pós-write.

Nenhum PriTaTor/NPCManager/ItemEditor.exe é executado pela GUI.
