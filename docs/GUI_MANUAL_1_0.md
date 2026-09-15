# PT Asset Tool R14 1.0.0 — Manual da GUI

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

A GUI distingue ações read-only de ações que criam artefactos. Ações mutáveis exigem arm temporário da sessão; esse arm autoriza **workspace/build**, não autoriza modificar client/server.

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
- Editar rare model;
- Gerar SMD/writer em `pt_build`.

## 24 ações expostas pela UI

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
| Editar no Blender | Editar | BUILD workspace |
| Gerar SMD | Build | BUILD writer |
| Doctor | Sistema | RO |

## API local interna

A UI possui endpoints locais para bootstrap, catálogo, asset, entidades, contracts, general census, server reports/editor, jobs, reports, preview, reindex, state/favorites, safety arm, tree compare e actions. Estes endpoints são detalhes de integração da aplicação local; não são uma API remota de produção.

## Encerrar

Use o botão **Parar servidor da UI** em Configurações ou encerre o processo que lançou `pt_asset_gui.py`.
