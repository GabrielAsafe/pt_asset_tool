# Guia do PT Asset Tool / Design Tool

> **Documentação 1.0:** Guia operacional 1.0. Para índice completo veja `README.md`; para comandos exaustivos veja `CLI_REFERENCE_1_0.md`.

Este guia explica como usar a ferramenta no dia a dia, o que cada área prova e como interpretar os resultados sem precisar conhecer os detalhes internos do engine.

## 1. Para que serve

O **PT Asset Tool / Design Tool** é a ferramenta principal para trabalhar com os assets do client Summit Tale e com os formatos 3D compartilhados com o servidor. Ele serve para:

- localizar assets e entender sua função;
- descobrir relações entre SMD, SMB, INX, skeletons e texturas;
- validar formatos físicos antes de editar qualquer coisa;
- abrir e validar conteúdo no Blender;
- gerar candidates e roundtrips dentro de `pt_build`;
- executar gates automáticos de regressão e de release;
- acompanhar relatórios e blockers sem escrever diretamente no client.

A regra mais importante é simples: **o client original é fonte de leitura**. A ferramenta trabalha em cópias e outputs sob `pt_build` até existir autorização explícita de promoção.

## 2. Modelo mental: quatro perguntas diferentes

É fácil confundir “o arquivo abre” com “o asset está pronto para produção”. O Tool separa essas respostas:

| Nível | Pergunta | Exemplo |
|---|---|---|
| Structural | O formato está coerente? | Header, offsets, contagens, blocos e tamanhos fecham? |
| Binding | Sabemos qual skeleton/config pertence ao modelo? | Este SMD usa qual INX/SMB? |
| Visual / Pose | O conteúdo se comporta corretamente no Blender? | Geometria, materiais, rig e animação preservam a pose? |
| Roundtrip / Writer | Conseguimos editar uma cópia e reconstruí-la sem danos colaterais? | Um vértice/material/key alterado volta a ser lido corretamente? |

Um asset pode passar Structural e ainda estar PENDING em Visual. Isso não é contradição; são perguntas diferentes.

## 3. Primeira configuração

### 3.1 Verificar o pacote

Na raiz da distribuição:

```bash
./VERIFY_PACKAGE.sh
```

Resultado esperado:

```text
PACKAGE_VERIFY=PASS
```

### 3.2 Configurar o client

```bash
cd app
python3 pt_asset.py config set-client-root \
  "/path/to/cliente"
```

Ou informe o path diretamente em cada comando com `--client-root`.

### 3.3 Validar o ambiente

```bash
python3 pt_asset.py \
  --client-root "/caminho/cliente" \
  validate environment-auto
```

Esse gate confirma Python, inventário, espaço em disco, hashes de writers certificados, Flatpak/Blender, paths com espaços/acentos, acesso ao client e isolamento de `pt_build`.

## 4. Como abrir a UI

Use o launcher fornecido pelo pacote, normalmente:

```bash
python3 pt_asset_gui.py
```

ou o wrapper `pt-asset-gui`, quando disponível na distribuição.

A UI é apenas uma camada de operação. O backend CLI continua sendo a autoridade para parse, validação e writers.

## 5. O que existe em cada aba

### Catálogo

É o inventário principal do client. Use para procurar por path, categoria, pasta, role, extensão e tags.

Ao selecionar um asset você vê:

- path e tamanho físico;
- classificação semântica;
- family/kind quando o registry conhece o formato;
- binding conhecido;
- capacidades disponíveis;
- ações de inspeção e validação.

**Quando usar:** quando você sabe “qual arquivo” ou “qual tipo de asset” quer investigar.

### Entidades

Agrupa assets por Monster/NPC físico em vez de mostrar somente arquivos isolados.

**Quando usar:** quando a pergunta é “o que compõe este monstro/NPC?” e não “o que contém este `.smd`?”.

### Servidor / Enrichment

Integra a árvore server-side ao Design Tool. A aba mostra:

- `server_root`;
- censo do servidor;
- lifecycle/política de cada família;
- bundles Monster/NPC, Field e OpenItem;
- readiness de integração;
- explorador de bundles com os motivos de REVIEW/BLOCKED.

Ela continua read-only no servidor.

### Comparar

Compara duas árvores físicas por path/tamanho e, opcionalmente, SHA-256.

**Use para:** diferenças entre clients, árvores donor, staging e snapshots.

**Não use para:** decidir automaticamente que “arquivo faltante” deve ser copiado. A decisão semântica continua pertencendo ao bundle/lifecycle.

### Tarefas

Mostra os jobs disparados pela UI e o console em andamento.

### Relatórios

Lista os JSONs produzidos em `pt_build`. São a evidência reproduzível dos gates.

### Ajuda / Guias

Resumo beginner-friendly dos dois produtos e do fluxo combinado.

## 6. Estados que aparecem na ferramenta

- **PASS** — o gate executado passou.
- **FAIL** — o gate executado encontrou uma violação.
- **REVIEW** — existe evidência útil, mas falta decisão ou prova para automatizar.
- **BLOCKED** — uma dependência/contrato obrigatório não está provado.
- **PENDING** — o gate ainda não foi executado.
- **SKIP** — o caso foi deliberadamente pulado pela regra daquele gate.
- **N/A** — o gate não se aplica àquele tipo de asset.

### Runtime review

Alguns reports mostram `visual_runtime_review_required=true` ou `runtime_game_acceptance_pending=true`. Isso significa que os testes automáticos já fizeram o que conseguem fora do jogo, mas a aprovação final ainda exige carregar o resultado no runtime Summit.

## 7. Blender: o que acontece automaticamente

Quando um gate precisa do Blender, o Tool normalmente:

1. importa uma cópia do asset;
2. cria ou identifica o contexto de skeleton;
3. executa uma transformação controlada;
4. salva em `pt_build`;
5. reabre o `.blend` ou o asset reconstruído;
6. compara a pose/estrutura esperada;
7. grava um report.

Não é necessário abrir manualmente o Blender para cada asset durante os gates automáticos.

## 8. Formatos principais

### SMD Model 0.62

Usado para modelos/containers legacy. O Tool conhece families static, rigid e Mixed-Physique.

### SMB

Container da mesma família, frequentemente usado para motion/skeleton/support data. Nem todo SMB é uma animação standalone completa.

### INX

Metadata `smMODELINFO`; é sensível a geração, layout e path. Renomear/mover não é uma operação neutra.

### Stage SMD 0.72

Formato de stage/mapa. No pipeline client-side há corpus físico validado, mas o uso server-side ainda exige cuidado com a variante de `StageArea` do runtime.

### BMP/TGA

Há arquivos padrão e variantes protegidas/nonstandard. O Tool faz seleção e validação por família física, não apenas pela extensão.

## 9. Gates automáticos mais importantes

### `validate environment-auto`

Preflight rápido do ambiente client/Blender.

### `validate integration-regression-auto`

Gate focado em regressões recentes de client + server. É o melhor gate durante desenvolvimento porque evita repetir toda a matriz pesada.

### `validate physical-regression-auto`

Gate físico intermediário mais amplo.

### `validate release-1-auto --resume`

Matriz completa para readiness da 1.0. Pode demorar bastante. `--resume` reutiliza evidência compatível quando o source SHA ainda é exatamente o mesmo.

## 10. Segurança de escrita

Existem três coisas diferentes:

1. **Workspace/build** — criar candidates em `pt_build`.
2. **Client/server source write** — alterar as árvores fonte.
3. **Production publish** — promover um candidate para o runtime real.

Armar workspace/build na UI só libera o item 1. Não libera 2 nem 3.

## 11. Onde procurar um problema

Quando algo falha, comece pelo report do gate. Exemplos:

```text
pt_build/devtest/environment_auto/result.json
pt_build/devtest/integration_regression_auto/result.json
pt_build/devtest/release_1_auto/result.json
```

O objetivo dos gates atuais é registrar o asset, o stage da operação, o erro e o path do report detalhado. Evite investigar por tentativa e erro no source original.

## 12. Fluxo recomendado para uma mudança 3D

1. Localize o asset no Catálogo/Entidades.
2. Confirme Structural e Binding.
3. Gere/edite somente em `pt_build`.
4. Rode o devtest/roundtrip correspondente.
5. Rode `integration-regression-auto` para regressões recentes.
6. Antes de release, rode `release-1-auto --resume`.
7. Faça runtime/game review.
8. Somente depois use o fluxo de promoção/publish/restore aprovado.

## 13. O que a ferramenta deliberadamente não faz

- não considera toda cópia existente no servidor um asset necessário;
- não converte automaticamente persistência do servidor;
- não “corrige” formato desconhecido chutando offsets;
- não transforma REVIEW em PASS por conveniência;
- não autoriza produção só porque um Blender roundtrip passou;
- não inventa um Mixed-Physique físico quando o corpus real não contém um representante.

## 14. Se você está começando

Comece por três coisas: **Catálogo**, **Entidades** e **Servidor / Enrichment**. Use os gates automáticos como checkpoints. Só entre nos scripts internos quando um report apontar exatamente para uma limitação do backend.
