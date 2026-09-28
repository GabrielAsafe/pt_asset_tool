# PT Asset Tool R14 1.0.0 — Manual Completo do Utilizador

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Atualização documental:** 2026-09-21 — Management Legacy + Legacy Authoring Python + World Closure → Authoring.  
**Regra de precedência:** a seção “Atualização operacional 2026-09-21” no fim deste manual prevalece sobre descrições históricas incompatíveis sobre server write/publish.  
**Guia temático:** `../tematicos/LEGACY_MANAGEMENT_AUTHORING.md`.

**Estado:** release 1.0.0 safety-locked.
**Público:** artista técnico, designer, integrador de assets, QA e operador da ferramenta.
**Objetivo:** ensinar todas as funcionalidades alcançáveis pelas interfaces gráficas distribuídas e explicar quando a UI apenas inspeciona, quando cria staging em `pt_build` e quando depende de Blender.

## Como usar este manual

Este é o manual operacional principal. Ele é deliberadamente mais detalhado que o guia rápido. Para a arquitetura ou comandos de automação, use também:

- `GUI_MANUAL_1_0.md` — mapa resumido da GUI principal;
- `../tematicos/GUIA_DESIGN_TOOL.md` — conceitos do Design Tool;
- `../tematicos/GUIA_ASSET_ENRICHMENT.md` — bundles e server/enrichment;
- `../tematicos/GUIA_WORKFLOW_CLIENT_SERVER.md` — fluxo combinado;
- `../tematicos/FIELD_METADATA_EDITOR.md` — SPM/SPP/SPC;
- `CLI_REFERENCE_1_0.md` — referência exaustiva do CLI;
- `../cobertura_funcional/FEATURE_MATRIX_1_0.md` — matriz de capability;
- `../cobertura_funcional/SECURITY_SAFETY_1_0.md` — fronteiras de escrita.

### O que este manual chama de “pela UI”

Há duas interfaces gráficas distribuídas:

1. **GUI principal** (`python3 pt_asset_gui.py` ou `./pt-asset-gui`), com Catálogo, Entidades, Servidor/Enrichment, Comparar, Tarefas, Relatórios, Ajuda/Guias e Configurações.
2. **Particle Editor** (`python3 pt_part_ui.py ...`), UI auxiliar de staging para ficheiros `.part`.

Este manual cobre ambas. Uma função só é descrita como editável se existir um botão/editor real na UI atual; não transformamos funcionalidades CLI em funcionalidades gráficas por suposição.

---

## 1. O que é o PT Asset Tool

O PT Asset Tool é uma aplicação local para catalogar, inspecionar, comparar, validar e trabalhar com assets do client e com bundles relacionados do Summit Server. A instalação 1.0 é **fresh**: estado operacional, registry, certifications, caches, drafts e evidência gerada nascem localmente em `app/pt_build` e não são distribuídos como resultados de outra máquina.

O programa combina:

- catálogo físico do client;
- índice semântico de assets;
- inspeção de modelos, texturas e ficheiros de suporte;
- comparação de duas árvores de assets;
- censo Monster/NPC;
- workflows Blender;
- validações de Model0.62 e Stage0.72;
- edição guardada de workflows certificados;
- geração de outputs em `pt_build`;
- relatórios e histórico de tarefas pela GUI;
- registry gerado automaticamente a partir do client atual;
- análise server-side e Asset Enrichment;
- staging controlado de metadata de Field;
- editor gráfico auxiliar de partículas `.part`.


## 1.1 Modelo mental: o que cada etapa prova

A ferramenta não trata “asset funciona” como uma única resposta. Ela separa níveis de evidência:

| Etapa | Pergunta que responde | Modifica o client? |
|---|---|---|
| **Catálogo / Inspect** | “Que arquivo é este e com que outros arquivos ele se relaciona?” | Não |
| **Structural** | “A estrutura conhecida do formato é coerente?” | Não |
| **Binding** | “Que INX/SMB/root fornece skeleton e animação para este modelo?” | Não |
| **Visual** | “O transporte para Blender preserva visualmente geometria/textura?” | Não |
| **Roundtrip** | “Conseguimos reconstruir/modificar uma cópia sem alterar bytes não autorizados?” | Não; output em `pt_build` |
| **Writer certificado** | “Existe um writer autorizado para este workflow específico?” | Output em `pt_build` |
| **Publish/deploy** | “Podemos substituir o bundle editado no client com rollback?” | Sim, apenas pelo workspace bundle verificado e com arm explícito |

Por isso uma linha com muitos `PENDING` não significa que o arquivo esteja danificado. Significa apenas que aquelas certificações ainda não foram executadas/registradas para aquele asset.

### Estados usados nas tabelas

- `PASS`: gate/certificação passou.
- `FAIL`: gate/certificação falhou.
- `SKIP`: revisão foi deliberadamente pulada.
- `PENDING`: ainda não há resultado registrado.
- `N/A`: aquele teste não se aplica àquele tipo de asset.
- `CONTEXT`: existe contexto técnico de animação, mas ainda não há certificação visual final.

O próprio programa também explica esses termos:

```bash
python3 pt_asset.py explain statuses
python3 pt_asset.py explain bindings
python3 pt_asset.py explain structural
python3 pt_asset.py explain visual
python3 pt_asset.py explain roundtrip
```

---

### Regra de segurança central

O **client original é tratado como fonte read-only por padrão**. Edição/build continua isolada em `pt_build`. A única exceção operacional é o deploy/restauro explícito de um **workspace bundle verificado**.

- `ARM BUILD WRITES` permite editar/buildar em `pt_build`;
- `ARM CLIENT DEPLOY` é uma autorização separada, one-shot, para **Publicar no jogo** ou **Restaurar último deploy**;
- antes da escrita, a app revalida provenance e drift de modelo, texturas e contexto INX/SMB;
- cria backup SHA-256 de todo o bundle;
- só escreve ficheiros realmente modificados, com replace atómico e verificação pós-write;
- qualquer falha aciona rollback dos ficheiros já escritos;
- server write continua fora deste fluxo.

---

# 2. Estrutura da distribuição

A partir da raiz do repositório/pacote, a aplicação operacional fica em `app/`. Uma instalação fresh não contém inventory/certification/evidence de outra execução. Estrutura relevante:

```text
pt_asset_tool/
├── VERIFY_PACKAGE.sh
├── SNAPSHOT_SHA256SUMS.txt
├── docs/
├── vendor/
└── app/
    ├── pt_asset.py
    ├── pt_asset_gui.py
    ├── pt-asset-gui
    ├── pt_part_ui.py
    ├── pt_asset_tool/
    │   ├── blender/
    │   ├── legacy_runtime/
    │   └── ui_static/
    ├── data/
    │   └── reference/        # seeds/reference knowledge, não runtime state
    ├── dev_tests/
    ├── tests/
    └── pt_build/             # criado localmente quando necessário
```

Depois de configurar/encontrar o client, o registry runtime é criado em:

```text
app/pt_build/state/asset_registry/
├── asset_inventory.json
├── inx_physical_pairing.csv
└── registry_meta.json
```

Outros estados locais podem aparecer em:

```text
app/pt_build/state/certifications/
app/pt_build/state/character_profiles/
app/pt_build/state/development_evidence/
app/pt_build/state/pt_asset_app_config.json
```

`pt_build` é deliberadamente separado do client/server. Apagar `pt_build` apaga apenas estado/output local da ferramenta; na próxima execução os índices necessários são reconstruídos.

---

# 3. Requisitos

## 3.1 Obrigatórios

- Linux;
- Python 3;
- acesso de leitura ao client;
- acesso de escrita à pasta da aplicação para `pt_build` e configuração local;
- browser moderno para a GUI.

Verifique o Python:

```bash
python3 --version
```

## 3.2 Blender

Blender é **opcional para o uso geral**. Catálogo, registry, server/enrichment, comparação, muitos audits e a GUI funcionam sem Blender. Workflows explicitamente Blender (preview 3D, validação visual, animação, import/edit/paint e preview `.part`) requerem Blender disponível.

O comando padrão esperado é:

```text
flatpak run --filesystem=home org.blender.Blender
```

Para verificar:

```bash
flatpak info org.blender.Blender
```

Se usar outro Blender, defina antes de executar a aplicação:

```bash
export PT_BLENDER_COMMAND="/caminho/para/blender"
```

Exemplo com Blender instalado no PATH:

```bash
export PT_BLENDER_COMMAND="blender"
```

---

# 4. Instalação

## 4.1 Verificar o pacote

Na raiz do projeto/pacote:

```bash
./VERIFY_PACKAGE.sh
```

Esse gate verifica a baseline estática do pacote. `pt_build` é estado runtime e não pertence ao snapshot estático.

## 4.2 Entrar na aplicação e confirmar versão

```bash
cd app
python3 pt_asset.py --version
```

Resultado esperado:

```text
1.0.0
```

## 4.3 Testar a instalação

```bash
python3 pt_asset.py status
python3 pt_asset.py smoke
python3 pt_asset.py validate environment-auto
```

Sem Blender instalado, `environment-auto` pode continuar `PASS`: o check Blender aparece como opcional/SKIP e `blender_ready=false`. Workflows Blender permanecem indisponíveis até instalar/configurar Blender.

## 4.4 Ajuda geral

```bash
python3 pt_asset.py --help
```

---

# 5. Configurar o client

A aplicação precisa saber onde está a pasta `cliente`.

## 5.1 Ver configuração atual

```bash
python3 pt_asset.py config show
```

Se o client ainda não estiver resolvido, o status será `WARN`.

## 5.2 Configurar o client de forma persistente

```bash
python3 pt_asset.py config set-client-root "/caminho/para/Summit Tale Client Full/cliente"
```

Exemplo:

```bash
python3 pt_asset.py config set-client-root \
  "/home/user/Área de Trabalho/summit/Summit Tale Client Full/cliente"
```

Depois:

```bash
python3 pt_asset.py config show
```

Resultado esperado:

```json
{
  "status": "PASS",
  "configured_client_root": ".../cliente",
  "resolved_client_root": ".../cliente",
  "resolved_client_root_source": "PERSISTENT_CONFIG"
}
```

## 5.3 Limpar configuração persistente

```bash
python3 pt_asset.py config clear-client-root
```

## 5.4 Usar variável de ambiente

Também é possível:

```bash
export PT_CLIENT_ROOT="/caminho/para/cliente"
```

## 5.5 Usar client explicitamente em comandos do core

Vários comandos aceitam:

```bash
python3 pt_asset.py --client-root "/caminho/para/cliente" ...
```

## 5.6 Registry fresh gerado automaticamente

Depois que o `client_root` é resolvido, a aplicação cria/revalida o registry a partir do client físico atual. Para conferir:

```bash
python3 pt_asset.py registry status
```

O output esperado aponta para `pt_build/state/asset_registry`, com `runtime_state=true` e `package_payload=false`. Para forçar reconstrução:

```bash
python3 pt_asset.py registry rebuild
```

Também é seguro apagar apenas esse estado e pedir o status novamente:

```bash
rm -rf pt_build/state/asset_registry
python3 pt_asset.py registry status
```

Isso **não modifica o client**. O bootstrap volta a percorrer o client e recria inventory/pairing/meta.

---

# 6. Teste inicial obrigatório

Antes de usar a GUI ou Blender, execute os quatro comandos abaixo.

```bash
python3 pt_asset.py --version
python3 pt_asset.py config show
python3 pt_asset.py status
python3 pt_asset.py smoke
```

Depois:

```bash
python3 pt_asset.py doctor
```

---

# 7. Entendendo `status`, `smoke` e `doctor`

## 7.1 `status`

```bash
python3 pt_asset.py status
```

Verifica:

- client root;
- features principais;
- dependências de runtime;
- hashes dos writers certificados;
- disponibilidade dos módulos principais.

O ideal é:

```text
"status": "PASS"
```

Campos importantes:

```text
client_root
client_root_source
certified_writer_hashes_valid
runtime_dependency_checks
features
client_source_write_default
```

`client_source_write_default` deve permanecer:

```text
false
```

## 7.2 `smoke`

```bash
python3 pt_asset.py smoke
```

O smoke atual cobre caminhos reais usados pela aplicação:

```text
app_status_pass
certified_writer_hashes_valid
runtime_dependencies_present
client_root_resolved
pt_build_writable
catalog_bootstrap
asset_registry_bootstrap
ui_capability_contract
ui_preview_pipeline
ui_javascript_contract
support_file_inspection_contract
blender_edit_workspace_contract
ui_reports_recursive_contract
tree_compare_import
monster_npc_import
blender_launcher_available
```

O resultado principal deve ser:

```text
"status": "PASS"
```

### Importante

`blender_launcher_available` é diagnóstico. O smoke pode validar a aplicação mesmo que o Blender não esteja disponível, desde que os checks obrigatórios passem.

O smoke declara:

```text
"client_modified": false
```

Ele percorre o client em leitura. O único write probe temporário é criado e apagado em `pt_build`.

## 7.3 `doctor`

```bash
python3 pt_asset.py doctor
```

Verifica uma camada mais profunda:

- inventário;
- pairing;
- registros canónicos;
- partition Physique/static;
- scripts auxiliares;
- client;
- Python;
- Blender.

Ao final procure:

```text
doctor_check=PASS
```

---

# 8. Abrir a GUI

Com o client configurado:

```bash
python3 pt_asset.py ui
```

ou:

```bash
python3 pt_asset.py gui
```

ou:

```bash
./pt-asset-gui
```

A GUI escolhe automaticamente uma porta local livre.

Também pode iniciar sem abrir o browser:

```bash
python3 pt_asset.py ui --no-browser
```

Ou especificar porta:

```bash
python3 pt_asset.py ui --port 33103
```

## Segurança da GUI

A GUI é local/loopback. O bind remoto está desativado nesta versão.

Use:

```text
127.0.0.1
```

Não espere poder publicar a GUI em `0.0.0.0` para acesso remoto.

---

# 9. Visão geral da GUI

A interface tem cinco áreas principais:

1. **Catálogo**
2. **Comparar**
3. **Tarefas**
4. **Relatórios**
5. **Configurações**

---


## 9.1 Mapa completo das ações contextuais do asset

Os botões do painel direito são calculados por asset. **Não é erro um botão não aparecer**: a capability layer suprime ações que não são aplicáveis ao `kind/family` daquele ficheiro.

| Botão | O que faz | Escrita | Blender / review |
|---|---|---|---|
| **Inspecionar** | inspeção física + semântica | RO | não |
| **Plano de edição** | mostra canais editáveis/writers/gates | RO | não |
| **Estrutural** | valida invariantes do formato | RO/report | não |
| **Bindings** | procura skeleton/Physique/root candidates | RO/report | não |
| **Animações** | lista motions associados | RO | não |
| **Cabeças compatíveis** | lista heads/face parts verificadas para o mesmo contexto | RO | não |
| **TexLinks** | inspeciona materiais/layers/TexLink | RO | não |
| **Object Local** | inspeciona transforms/keys object-local | RO | não |
| **Validar visual** | abre no Blender e pede avaliação humana | `pt_build` evidence | Blender + review |
| **Roundtrip Model** | reconstrói cópia controlada e pede review | `pt_build` | possivelmente Blender + review |
| **Roundtrip Object Local** | valida transforms/animação local | `pt_build` evidence | Blender + review |
| **Roundtrip TexLink** | valida chain/UV/material roundtrip | `pt_build` | backend/Blender conforme fluxo |
| **Stage Preview** | valida transporte Stage0.72 | `pt_build` evidence | Blender |
| **Stage UV Roundtrip** | valida UV Stage0.72 | `pt_build` | workflow de roundtrip |
| **Stage Geometria** | valida geometria Stage0.72 | `pt_build` | workflow de roundtrip |
| **Animação** | avaliação visual de uma motion | `pt_build` evidence | Blender + review |
| **Diagnosticar animação** | compara source e armature Blender | `pt_build` evidence | Blender + review |
| **Importar para Blender** | cria workspace editável/paint/animation | `pt_build` | Blender |
| **Abrir no Blender** | preview rare Model0.62 | `pt_build`/temp | Blender |
| **Abrir Stage0.72** | preview do stage | `pt_build`/temp | Blender |
| **Texture Paint** | workspace Stage0.72 para pintar uma layer/TexLink | `pt_build` | Blender |
| **Upscale textura** | cria cópia 2x/3x/4x de BMP/TGA/PNG/JPG/JPEG | `pt_build/texture_upscale` | não; Real-ESRGAN é opcional |
| **Editar no Blender** | workspace guardado de rare-model suportado | `pt_build` | Blender |
| **Gerar SMD** | writer guardado do rare-model suportado | `pt_build` | usa workspace validado |
| **Doctor** | diagnóstico do sistema | RO/report | não |

### Natureza dos botões

- **RO**: lê client/server e pode produzir report em `pt_build`, mas não cria candidato editado.
- **BUILD**: cria workspace, draft ou candidato somente em `pt_build`; requer **Armar workspace/build**.
- **Interactive**: a tarefa pode parar aguardando `PASS / Sim`, `FAIL / Não` ou `SKIP / Pular` na consola.
- **Long-running**: acompanhe em **Tarefas**; não feche o backend enquanto estiver RUNNING.

## 9.2 O que a GUI consegue realmente criar/editar

Para evitar falsas expectativas:

| Conteúdo | UI atual | Resultado |
|---|---|---|
| Modelo Model0.62 suportado | workspace Blender genérico | edição/paint em `pt_build`; geração final depende de writer/capability |
| Rare model certificado específico | editar + **Gerar SMD** | SMD candidato em `pt_build` |
| Stage0.72 | preview, roundtrips e Texture Paint | workspace/drafts/evidence em `pt_build` |
| Textura de modelo/stage | via workspace Blender ligado ao asset | textura/cópia em `pt_build`; não altera BMP/TGA fonte |
| BMP/TGA/PNG/JPG avulso | preview/inspeção + **Upscale textura** | cópia redimensionada em `pt_build`; não há pintura genérica nem overwrite do source |
| `.part` | Particle Editor auxiliar | draft textual estruturado + verify + preview Blender |
| Field SPM | editor server staging | draft SPM em `pt_build/server_field_editor` |
| Field SPP | editor de record por índice | draft SPP em `pt_build/server_field_editor` |
| Field SPC | clone-patch ADD_NPC conhecido | draft SPC em `pt_build/server_field_editor` |
| Item/OpenItem | census/explorer read-only | **não há criação/edição de item pela UI 1.0** |
| Monster/NPC server definition | census/explorer read-only | não há writer server pela UI |
| Client/server target | nunca | publish direto não é exposto |

Se uma função não aparece nessa tabela como editável, este manual não inventa um tutorial de escrita.

# 10. Catálogo

O catálogo percorre fisicamente o client configurado.

Ele oferece:

- pesquisa textual;
- filtro por categoria;
- filtro por role;
- filtro por extensão;
- favoritos;
- filtros rápidos;
- tabela;
- galeria;
- preview para tipos suportados;
- anotação local;
- ações de backend compatíveis com cada asset.

## 10.1 Filtros rápidos

Existem botões para:

```text
UI
Personagens
Monstros
NPCs
Itens
Mapas
Efeitos
```

## 10.2 Extensões

O dropdown de extensões inclui os tipos encontrados no client.

Arquivos sem extensão aparecem como:

```text
Sem extensão (N)
```

e não como apenas `(N)`.

## 10.3 Tabela e galeria

Use:

- **Tabela** para navegar muitos arquivos;
- **Galeria** para assets visuais.

A preferência é guardada localmente no browser.

### Paginação

Use **Anterior** e **Próxima** no rodapé do catálogo quando a pesquisa tiver mais de uma página. Trocar filtro/busca volta a paginação para a primeira página.

## 10.4 Selecionar um asset

O painel de detalhes pode mostrar:

```text
Path
Category
Role
Size
Physical hint
Family
Kind
Binding
Capabilities
```

Nem todo arquivo possui um `Asset` semântico completo. Ficheiros como INX, SMB, WAV e outros support files podem ser apenas arquivos físicos ou registros de suporte.

Isso é válido: `Inspecionar` continua disponível.

## 10.5 Anotações

É possível registrar:

- override de categoria;
- override de role;
- tags;
- notas;
- favorito.

Esses dados pertencem ao estado local da GUI, não ao client.

## 10.6 Reindexar

Use **Reindexar** quando:

- novos arquivos aparecerem no client;
- arquivos forem removidos;
- quiser atualizar contagens e filtros físicos.

A reindexação atualiza o **catálogo físico**.

O catálogo físico e o registry são derivados do client atual. Se a árvore física mudou, a camada de registry verifica a origem/freshness e reconstrói o estado em `pt_build/state/asset_registry` quando necessário. Não existe mais um snapshot histórico obrigatório em `data/asset_registry`.

---

# 11. Preview de imagens

Para imagens suportadas, o detalhe exibe preview.

O pipeline atual trata BMP/TGA através dos adaptadores da própria aplicação, incluindo variantes do client que não devem ser enviadas diretamente a um decoder genérico.

Se um preview não puder ser gerado, a GUI deve exibir um fallback legível e o servidor pode responder com:

```text
PREVIEW_NOT_AVAILABLE
PREVIEW_UNSUPPORTED
PREVIEW_DECODE_FAILED
PREVIEW_READ_FAILED
```

Um erro de preview não deve alterar o arquivo original.

---

# 12. Capabilities: por que alguns botões aparecem e outros não

A GUI é deliberadamente conservadora.

Ela só oferece uma ação quando o backend considera o asset compatível.

Isso evita situações como:

```text
Bindings em SMD estático
Motions sem contexto de animação
Structural em BMP/TGA sem validator
Upscale em formato não suportado ou sem Pillow
TexLink Roundtrip em asset sem preflight compatível
```

## Exemplos

### SMD Stage0.72

Pode oferecer:

```text
Inspecionar
Abrir Stage0.72
Texture Paint
Stage Preview
Stage UV Roundtrip
Stage Geometria
```

### SMD Model0.62 estático

Pode oferecer:

```text
Inspecionar
Estrutural
TexLinks
Object Local
```

e, quando o preflight físico permitir:

```text
Roundtrip TexLink
```

### SMD Model0.62 rigid Physique

Pode oferecer:

```text
Inspecionar
Estrutural
Bindings
Animações
TexLinks
```

dependendo dos bindings realmente resolvidos.

### BMP/TGA/support files

Normalmente:

```text
Inspecionar
Preview, quando suportado
```

Não deve aparecer um validator estrutural genérico se ele não existir.

---

# 13. Inspeção de assets pela CLI

## 13.1 Asset semântico

```bash
python3 pt_asset.py asset inspect \
  "char/tmABCD/at_dragon.smd" \
  --physical
```

O output pode incluir:

- asset ID;
- family;
- kind;
- configs;
- motions;
- binding skeleton;
- root models;
- paths físicos.

## 13.2 Support file

INX:

```bash
python3 pt_asset.py asset inspect \
  "char/tmABCD/A004.inx" \
  --physical
```

SMB:

```bash
python3 pt_asset.py asset inspect \
  "char/monster/decoy/decoy-ani.smb" \
  --physical
```

WAV com espaço:

```bash
python3 pt_asset.py asset inspect \
  "wav/Effects/Player/Archer/dead 1.wav" \
  --physical
```

Para support files, é normal o output indicar:

```text
registry_asset: false
```

Isso não significa erro.

---

# 14. Listar assets

```bash
python3 pt_asset.py assets list
```

Com limite:

```bash
python3 pt_asset.py assets list --limit 20
```

Por categoria:

```bash
python3 pt_asset.py assets list --category CHARACTER --limit 50
```

Por família:

```bash
python3 pt_asset.py assets list --family SMD_MODEL_062_STATIC
```

Por extensão:

```bash
python3 pt_asset.py assets list --ext smd
```

Somente assets visuais:

```bash
python3 pt_asset.py assets list --visual-only --limit 50
```

---

# 15. Families

```bash
python3 pt_asset.py families
```

Use para ver as famílias semânticas conhecidas pelo registry.

---

# 16. Bindings

Um **binding** não é simplesmente “algo anexado ao personagem”. É a relação técnica comprovada entre:

```text
modelo SMD
   ↓
configuração INX
   ↓
skeleton / motions SMB
   ↓
root model, quando o SMD é apenas um componente
```

Essa relação é necessária para saber qual skeleton deve deformar um modelo rigid Physique e quais motions podem ser aplicadas sem adivinhação.

Modos principais:

- `SELF_CONTAINED`: o próprio modelo/config resolve diretamente seu INX/SMB de animação;
- `ROOT_SKELETON_BOUND`: o modelo reutiliza um root/skeleton verificado;
- `CONFIG_ONLY`: há config, mas o root único não está suficientemente provado; animação fica fail-closed;
- `NONE`: não há binding conhecido ou ele não se aplica ao asset.

Cabeças/rostos podem ser peças modulares, mas a compatibilidade só é aceita quando a evidência de binding mostra que compartilham o mesmo root de animação.

Listagem:

```bash
python3 pt_asset.py bindings --limit 50
```

O final da saída imprime uma legenda dos modos.

Filtrar:

```bash
python3 pt_asset.py bindings --category CHARACTER --limit 50
```

### O que significa `bindings --discover`

Use somente em um **SMD rigid Physique** que esteja `CONFIG_ONLY` e para o qual você queira investigar se existe evidência suficiente para resolver um root/skeleton único:

```bash
python3 pt_asset.py bindings --discover \
  "char/caminho/modelo.smd"
```

O comando examina evidência estrutural/configuração e grava apenas diagnóstico/cache em `pt_build`. Ele **não modifica o client** e não força um binding quando a evidência é ambígua.

Para ver o significado direto no programa:

```bash
python3 pt_asset.py explain bindings
```

---

# 17. Motions e animação

Antes de abrir animação, confirme quais motions o INX realmente declara:

```bash
python3 pt_asset.py asset motions \
  "char/caminho/personagem.smd"
```

Se aparecer:

```text
animation_binding_ready=False
```

a ferramenta não considera seguro escolher um SMB/motion automaticamente.

## `--motion` versus `--load-actions`

São opções diferentes:

- `--motion ATTACK` escolhe qual Action fica **ativa** no viewport do Blender;
- `--load-actions selected` cria somente a Action escolhida;
- `--load-actions core` cria o subconjunto principal de states;
- `--load-actions all` cria todas as motions ativas encontradas no INX.

Mesmo com `--load-actions all`, somente `selected_action` fica tocando no viewport. As outras Actions estão disponíveis no **Dope Sheet → Action Editor** do Blender. O programa agora imprime `selected_action`, `actions_loaded` e `available_actions` antes de abrir o Blender.

Exemplo:

```bash
python3 pt_asset.py validate animation \
  "char/caminho/personagem.smd" \
  --motion ATTACK \
  --load-actions all
```

## Cabeças / personagens modulares

Antes de usar `--head auto`, descubra quais partes de cabeça/rosto estão realmente verificadas para o mesmo root:

```bash
python3 pt_asset.py asset heads \
  "char/caminho/body.smd" \
  --limit 100
```

Depois você pode usar:

```text
--head auto
--head none
--head "char/.../cabeca.smd"
--head-tier auto
--head-tier base
--head-tier a
--head-tier b
--head-tier c
--head-tier d
--head-tier t
```

Se não existirem candidatos verificados, `--head auto` não inventa uma cabeça. A saída informa `ASSEMBLED_HEAD=NONE` e a quantidade de candidatos encontrados.

Na GUI de desenvolvimento, animações interativas podem ser conduzidas pela aba **Tarefas**: escolha motion/load-actions/cabeça e responda `PASS / FAIL / SKIP` quando o console pedir.

---

# 18. Diagnóstico de animação

```bash
python3 pt_asset.py diagnose animation \
  "char/caminho/personagem.smd" \
  --motion ATTACK
```

Diagnosticar origem da motion:

```bash
python3 pt_asset.py diagnose motion-source \
  "char/caminho/personagem.smd" \
  --motion STAND
```

Diagnosticar segmento:

```bash
python3 pt_asset.py diagnose motion-segment \
  "char/caminho/personagem.smd" \
  --motion STAND
```

---

# 19. Object Local

**Object-local** é uma vertical específica de `SMD_MODEL_062_STATIC`: em vez de vertices serem deformados por Physique/skeleton, objetos inteiros possuem transforms locais (posição/rotação/escala e, em alguns casos, affine legado).

Portanto não use este comando em modelos `SMD_MODEL_062_RIGID_PHYSIQUE`. Para esses use `bindings`, `asset motions` e as ferramentas de animação.

Inspecionar um static compatível:

```bash
python3 pt_asset.py asset object-local \
  "char/caminho/static.smd"
```

A inspeção responde perguntas como:

- quantos objetos existem;
- se algum objeto realmente muda de transform;
- que canais são animados;
- relação parent/child;
- se há um caso affine/segmentado que exige tratamento especial.

Validar visualmente no Blender:

```bash
python3 pt_asset.py validate object-local \
  "char/caminho/static.smd" \
  --fps 30
```

A GUI só oferece o validator quando o preflight físico encontra animação object-local suportada.

---

# 20. TexLinks

TexLinks representam relações de material/texture stages e seus links de UV dentro de Model0.62.

### Inspeção genérica

Use em qualquer Model0.62 suportado:

```bash
python3 pt_asset.py asset texlinks \
  "char/caminho/modelo.smd"
```

Esse é o comando para responder “quantas camadas este material tem e como estão ligadas?”.

### `validate texlinks`

Apesar do nome histórico, este **não é um validator genérico de qualquer TexLink**. É um gate visual especializado para uma fonte multilayer comprovada com exatamente duas camadas.

Se um modelo comum tiver `max_layers=1`, a recusa é esperada. Use `asset texlinks` para inspeção genérica.

```bash
python3 pt_asset.py validate texlinks \
  "char/caminho/modelo_two_layer.smd"
```

### TexLink roundtrip

É mais restrito ainda: prova que o writer de duas camadas consegue alterar/regravar uma cópia sem perder a semântica autorizada.

```bash
python3 pt_asset.py validate texlink-roundtrip \
  "char/caminho/modelo_two_layer.smd"
```

Não force esse gate em modelos single-layer.

---

# 21. Stage0.72

## 21.1 Abrir preview no Blender

```bash
python3 pt_asset.py view stage072 \
  "Field/Ricarten/village-2.smd"
```

O preview é um workflow de visualização.

## 21.2 Validar preview

```bash
python3 pt_asset.py validate stage072-preview \
  "Field/Ricarten/village-2.smd"
```

## 21.3 UV roundtrip

```bash
python3 pt_asset.py validate stage072-roundtrip \
  "Field/castle/castle.smd"
```

Delta customizado:

```bash
python3 pt_asset.py validate stage072-roundtrip \
  "maps/caminho/stage.smd" \
  --uv-delta 0.03125
```

## 21.4 Geometry roundtrip

```bash
python3 pt_asset.py validate stage072-geometry-roundtrip \
  "maps/caminho/stage.smd"
```

Exemplo:

```bash
python3 pt_asset.py validate stage072-geometry-roundtrip \
  "maps/caminho/stage.smd" \
  --delta-world 64
```

## 21.5 Texture Paint

```bash
python3 pt_asset.py paint stage072 \
  "Field/Ricarten/village-2.smd" \
  --stage 0
```

CLI aceita stages de `0` a `7`.

Para resetar o workspace privado:

```bash
python3 pt_asset.py paint stage072 \
  "maps/caminho/stage.smd" \
  --stage 0 \
  --reset
```

Na GUI, o seletor atual é deliberadamente mais restrito e usa stage 0 ou 1.

---

# 22. Workspaces Blender

Todo artefacto Blender **editável** deve permanecer sob:

```text
pt_build/blender_edits/
```

A convenção é:

```text
pt_build/
└── blender_edits/
    └── <workflow>/
        └── <asset-descritivo>/
            └── ...
```

Exemplo:

```text
pt_build/blender_edits/
└── rare_model/
    └── char__tmABCD__at_dragon/
```

Outro:

```text
pt_build/blender_edits/
└── stage072_texture_paint/
    └── maps__Ricarten__Field_01/
        └── stage_0/
```

O workspace pode conter:

```text
workspace_info.json
*.blend
source/
editable/
builds/
logs/
```

`workspace_info.json` identifica:

- workflow;
- asset;
- caminho do workspace;
- se é editável;
- política de segurança;
- `client_modified: false`.

---

# 23. Rare-model

O workflow guardado de edição rare-model atual é restrito aos assets certificados.

## 23.1 Visualizar rare model

```bash
python3 pt_asset.py view rare-model \
  "char/tmABCD/at_dragon.smd"
```

## 23.2 Abrir workspace de edição

```bash
python3 pt_asset.py edit rare-model \
  "char/tmABCD/at_dragon.smd"
```

Para reconstruir o workspace:

```bash
python3 pt_asset.py edit rare-model \
  "char/tmABCD/at_dragon.smd" \
  --reset
```

## 23.3 Gerar SMD guardado

```bash
python3 pt_asset.py write rare-model \
  "char/tmABCD/at_dragon.smd"
```

Output customizado:

```bash
python3 pt_asset.py write rare-model \
  "char/tmABCD/at_dragon.smd" \
  --output "pt_build/meu_output.smd"
```

O comando **não substitui automaticamente o asset no client**.

---

# 24. Armar ações de workspace/build na GUI

Na GUI, ações que criam/editam `pt_build` ficam bloqueadas inicialmente.

Clique:

```text
Armar workspace/build
```

Digite exatamente:

```text
ARM BUILD WRITES
```

O arm dura 15 minutos.

Ele permite ações como:

```text
Texture Paint
Editar no Blender
Gerar SMD
```

Ele **não** autoriza deploy no client. Para publicar/restaurar, a própria ação solicitará separadamente `ARM CLIENT DEPLOY`; essa autorização é consumida por uma única transação.

Você pode desarmar o arm de build antes do prazo clicando novamente no botão.

---

# 25. Tarefas

A GUI executa comandos em jobs.

Status possíveis:

```text
QUEUED
RUNNING
CANCELLING
CANCELLED
PASS
FAIL
ERROR
```

Cada job possui log em:

```text
pt_build/ui_jobs/
```

A aba Tarefas mostra:

- comando;
- asset;
- PID;
- status;
- retorno;
- tail do console.

## Cancelar

Use:

```text
Cancelar tarefa
```

O cancelamento encerra o grupo de processos do job, incluindo Blender/tool children quando possível.

Um cancelamento intencional deve terminar como:

```text
CANCELLED
```

e não como `FAIL`.

---

# 26. Relatórios

A aba **Relatórios** busca arquivos JSON recursivamente dentro de:

```text
pt_build/
```

Isto inclui relatórios em subpastas.

Relatórios muito grandes podem ser recusados pela UI para evitar leitura excessiva.

---

# 27. Comparar duas árvores de assets

## GUI

Abra a aba:

```text
Comparar
```

Informe:

- árvore esquerda;
- árvore direita.

Opções:

- SHA-256;
- case sensitive;
- differences only;
- extensões;
- categoria;
- substring de path.

## Teste de sanidade

Compare o client contra ele mesmo.

Resultado esperado:

```text
only_left = 0
only_right = 0
different = 0
```

## CLI simples

```bash
python3 pt_asset.py compare trees \
  --left "/caminho/A" \
  --right "/caminho/B" \
  --differences-only
```

## Comparação com SHA-256

```bash
python3 pt_asset.py compare trees \
  --left "/caminho/A" \
  --right "/caminho/B" \
  --hash \
  --differences-only
```

## Somente SMD

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --ext smd \
  --differences-only
```

## Múltiplas extensões

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --ext smd \
  --ext inx,inf \
  --differences-only
```

## Categoria

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --category CHARACTER \
  --differences-only
```

## Path

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --path-contains monster \
  --differences-only
```

## Glob

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --include-glob 'char/*' \
  --exclude-glob '*effect*'
```

## Output

Default:

```text
pt_build/tree_compare_v0120.json
```

Customizado:

```bash
python3 pt_asset.py compare trees \
  --left A \
  --right B \
  --output pt_build/minha_comparacao.json
```

A ferramenta recusa output dentro das próprias árvores de origem.

---

# 28. Monster/NPC

O censo agrupa arquivos físicos e dependências de monstros/NPCs. Ele serve para responder “quais entidades existem, que modelos/configs/SMBs/texturas pertencem a cada pasta e quanta evidência técnica já existe?”.

Ele **não autoriza writers** só porque uma pasta se chama Monster/NPC.

## GUI

Use **Censo Monster/NPC**. Na linha de desenvolvimento atual, a aba **Entidades** também apresenta cada pasta como uma entidade visual com preview e contexto do registry.

## CLI

```bash
python3 pt_asset.py audit monster-npc-census \
  --output pt_build/monster_npc_census.json
```

Na primeira execução, se `semantic_asset_census_current.json` ainda não existir, ele é criado automaticamente por uma varredura read-only. O antigo erro que exigia `--refresh-census` manualmente foi corrigido.

Para forçar uma atualização porque o corpus mudou:

```bash
python3 pt_asset.py audit monster-npc-census \
  --refresh-census \
  --output pt_build/monster_npc_census.json
```

---

# 29. Certificações

Listar:

```bash
python3 pt_asset.py certification list
```

Últimas:

```bash
python3 pt_asset.py certification list --latest
```

Filtrar asset:

```bash
python3 pt_asset.py certification list \
  --asset "char/caminho/modelo.smd"
```

Registrar uma avaliação:

```bash
python3 pt_asset.py certification record \
  "char/caminho/modelo.smd" \
  --test VISUAL_ASSET \
  --layer HUMAN_VISUAL \
  --result PASS \
  --notes "Visualmente aprovado"
```

Resultados válidos:

```text
PASS
FAIL
SKIP
```

---

# 30. Validações com avaliação humana

Alguns validators abrem Blender e depois perguntam se o resultado visual está correto. Exemplos:

```text
validate visual
validate roundtrip
validate object-local
validate animation
diagnose animation
```

Na release inicial auditada essas perguntas exigiam o terminal. Na linha de desenvolvimento atual, a GUI mantém o **mesmo processo CLI** aberto e mostra botões `PASS / FAIL / SKIP` na aba **Tarefas** quando o console chega a uma pergunta `[y]es / [n]o / [s]kip`.

Isto evita duplicar a lógica do validator na interface: a GUI apenas fornece a resposta humana ao backend original.

---

# 31. Validação estrutural

Pergunta que responde:

> “Este asset respeita as invariantes conhecidas do seu formato/família antes de confiarmos em Blender ou writer?”

Ela pode verificar, conforme a família:

- estrutura e contagens serializadas;
- objetos/vertices/faces;
- referências Physique;
- relações esperadas de material/config;
- invariantes específicas do adapter.

Ela **não** prova que o asset ficou bonito no Blender ou no jogo e não é um editor.

```bash
python3 pt_asset.py validate structural \
  "char/tmABCD/MfbC01.smd"
```

Não existe validator estrutural genérico para todo BMP/TGA/support file; nesses casos a GUI não deve oferecer o botão.

Mais contexto:

```bash
python3 pt_asset.py explain structural
```

---

# 32. Validação visual

Pergunta que responde:

> “Nosso caminho de import/transporte para Blender representa corretamente este asset?”

```bash
python3 pt_asset.py validate visual \
  "char/tmABCD/MfbC01.smd"
```

A validação abre um preview e pede revisão humana de geometria e, quando aplicável, textura/material.

**Ela não é a prova de que conseguimos editar e regravar o asset.** A prova de alteração controlada é um **roundtrip/writer gate**.

Mais contexto:

```bash
python3 pt_asset.py explain visual
```

---

# 33. Roundtrip Model0.62 estático

Pergunta que responde:

> “Conseguimos ler, reconstruir/modificar uma cópia e regravar o asset preservando tudo que não foi autorizado a mudar?”

```bash
python3 pt_asset.py validate roundtrip \
  "char/caminho/static.smd"
```

O workflow usa uma alteração controlada (`witness`) justamente para provar que o pipeline realmente transportou uma modificação, em vez de somente copiar o arquivo.

```bash
python3 pt_asset.py validate roundtrip \
  "char/caminho/static.smd" \
  --witness-strength 0.08
```

Outputs permanecem em `pt_build`. Este gate não transforma todos os Model0.62 em assets automaticamente editáveis em produção.

Mais contexto:

```bash
python3 pt_asset.py explain roundtrip
```

---

# 34. Auditorias avançadas

O backend ainda contém auditorias de engenharia e certificação, como:

```text
audit physique
audit object-local
audit object-local-corpus
audit texlink-corpus
audit texlink-semantics
audit stage072-corpus
audit stage072-stagearea
audit stage072-normals
audit stage072-textures
audit rare-outliers
audit rare-support
audit rare-rigid-context
audit rare-rigid-binding
audit rare-rigid-preview
audit rare-rigid-geometry
audit rare-rigid-geometry-roundtrip
audit rare-rigid-normal-roundtrip
audit rare-rigid-extent-roundtrip
audit rare-rigid-multibone
audit rare-rigid-multibone-roundtrip
audit rare-rigid-edit-workflow
```

Exemplo:

```bash
python3 pt_asset.py audit physique \
  --output pt_build/physique.json
```

Essas auditorias são avançadas. Para uso normal, prefira:

```text
status
smoke
doctor
ui
assets
asset
compare trees
bindings
view
edit
paint
write
validate
diagnose
certification
audit monster-npc-census
```

---

# 35. Instalar entrada de desktop

A distribuição inclui:

```text
install_desktop_entry.sh
```

Execute:

```bash
./install_desktop_entry.sh "/caminho/para/pt_asset_tool"
```

O script cria/atualiza uma entrada `.desktop` **local para o utilizador**, apontando para o launcher da pasta informada. O objetivo é permitir abrir a GUI pelo menu de aplicações sem digitar o comando no terminal.

Ele **não instala arquivos no client**, não altera assets e não configura sozinho o client root. Depois procure a aplicação no menu do desktop.

Para ver a explicação no programa:

```bash
python3 pt_asset.py explain desktop-entry
```

---

# 36. Troubleshooting

## 36.1 `CLIENT_ROOT_NOT_FOUND`

Execute:

```bash
python3 pt_asset.py config set-client-root "/caminho/correto/cliente"
```

Depois:

```bash
python3 pt_asset.py status
```

## 36.2 `asset/file not found`

Confirme o path e a caixa:

```bash
find "$PT_CLIENT_ROOT" -iname 'nome-do-arquivo*'
```

O resolver suporta paths reais do client, mas paths incorretos continuam inválidos.

## 36.3 `ACTION_NOT_SUPPORTED_FOR_ASSET`

A ação não é compatível com a family/kind do asset.

Selecione outro asset ou use apenas as capabilities exibidas.

## 36.4 `BUILD_WRITE_NOT_ARMED`

Na GUI:

1. clique em **Armar workspace/build**;
2. digite `ARM BUILD WRITES`;
3. execute novamente.

## 36.5 Blender não abre

Teste:

```bash
flatpak info org.blender.Blender
```

ou:

```bash
$PT_BLENDER_COMMAND --version
```

Se necessário:

```bash
export PT_BLENDER_COMMAND="blender"
```

Depois:

```bash
python3 pt_asset.py doctor
```

## 36.6 Preview não aparece

Teste outro BMP/TGA conhecido.

Se persistir, veja o terminal onde a UI foi aberta e o job/log correspondente.

A API diferencia:

```text
PREVIEW_NOT_AVAILABLE
PREVIEW_UNSUPPORTED
PREVIEW_DECODE_FAILED
PREVIEW_READ_FAILED
```

## 36.7 Um job ficou preso

Na GUI:

```text
Cancelar tarefa
```

Se o processo externo não encerrar, feche a UI e verifique:

```bash
ps aux | grep -i blender
```

## 36.8 `doctor_check=FAIL`

Não use edição/build até entender o check que falhou.

Os nomes de checks apontam diretamente para:

- arquivo ausente;
- índice ausente;
- client ausente;
- Blender ausente;
- dependência de runtime ausente.

---

# 37. Fluxo recomendado de utilização

Para uma nova instalação:

```bash
python3 pt_asset.py --version

python3 pt_asset.py config set-client-root \
  "/caminho/para/cliente"

python3 pt_asset.py config show
python3 pt_asset.py status
python3 pt_asset.py smoke
python3 pt_asset.py doctor
python3 pt_asset.py ui
```

Na GUI:

1. conferir contagem do catálogo;
2. testar pesquisa;
3. testar TGA/BMP preview;
4. inspecionar SMD;
5. inspecionar INX;
6. inspecionar SMB;
7. inspecionar WAV;
8. executar Doctor;
9. comparar client consigo mesmo;
10. executar Monster/NPC census;
11. testar Blender somente depois;
12. armar build somente para workflows de edição.

---

# 38. Checklist antes de editar no Blender

Antes de `edit`, `paint` ou `write`:

- [ ] `status` = PASS
- [ ] `smoke` = PASS
- [ ] `doctor_check=PASS`
- [ ] client root correto
- [ ] Blender disponível
- [ ] asset possui capability correspondente
- [ ] `pt_build` está gravável
- [ ] não existe job ativo do mesmo asset
- [ ] entende que o output não será automaticamente publicado no client

---

# 39. Checklist depois de uma edição

- [ ] confirmar workspace em `pt_build/blender_edits`
- [ ] conferir `workspace_info.json`
- [ ] confirmar que o client original não mudou
- [ ] executar validator correspondente
- [ ] revisar output em `pt_build`
- [ ] guardar relatório do job
- [ ] registrar certificação se aplicável

---

# 40. Encerrar a GUI

Use:

```text
Parar servidor da UI
```

A página mostrará que o servidor foi parado.

Também é possível interromper o terminal com `Ctrl+C`.

---

# 41. Publicar um asset editado no jogo, backup e restore

Para Model0.62 static/rigid importado por **Importar para Blender**, a GUI pode fechar o roundtrip com **Publicar no jogo**. O workspace continua sendo a fonte da edição; o client só é tocado na transação final.

1. edite e salve o `.blend`/texturas do workspace;
2. clique **Publicar no jogo**;
3. digite exatamente `ARM CLIENT DEPLOY`;
4. escolha `full` para modelo + texturas alteradas ou `textures` para somente texturas;
5. acompanhe o job até `APPLIED_VERIFIED`.

A preparação detecta o bundle pelo `authoring_manifest.json` e `texture_overlay_report.json`: SMD, texturas realmente associadas e dependências INX/SMB. INX/SMB são **preserve-only**: entram no backup e drift gate, mas não são reescritos.

BMP/TGA protegido é reconstruído no container runtime original e validado por roundtrip. O modelo só entra como `MODIFIED` quando o writer saved-Blender static/rigid constrói um candidate cujo verificador dá PASS e observa edição real. Se o writer não suportar o asset, `full` bloqueia; `textures` permanece disponível para edição exclusivamente de textura.

Cada transação fica em `pt_build/deploy_bundles/<asset>/<transaction-id>/` com `transaction.json`, `backup/`, `staged/` e `evidence/`. Antes do primeiro write a app revalida todos os hashes; depois faz replace atómico e valida o SHA de cada destino. Falha de escrita/hash/validação pós-write dispara rollback automático.

Após `APPLIED_VERIFIED`, a GUI oferece **Restaurar último deploy**. O restore também exige `ARM CLIENT DEPLOY` e recusa drift desconhecido.

CLI equivalente:

```bash
python3 pt_asset.py deploy workspace-prepare char/npc/TN-003/TN-003.smd
python3 pt_asset.py deploy workspace-publish char/npc/TN-003/TN-003.smd --confirm "APPLY CLIENT BUNDLE"
python3 pt_asset.py deploy workspace-history char/npc/TN-003/TN-003.smd
python3 pt_asset.py deploy workspace-restore-latest char/npc/TN-003/TN-003.smd --confirm "RESTORE CLIENT BUNDLE"
```

Mantenha também backups externos para operações manuais fora da aplicação; o histórico interno cobre apenas transações gerenciadas pela própria app.

---

# 42. Resumo das funcionalidades

| Área | Função |
|---|---|
| Status | readiness, writers e dependências |
| Smoke | teste integrado read-only |
| Doctor | diagnóstico profundo |
| Config | client root persistente |
| Catálogo | indexação física e filtros |
| Preview | BMP/TGA suportados |
| Inspect | asset semântico ou support file |
| Bindings | skeleton/Physique |
| Motions | contexto de animação |
| TexLinks | análise de materiais/stages |
| Object Local | transforms |
| Compare | comparação de árvores |
| Monster/NPC | censo e triagem |
| Blender View | preview de Stage0.72/rare |
| Blender Edit | workspace guardado |
| Texture Paint | workspace privado Stage0.72 |
| Texture Upscale | cópia 2x/3x/4x em overlay `pt_build`, com manifest e source read-only |
| Write | output guardado em `pt_build` |
| Deploy bundle | publica modelo/texturas alterados com backup, drift gate, write atómico, validação e rollback |
| Restore bundle | restaura o último deploy conhecido se não houver drift |
| Jobs | execução, logs e cancelamento |
| Reports | consulta recursiva de JSONs |
| Certification | registro de PASS/FAIL/SKIP |

---

# 43. Regra final para o utilizador

Se a GUI não oferecer um botão para um asset, **não assuma que é um bug automaticamente**.

Primeiro confirme a family/kind com:

```bash
python3 pt_asset.py asset inspect "PATH" --physical
```

As capabilities são intencionalmente conservadoras.

Se o botão aparece e o backend recusa por incompatibilidade conhecida, isso é um bug de capability e deve ser reportado.

Se um botão de build escrever fora de `pt_build`, pare o teste e reporte imediatamente.

# 44. Tutorial completo — Servidor / Enrichment

A aba **Servidor / Enrichment** é uma superfície read-only/plan-only para o server root, com uma única exceção controlada: o **Field Metadata Editor** pode criar drafts em `pt_build`; ele nunca escreve no servidor.

## 44.1 Configurar a raiz do servidor

1. Abra **Servidor / Enrichment**.
2. No campo **Raiz do servidor**, informe a pasta `Servidor`.
3. Clique **Salvar raiz**.
4. Confira o estado mostrado ao lado do título.

O valor usa o mesmo mecanismo do CLI `config set-server-root`. Limpar o campo e salvar remove a configuração persistente.

### O que nunca entra na superfície normal de autoria

A UI exclui deliberadamente persistência/logs/estado operacional como `DataServer`, `PostBox`, `WAR`, `LogItemData`, `cpItem.dat`, `BlessCastle.dat`, `BlackUser` e `FuncBox`. Ver um path desses num inventário não transforma o ficheiro em asset editável.

## 44.2 Validar ambiente server

Clique **Validar ambiente**. A tarefa executa o equivalente a `validate server-environment-auto` e verifica root, leitura, separação de client/server/build e precondições do analisador.

Use isto sempre que:

- trocar de server root;
- mover a instalação;
- receber uma árvore de servidor de outra máquina;
- um gate server falhar antes do parsing de bundles.

## 44.3 Analisar Asset Enrichment

Clique **Analisar Asset Enrichment**. O gate agregado executa inventário e análises de Monster/NPC, Field e OpenItem. Aguarde a tarefa terminar e volte à aba Servidor para atualizar os cards/exploradores.

Interpretação:

- **PASS/RESOLVED**: a cadeia observada fecha para aquele gate;
- **REVIEW**: há evidência, mas falta decisão/contrato/prova;
- **BLOCKED**: dependência obrigatória ausente ou ambígua;
- nenhum desses estados autoriza server write.

## 44.4 Validar Client + Server

Clique **Validar Client + Server** para rodar a regressão de integração. Use depois de mudanças em parsers, registry, contract logic, server bundle logic ou assets de teste que cruzam client/server.

## 44.5 Inventário físico server

Clique **Inventário físico server** para classificar a árvore e contar:

- número de ficheiros;
- bytes;
- candidatos de asset;
- caminhos hard-excluded de estado/log/persistência.

É diagnóstico, não migration plan.

## 44.6 Plano v9 e grafo v9

**Gerar plano v9** executa o Asset Enrichment v9 em modo de planejamento e grava resultado sob `pt_build/enrichment_vendor`.

**Grafo de dependências v9** constrói o grafo de referências/gaps. Use para entender o porquê de uma dependência, não para copiar automaticamente tudo que estiver ausente.

A GUI **não expõe `apply` do vendor**. Isso é intencional.

# 45. Tutorial — Source Contracts, donors e 10 classes

A mesma aba possui **Asset Contracts · Source Evidence**. Essa área serve para comparar o source atual com um source de referência e, opcionalmente, donors read-only.

## 45.1 Salvar fontes

Preencha:

- **Source Summit** — source atual;
- **Source EU de referência** — source usado como evidência comparativa;
- **Donor clients read-only** — um `LABEL=PATH` por linha;
- **Donor servers read-only** — um `LABEL=PATH` por linha.

Clique **Salvar fontes**. Donors continuam fontes somente leitura.

## 45.2 Ler contratos do source

Clique **Ler contratos do source** para extrair/atualizar evidência de símbolos, sound IDs, relations, job capacity e referências conhecidas.

Use esse relatório para responder “o source chama isto?” antes de concluir que um ficheiro donor precisa ser recuperado.

## 45.3 Auditar 10 classes

Clique **Auditar 10 classes** para cruzar skills/classes, source runtime, áudio, motion contracts e assets descobertos. O card mostra contagens como PRESENT_TARGET, RECOVERABLE_REFERENCE, CONFLICT e MISSING_UNKNOWN.

Isso é auditoria; não materializa assets.

## 45.4 Agregar 10 classes (staging)

Clique **Agregar 10 classes (staging)** para gerar overlay/manifest em `pt_build`.

A agregação pode classificar entradas em manter target, recuperar, escolher variante, conflito ou missing. Ela não escreve no client.

## 45.5 Censo geral (plan-only)

Clique **Censo geral (plan-only)** para cruzar roots funcionais, dependências runtime/model/particle/field, manifests, source e donors.

Depois use o **Explorador do censo geral**:

1. escolha lado `Client`, `Server` ou ambos;
2. pesquise por path/evidência/donor/motivo;
3. filtre decisão;
4. filtre família;
5. clique **Atualizar lista**.

`RECOVERABLE_REACHABLE_CANDIDATE` significa que um root funcional alcança o asset e existe candidato donor. Donor-only, manifest-only, conflitos e evidência fraca continuam em REVIEW.


<!-- PT_SERVER_ENRICHMENT_CENSUS_GUIDE_2026-09-21 -->

### 45.5.1 Preflight operacional e acompanhamento do Censo geral

Antes de depender do resultado, use o bloco **Antes de executar o Censo geral**. Ele mostra Client root, Server root, Source Summit, Source EU de referência, donors client/server, blockers/warnings, freshness do último relatório e o comando CLI equivalente montado a partir da configuração persistente.

Estados principais:

- `BLOQUEADO`: falta root obrigatório ou um donor salvo deixou de existir;
- `PRONTO PARA EXECUTAR`: configuração válida e nenhum relatório atual;
- `EM EXECUÇÃO`: job iniciado pela própria GUI;
- `RELATÓRIO ATUAL`: roots e conjunto de donors coincidem com o relatório;
- `RELATÓRIO DESATUALIZADO`: client/server/source/reference ou donors mudaram.

Donors são opcionais para executar, mas zero donors reduz a autoridade de recovery. Portanto `Recoverable = 0` com nenhum donor configurado não prova que não exista conteúdo recuperável.

**CLI versus GUI:** `--source-root`, `--reference-source-root`, `--donor-client` e `--donor-server` passados manualmente no terminal valem para aquela execução. Para a GUI reutilizar os mesmos valores, preencha-os em **Asset Contracts · Source Evidence** e clique **Salvar fontes**.

A GUI acompanha em **Tarefas & Console** apenas jobs iniciados por ela. Um `audit general-asset-census` iniciado em outro terminal aparece na UI somente quando terminar e gravar `pt_build/general_asset_census/result.json`.

O comando genérico é:

```bash
cd app
python3 pt_asset.py \
  --client-root '/caminho/cliente' \
  --server-root '/caminho/Servidor' \
  audit general-asset-census \
  --source-root '/caminho/SourceCode' \
  --reference-source-root '/caminho/source-eu' \
  --donor-client 'PT_EU=/caminho/pt-eu/client' \
  --donor-server 'PT_EU_SERVER=/caminho/pt-eu/server'
```

A própria GUI exibe o comando exato para os roots salvos na máquina.

### REVIEW no Explorador de bundles

Ao selecionar Monster/NPC, Field ou OpenItem em REVIEW/BLOCKED, a lateral mostra separadamente: resumo operacional, motivo, o que falta, onde verificar e próximas ações seguras. Ações apenas navegam para Catálogo, Censo geral, Field editor ou lookup de item; selecionar a linha continua read-only e nenhuma dessas ações publica no servidor.

## 45.6 Agregar Summit completo (staging)

Clique **Agregar Summit completo (staging)** para materializar o superset de staging em `pt_build`, usando client/server/donors configurados.

Antes de confiar num resultado antigo, observe o estado de freshness. Se client/server roots ou contagens mudaram, a GUI pode marcar o manifest como stale e ele deve ser refeito.

# 46. Tutorial — Explorador de bundles Monster/NPC, Field e OpenItem

No **Explorador de bundles**, escolha o tipo e clique/filtre as linhas. A lateral explica a cadeia e os motivos do estado.

## 46.1 Monster / NPC

A vista mostra:

- definição server;
- model lógico;
- INX;
- presença server/client;
- ZHOON;
- reasons de REVIEW/BLOCKED.

Fluxo recomendado:

1. encontre a entidade no explorer;
2. leia model/INX e blockers;
3. vá para **Entidades** ou **Catálogo**;
4. valide SMD/SMB/INX/texturas no Design Tool;
5. volte ao server bundle para fechar placement/spawn/quest/shop conforme aplicável;
6. faça runtime review no jogo fora da ferramenta.

A aba não cria Monster/NPC server definitions.

## 46.2 Field

A vista mostra basename, stage selecionado e companions SPP/SPC/SPM.

Se aparecer `AMBIGUOUS_STAGE_BASENAME`, a ferramenta se recusa a escolher silenciosamente um stage. Resolva a ambiguidade antes de tratar o bundle como fechado.

Quando selecionar uma linha Field, os botões **Abrir SPM/SPP/SPC** são habilitados apenas para companions existentes.

## 46.3 OpenItem

A vista mostra:

- definição OpenItem;
- item code;
- basis da identidade;
- ZHOON;
- reasons como `DUPLICATE_CODE` ou `CODE_NOT_PARSED`.

**Importante:** item code server-side não é automaticamente filename do modelo ou ícone no client.

### A UI cria items?

**Não.** A 1.0 não expõe writer de OpenItem/item definition, shop/drop ou criação completa de item. O tutorial suportado é de **auditoria e rastreio**:

1. encontre o OpenItem;
2. valide code e colisões;
3. rastreie catálogo/model/drop/icon no client;
4. verifique quem usa o code (drop/shop/evento);
5. corrija por fluxo específico fora da UI somente quando houver writer/contrato autorizado.

# 47. Tutorial completo — Field Metadata Editor (SPM / SPP / SPC)

O editor é staging only. Para criar um draft:

1. execute/anexe um relatório de Fields;
2. no Explorador de bundles escolha **Fields**;
3. selecione um Field;
4. clique **Armar workspace/build** e confirme `ARM BUILD WRITES`;
5. abra SPM, SPP ou SPC;
6. faça a alteração permitida;
7. crie o draft;
8. inspecione draft + manifest em `pt_build/server_field_editor`;
9. valide runtime externamente antes de qualquer promoção manual.

O arm dura 15 minutos e só autoriza escrita em `pt_build`.

## 47.1 SPM — spawn/atores

1. Clique **Abrir SPM**.
2. A UI mostra path, SHA-256, encoding, quantidade de atores e último draft.
3. Edite o texto no campo **Conteúdo SPM**.
4. Clique **Criar draft SPM em pt_build**.

O writer preserva encoding detectado e estilo de newline. Ele não prova gameplay de spawn/timing; valide runtime.

## 47.2 SPP — start points

O layout canónico suportado é 200 records × 12 bytes (`state`, `x`, `z`).

1. Clique **Abrir SPP**.
2. Observe os start points ativos listados.
3. Informe **Índice** de 0 a 199.
4. Informe `State`, `X` e `Z`.
5. Clique **Criar draft SPP em pt_build**.

A UI altera um record por draft e preserva tamanho/ordem. Layout legacy incompatível permanece bloqueado.

## 47.3 SPC — NPC fixo / merchant placement

A UI **não cria um SPC sintético do zero**. Ela faz clone-patch de um record ADD_NPC conhecido.

1. Clique **Abrir SPC**.
2. Escolha um **Template ADD_NPC** existente.
3. Escolha um **Slot destino** blank.
4. Defina `Nome record`.
5. Defina `Model INI`.
6. Defina `Server NPC`.
7. Defina X/Y/Z, AX/AY/AZ e State.
8. Clique **Criar draft SPC clone em pt_build**.

Placement não cria shop/quest/comportamento. Esses contratos continuam na definição server NPC/lógica server-side.

# 48. Tutorial — Comparar árvores

A aba **Comparar** é read-only.

1. Informe **Árvore esquerda** e **Árvore direita**.
2. Opcionalmente filtre extensões (`smd, inx, smb, bmp`).
3. Opcionalmente filtre categoria.
4. Opcionalmente informe `Path contém`.
5. Mantenha **Mostrar/exportar somente diferenças** quando quiser um diff operacional.
6. Marque **Comparar SHA-256** quando tamanho/path não for suficiente.
7. Marque **Paths case-sensitive** apenas quando essa distinção fizer parte da análise.
8. Clique **Comparar árvores**.
9. Acompanhe o job e o resultado.

JSON/CSV/Markdown ficam em `pt_build`. Nenhum ficheiro é copiado entre as árvores.

# 49. Tutorial — Tarefas e revisão humana

A aba **Tarefas** mostra os jobs long-running.

Para validações interativas:

1. inicie `Validar visual`, `Roundtrip Model`, `Roundtrip Object Local`, `Animação` ou `Diagnosticar animação`;
2. abra a consola do job;
3. quando aparecer uma pergunta de review, observe o Blender/resultados;
4. responda **PASS / Sim**, **FAIL / Não** ou **SKIP / Pular**;
5. aguarde estado final PASS/FAIL/ERROR/CANCELLED.

Use **Cancelar tarefa** quando precisar interromper um job ativo. Cancelar não publica outputs no target.

# 50. Tutorial — Relatórios

A aba **Relatórios** descobre JSONs recursivamente dentro de `pt_build`.

Use **Censo Monster/NPC** para disparar um censo físico e **Atualizar** para recarregar a lista. Ao abrir um report, trate paths/status/evidence como diagnóstico da execução atual; reports antigos podem estar stale depois de trocar roots.

# 50.1 Tutorial — Ajuda / Guias

A aba **Ajuda / Guias** não executa writers. Ela resume o Design Tool, Asset Enrichment, fluxo combinado e estados PASS/REVIEW/BLOCKED/PENDING, além do runbook de release. Use-a como orientação rápida; para detalhes operacionais permaneça neste manual.

# 51. Tutorial — Configurações, Doctor e safety arm

## 51.1 Doctor

Clique **Executar Doctor** no topo para diagnosticar configuração/runtime. O job é read-only.

## 51.2 Reindexar

Clique **Reindexar** depois de adicionar/remover assets fisicamente no client. O catálogo e registry são derivados do client atual; o estado semântico runtime fica em `pt_build/state/asset_registry`.

## 51.3 Armar workspace/build

1. Clique **Armar workspace/build**.
2. Digite exatamente `ARM BUILD WRITES`.
3. Clique **Armar por 15 min**.
4. O botão passa a indicar sessão armada.
5. Clique novamente para desarmar antes do timeout, se desejar.

Isso autoriza **somente** ações que escrevem em `pt_build`. Não habilita client/server write.

# 52. Tutorial — editar um modelo pela GUI principal

A possibilidade de edição depende do asset. Se **Importar para Blender** não aparece, a capability layer não considera esse asset elegível para o workspace genérico.

## 52.1 Preparar

1. Catálogo → encontre o `.smd`.
2. Selecione-o e leia `Family`, `Kind` e `Binding`.
3. Rode **Plano de edição**.
4. Quando aplicável, rode **Estrutural**, **Bindings**, **Animações**, **TexLinks** e/ou **Object Local**.
5. Arme workspace/build.

## 52.2 Importar para Blender

Clique **Importar para Blender**. A UI pede:

- **LOD**: `auto`, `high`, `default`, `low`;
- **Animações no workspace**: `all`, `selected`, `none`;
- **Motion inicial** quando animations != none;
- **Workspace**: `paint` ou `animation`;
- se houver múltiplos INX/model-info, escolha o path exato.

### Qual modo escolher

- `paint`: workspace estável para editar/pintar;
- `animation`: preview com Actions/motions carregadas.

Edite no `.blend`/workspace criado em `pt_build`. Fechar/salvar Blender não substitui o `.smd` do client.

## 52.3 Como transformar uma edição em SMD

A GUI principal **não oferece um writer genérico “salvar qualquer Model0.62 de volta”**. Para assets com writer explícito, o botão correspondente aparece. No rare-model certificado suportado, use **Editar no Blender** e depois **Gerar SMD**. Para outras famílias, siga o `Plano de edição`/build dispatcher e só use writers que o backend classificar como certificados/candidate.

# 53. Tutorial — alterar textura/imagem

## 53.1 Imagem BMP/TGA/PNG/JPG avulsa

A GUI principal consegue localizar, classificar e fazer preview de imagens suportadas. Ela **não possui um editor de pintura genérico tipo Photoshop**, mas possui a ação **Upscale textura** para BMP/TGA/PNG/JPG/JPEG. O upscale sempre cria uma cópia fora do client.

### Tutorial — upscale de uma textura pela UI

1. abra **Catálogo** e selecione a imagem;
2. confirme no preview/path que é o asset esperado;
3. arme **workspace/build**;
4. clique **Upscale textura**;
5. escolha escala `2`, `3` ou `4`;
6. escolha `lanczos` para upscale local determinístico ou `realesrgan` quando o backend AI estiver instalado;
7. se o path for UI/login/font/cursor/atlas, a GUI mostra um aviso adicional; só confirme quando quiser testar conscientemente um consumidor que pode usar recortes em pixels;
8. acompanhe o job em **Tarefas & Console**;
9. o resultado fica em `pt_build/texture_upscale/runs/<run-id>/overlay/` e o `manifest.json` fica no mesmo run;
10. valide visualmente/in-game antes de qualquer promoção externa.

A aplicação recusa output/manifest dentro do client, não sobrescreve output existente sem autorização explícita e valida o container redimensionado antes de publicar o ficheiro de staging. TGA/BMP protegidos são reconstruídos na família de header compatível com os adapters atuais.

### Dependências do upscale

- `Pillow`: necessário para Lanczos e para decode/encode do pipeline; é opcional para o resto do PT Asset Tool;
- `realesrgan-ncnn-vulkan`: opcional, necessário apenas para o backend AI.

Veja o estado em `python3 pt_asset.py status`, campo `optional_capabilities.texture_upscale`.

Para batch/CLI e detalhes de safety, veja `docs/tematicos/TEXTURE_UPSCALE_PIPELINE.md`.

## 53.2 Textura associada a Model0.62

Quando **Importar para Blender** está disponível:

1. selecione o modelo;
2. inspecione **TexLinks**;
3. arme workspace/build;
4. **Importar para Blender**;
5. escolha `open_mode=paint`;
6. altere/pinte a textura no workspace;
7. salve somente no workspace/output `pt_build`;
8. valide visual/roundtrip antes de qualquer promoção externa.

## 53.3 Textura de Stage0.72

1. selecione o Stage0.72;
2. rode **Stage Preview**;
3. rode **Stage UV Roundtrip** se estiver mexendo em UV/material;
4. arme workspace/build;
5. clique **Texture Paint**;
6. informe `Stage TexLink` de 0 a 7;
7. pinte no workspace Blender;
8. rode novamente preview/roundtrip/geometry conforme a mudança.

Nenhum desses fluxos altera a textura fonte no client automaticamente.

# 54. Tutorial — animação e cabeças

## 54.1 Listar motions

Selecione um Model0.62 rigid com binding conhecido e clique **Animações**.

## 54.2 Validar uma motion

Clique **Animação** e responda aos prompts:

1. motion (`STAND`, `WALK`, `ATTACK` etc.);
2. actions: `all` (recomendado), `selected` ou `core`;
3. para CHARACTER, cabeça `auto`, `none` ou path exato;
4. tier `auto`, `base`, `a`, `b`, `c`, `d` ou `t`.

Depois responda à review humana pela consola da tarefa.

## 54.3 Diagnosticar animação

Use **Diagnosticar animação** quando a motion parece errada e você quer comparar source vs armature Blender. O fluxo pede motion/actions e também usa a consola de review.

## 54.4 Cabeças compatíveis

Quando o asset é CHARACTER e existem candidates do mesmo contexto, **Cabeças compatíveis** lista as peças verificadas. Isso não significa que qualquer head encontrada por nome seja válida; a UI usa o registry/binding.

# 55. Tutorial — Stage0.72 completo

Para um SMD `kind=SMD_STAGE_072`, a UI oferece apenas capacidades próprias de stage. Fluxo recomendado:

1. **Plano de edição**;
2. **Abrir Stage0.72** para preview;
3. **Stage Preview** para gate de transporte;
4. **Stage UV Roundtrip** se a mudança tocar UV/material;
5. **Stage Geometria** se a mudança tocar vertices/faces/estrutura;
6. **Texture Paint** para edição de textura em workspace;
7. acompanhe outputs/reports em `pt_build`;
8. não publique no target a partir da GUI.

# 56. Tutorial — rare Model0.62 com writer exposto

A UI é deliberadamente estreita. `Abrir no Blender` pode aparecer para rare models conhecidos; `Editar no Blender` e **Gerar SMD** aparecem somente no escopo que o backend autoriza.

Fluxo quando os três botões existem:

1. **Abrir no Blender** e confira a representação;
2. **Plano de edição** e validators aplicáveis;
3. arme workspace/build;
4. **Editar no Blender**;
5. faça a alteração e salve o `.blend`;
6. **Gerar SMD**;
7. inspecione o candidato/reports em `pt_build`;
8. execute validações/roundtrips relevantes antes de qualquer publish externo.

# 57. Tutorial — Object Local e TexLink

## Object Local

**Object Local** inspeciona semântica de transforms. Se o backend detectar animação local suportada, pode aparecer **Roundtrip Object Local**. Use o roundtrip para provar que transforms/keys sobrevivem ao pipeline controlado; não use como licença para inventar keys inexistentes.

## TexLink

**TexLinks** mostra relações material/layer. **Roundtrip TexLink** só aparece quando o preflight físico reconhece shape compatível (incluindo multilayer suportado). Rode-o antes/depois de alterações de material/UV.

# 58. Particle Editor `.part` — UI auxiliar completa

A edição `.part` não está embutida na GUI principal. Inicie a UI auxiliar a partir de `app/`:

```bash
python3 pt_part_ui.py --client-root "/caminho/cliente"
```

Por padrão ela serve em `http://127.0.0.1:8765/`. Para outro build root/porta:

```bash
python3 pt_part_ui.py \\
  --client-root "/caminho/cliente" \\
  --build-root "pt_build/devtest" \\
  --port 8765
```

## 58.1 Selecionar e inspecionar

1. use a busca à esquerda;
2. selecione um `.part`;
3. confira `parse_status`, `authoring_status`, EOL e SHA source;
4. a tabela lista ocorrências por selector, tipo e valor.

## 58.2 Fazer uma alteração staging

Somente ocorrências marcadas editáveis recebem input/botão **Stage**.

1. altere o valor;
2. clique **Stage**;
3. a UI cria nova revision do draft em build root;
4. o client original permanece intacto.

## 58.3 Verificar draft

Clique **Verify draft** e leia o JSON de diff/verificação. Faça isso depois de cada conjunto de mudanças.

## 58.4 Preview sem Blender

Clique **Build Preview Plan** para construir um plano semântico determinístico e conferir referências/texturas/complexidade.

## 58.5 Preview Blender

Clique **Generate Blender .blend**. Requer Blender disponível e produz `.blend`/PNGs em `pt_build/devtest/effect_preview/blender`.

A certificação é `BLENDER_PREVIEW_APPROXIMATE`: serve para iteração visual; não prova equivalência perfeita de timing/billboard/event semantics do runtime.

# 59. O que a UI 1.0 deliberadamente NÃO faz

Para manter a fronteira de segurança clara:

- não publica automaticamente no client;
- não escreve no server root;
- não cria OpenItem/item completo;
- não cria Monster/NPC server definition;
- não cria shop/quest automaticamente ao editar SPC;
- não possui editor de pintura genérico para BMP/TGA/PNG/JPG avulso; possui upscale seguro para cópias em `pt_build`;
- não oferece writer genérico para qualquer SMD;
- não converte donor gap em recovery automático sem reachability/proveniência;
- não trata Blender preview como prova de bytes/runtime;
- não habilita vendor `apply` pela GUI.

Essa ausência é parte do design fail-closed, não uma função escondida.

# 60. Checklist prático por objetivo

## Quero descobrir o que um ficheiro é

Catálogo → buscar → selecionar → **Inspecionar**.

## Quero editar um modelo

Catálogo → modelo → **Plano de edição** → validators → armar → **Importar para Blender** ou workflow rare específico → validar → candidate em `pt_build`.

## Quero pintar textura de um stage

Stage0.72 → Stage Preview/UV → armar → **Texture Paint** → escolher layer 0–7 → pintar → revalidar.

## Quero editar/upscalar uma imagem solta

Para redimensionar/upscalar uma imagem suportada, selecione-a no Catálogo e use **Upscale textura**. Para pintura/retouch livre, use uma ferramenta externa ou o workspace Blender quando a textura pertence a um Model0.62/Stage0.72; a GUI não sobrescreve a fonte.

A GUI 1.0 apenas preview/inspeciona. Use ferramenta externa e depois reintroduza o resultado por um workflow certificado; não existe editor genérico interno.

## Quero criar/editar item

A UI 1.0 audita OpenItem/code/model/icon/dependências, mas não cria item. Use o explorer para descobrir a cadeia e só faça autoria por um writer/fluxo específico quando existir.

## Quero colocar um NPC fixo num Field

Servidor/Enrichment → analisar → Explorer `Fields` → selecionar field → armar → **Abrir SPC** → clone ADD_NPC → preencher paths/posição → draft → runtime review.

## Quero mudar spawn do Field

Explorer `Fields` → **Abrir SPM** → editar texto → draft → runtime review.

## Quero mudar start point

Explorer `Fields` → **Abrir SPP** → índice/state/X/Z → draft → runtime review.

## Quero editar efeito `.part`

Inicie `pt_part_ui.py` → selecione `.part` → Stage em campos editáveis → Verify draft → preview plan/Blender.

## Quero comparar duas versões do client

Comparar → roots → filtros → SHA opcional → **Comparar árvores**.

## Quero entender um blocker server

Servidor/Enrichment → Analisar Asset Enrichment → Explorador de bundles → filtro status/reason → selecionar linha e ler a cadeia.

# 61. Regra final

Use a UI como uma sequência de **evidência → staging → validação**, não como editor direto do target:

```text
client/server físico (read-only)
        ↓
catálogo / bundle / inspect
        ↓
structural / binding / source evidence
        ↓
workspace ou draft em pt_build
        ↓
roundtrip / visual / review
        ↓
candidate + provenance
        ↓
publish externo deliberado (não exposto pela UI 1.0)
```

Se o botão não aparece, não contorne a capability layer copiando manualmente um comando de outro asset. Primeiro descubra qual gate/contrato falta.

---

## Atualização operacional 2026-09-21 — Management Legacy + Legacy Authoring Python

Esta seção é a referência operacional atual para as funcionalidades Management/World Closure/Authoring. Em caso de conflito com descrições históricas anteriores deste manual, **esta seção prevalece**.

### Management Legacy: evidência, não dependência de executáveis

PriTaTor, NPCManager, ItemDistributor, ItemEditor/Editor de Itens, Editor de Monstros e tooling relacionado foram incorporados como **evidência estática e contratos recuperados**. Nenhum executável legacy é requerido para operar os workflows Python já promovidos, e a aplicação não inicia esses EXEs.

Isso **não significa que todas essas aplicações tenham sido completamente descompiladas/portadas**. O estado atual é misto: NPCManager/SPC possui substituto Python operacional; PriTaTor/ItemEditor/MonsterEditor têm substituições parciais nos workflows já provados; ItemDistributor/userdata e várias ferramentas admin permanecem evidência ou fora do escopo. A matriz de substituição fica na documentação/API de engenharia e não ocupa mais o workspace operacional.

A auditoria Management cruza, quando os roots estão configurados:

```text
Field/SPM → Monster/INF → item code → OpenItem → sITEM → DorpItem → ícone/ASE
```

Ela complementa o census existente da aplicação; não cria um universo paralelo de assets.

### World Closure Explorer

O World Closure Explorer é uma camada de correlação e diagnóstico. Estados principais:

- `CLOSED`: a closure esperada para aquele gate foi encontrada;
- `REVIEW`: existe contexto suficiente, mas falta uma dependência ou decisão; não significa automaticamente asset quebrado;
- `RUNTIME_CATALOG_MISSING`: o code apareceu no server/OpenItem, mas não há registro source-verificado correspondente na runtime table;
- `RESOLVED`: referência resolvida para um target único;
- `AMBIGUOUS`: mais de um target plausível; a UI não escolhe silenciosamente;
- `UNRESOLVED`: target ainda não provado.

Selecionar uma linha mantém o contexto no **World Closure Explorer** e mostra o motivo do estado. Para abrir o editor, use a ação explícita oferecida no detalhe da linha:

```text
ITEM row    → Abrir definição do item
SPM row     → Editar SPM
MONSTER row → Editar monstro
NPC row     → Editar NPC
```

Para ITEM, o path vem do census real de OpenItem; a aplicação não assume `CODE.txt`.

### Legacy Authoring / Reescrita Python

Kinds atualmente suportados:

```text
ITEM MONSTER NPC SPM SPP SPC
```

Pipeline:

```text
Inspect
→ Edit/Create
→ Stage em pt_build
→ Validate
→ hash preflight
→ backup
→ publish atómico
→ post-write verify
→ runtime review
→ Restore, se necessário
```

`Stage` não altera client/server. Publish e restore são capability-scoped e exigem autorização/confirmação explícita.

#### ITEM

Cria/edita OpenItem para codes já reconhecidos pela runtime table source-verificada. Em EDIT, diretivas desconhecidas são preservadas sempre que o writer não precisa substituí-las. A pipeline integra identidade `sITEM`, `ItemFilePath`, `DorpItem` e closure visual.

Registrar um **code runtime totalmente novo** em `sITEM` continua bloqueado enquanto o writer dessa tabela não estiver certificado.

#### MONSTER

Cria/edita definição de Monster, incluindo campos/stats, EXP, item drops, money drops, extra drops, dialogs e linked file no escopo provado.

#### NPC

Cria/edita definição NPC, flags/campos, dialogs e shops no escopo provado. Placement fixo usa o writer SPC.

#### SPM

Operações estruturadas incluem actor add/remove, boss add/remove, horas de boss/spawn e diretivas como `MAX_ACTOR_POS`, `MAX_ACTOR` e `DELAY`.

#### SPP

Writer para o layout canónico de start points (`200 × 12 bytes`, records `state,x,z`).

#### SPC

Writer para o layout canónico de fixed NPC (`100 × 504 bytes`) com `ADD`, `REPLACE` e `REMOVE`.

### Safety arms e transação

Na Web UI:

- `ARM BUILD WRITES` autoriza staging em `pt_build`;
- `ARM ASSET DEPLOY` é separado e necessário para publish/restore de Asset Bundles.

CLI de publish/restore:

```bash
python3 pt_asset.py legacy-authoring publish \
  --confirm 'APPLY ASSET BUNDLE'

python3 pt_asset.py legacy-authoring restore \
  --confirm 'RESTORE ASSET BUNDLE'
```

A transação executa hash preflight, backup, replace atómico e verificação pós-write. Drift externo desconhecido bloqueia a operação.

### Limites fail-closed

Continuam deliberadamente bloqueados:

- registro arbitrário de code novo na runtime table `sITEM`;
- mutação binária de userdata/warehouse;
- internals não comprovados do ItemEditor nativo;
- qualquer formato sem corpus/ABI/roundtrip suficiente para writer seguro.

Guia aprofundado: `docs/tematicos/LEGACY_MANAGEMENT_AUTHORING.md`.

<!-- PT_SERVER_ENRICHMENT_MANUAL_WORKFLOW_V2_2026-09-22 -->
## Servidor / Enrichment — workflow operacional

Use esta página para **configurar → diagnosticar → censar/recuperar → validar → consultar evidência**. Use **Management Legacy** para criar/editar Item, Monster, NPC e Field ou para resolver World Closure. Não existe um segundo authoring cockpit na página Server.

Jobs iniciados no Server são acompanhados em **Servidor → Atividade**. O console e o histórico ficam ali e o botão **Abrir resultado** retorna à etapa que produziu o relatório.

Em **Source & donors de evidência**, use uma linha por donor: `LABEL=/caminho`. Também é permitido colar a linha completa do comando, por exemplo `--donor-client 'DONOR1=/caminho com espaços'`. Se a entrada for inválida, a UI mostra lado, número da linha, motivo e exemplo; a configuração inteira permanece inalterada.

<!-- PT_CLIENT_ENRICHMENT_MANUAL_WORKFLOW_V3_2026-09-22 -->
# Cliente / Enrichment — fluxo operacional

Use **Cliente / Enrichment** para resultados agregados do client, não para navegar novamente por todos os assets.

- **Visão geral** mostra root/métricas e encaminha para Catálogo ou Entidades quando a tarefa é inspeção individual.
- **Diagnóstico** executa Client Enrichment e auditoria das classes.
- **Censo & recuperação** contém o lado CLIENT do Censo geral e o dependency graph. Se Source/donors estiverem incompletos, use **Configurar Source & donors**, que abre a configuração compartilhada em Servidor.
- **Validação** mostra gaps/certificações; clicar num path físico pode abrir o asset no Catálogo, mas o resultado agregado permanece nesta aba.
- **Texture Enhancement** contém somente o lote global. Enhancement individual pertence ao Catálogo.
- **Atividade** contém as tarefas iniciadas nesta página, console e **Abrir resultado**. Esses jobs não são repetidos em Tarefas gerais.

Essa divisão evita três autoridades para a mesma operação: Catálogo cuida de assets individuais, Entidades cuida de relações, e Cliente / Enrichment cuida de análise/recovery agregados.

<!-- PT_CATALOG_ENTITY_PERF_VISUAL_MANUAL_V4_2026-09-22 -->

## Catálogo e Entidades: leitura rápida e Visual Bundle

A listagem de Entidades é cacheada por revisão. Reindexar o client ou alterar categoria/role de um asset invalida o snapshot automaticamente. Ao pesquisar rapidamente, requests antigos são cancelados e não continuam acumulando resultados atrasados.

Em **Item**, a tela de detalhe mostra também **Visual bundle**. `runtime ...` lista códigos de item que permanecem identidades distintas; `VISUAL ×N` indica quantas identidades ITEM compartilham a mesma aparência segundo dependências comprovadas. **Ver visual bundle no Catálogo** mostra os paths físicos relacionados, incluindo drop model/textures e, quando provado pelo registry, config/modelo equipado.

Se um arquivo esperado não entrar no bundle, não force uma associação pelo nome: use o detalhe/registry para verificar a cadeia. O agrupamento é deliberadamente conservador.

<!-- PT_CATALOG_PERSISTENT_ITEM_RELATIONS_MANUAL_V5_2026-09-22 -->

## Catálogo e itens relacionados · fluxo rápido

- Use **Reindexar** quando arquivos do client forem alterados fora do PT Asset Tool. Esse é o comando que atualiza o censo físico persistido.
- Sair e voltar para **Catálogo** ou **Entidades** não deve disparar nova varredura do client. A UI reutiliza os índices persistidos e cache do browser.
- Na coluna **Relação item**, o Catálogo identifica o papel observado do asset: imagem do inventário, modelo/textura no chão ou config/modelo/textura equipada.
- Ao abrir um asset de item, **Bundle visual do item** mostra os códigos runtime associados e os arquivos relacionados agrupados por papel. Agrupamento visual não significa que os códigos runtime sejam o mesmo item.
- Se um papel estiver classificado incorretamente, escolha outro em **Papel visual do item** e salve. O asset muda de grupo sem escrever no client. Escolha **Automático** para remover o override e voltar à evidência do censo/graph.

<!-- PT_CATALOG_CLASSIFICATION_SMD_PREVIEWS_MANUAL_V6_2026-09-22 -->

## Catálogo · filtros, personagem e preview SMD

- Selecione filtros normalmente: Categoria, Entidade, Personagem, Pasta, Role e Extensão atualizam a lista imediatamente.
- **Personagem** é um filtro separado de **Pasta**. Sons de uma classe continuam AUDIO e não transformam o nome da classe numa pasta semântica.
- Ao selecionar um `.smd` Model0.62 com INX/SMB necessários comprovados, a UI agenda automaticamente um preview Blender low-res em background. Continue navegando; quando terminar, o PNG aparece no painel do asset.
- O preview é cacheado em `pt_build/previews/smd_catalog/`. Não há escrita no client.
- Em **Anotação do catálogo**, Categoria, Role e Personagem são dropdowns. Escolher um valor cria override manual; escolher **Automático** remove o override e volta à classificação derivada do registry/dependency graph.
- Para texturas com nomes ambíguos, prefira a ligação mostrada por `SMD_MATERIAL_TEXLINK`/INX→SMD. Nome de ficheiro isolado é apenas pista.

<!-- PT_BLENDER_RUNTIME_PORTABILITY_MANUAL_V7_2026-09-22 -->
## Escolher Blender no portátil e na torre

O projeto não contém paths pessoais hardcoded. Para uma máquina com Blender normal no PATH, não é necessário configurar nada.

Override temporário:

```bash
PT_BLENDER_EXE=/caminho/para/blender python3 pt_asset.py dependencies
```

Override persistente, apenas nesta instalação/máquina:

```bash
python3 pt_asset.py config set-blender-exe /caminho/para/blender
```

No portátil, o binário Blender 3.6 pode ser usado diretamente para processamento headless. Se workflows Blender interativos precisarem de um launcher que configure Mesa/llvmpipe, esse launcher executável também pode ser salvo como `blender_executable`. A ferramenta não altera drivers nem injeta variáveis gráficas.

`python3 pt_asset.py dependencies` deve informar claramente o executável escolhido, a origem da escolha e a versão detectada. Blender 3.6.x não é rejeitado por exigir uma versão 4.x/5.x; compatibilidade de scripts continua sendo mantida no pipeline comum.

<!-- PT_SMD_PREVIEW_BACKGROUND_MANUAL_V8_2026-09-22 -->
## Gerar previews de modelos SMD em lote

No Catálogo, use **Gerar previews SMD** para aquecer o cache em background. Há ações separadas para **Regerar stale** e **Repetir falhados**. O progresso aparece em Cliente → Atividade e a navegação continua disponível durante o processamento.

Também é possível executar pela linha de comando:

```bash
cd app
python3 pt_asset.py preview render-all-smd --mode warmup --workers 1
```

Os resultados são gravados somente em `app/pt_build/previews/smd_catalog/`. O client permanece read-only. O Catálogo oferece o filtro de preview (`READY`, `MISSING`, `STALE`, `FAILED`) e usa o PNG gerado como imagem padrão de cada SMD quando o estado é `READY`.

Após **Reindexar**, previews já existentes são marcados `STALE`; eles não são apagados. Rode **Regerar stale** para atualizar apenas o que precisa ser reprocessado.

<!-- PT_SMD_PREVIEW_V81_MANUAL_2026-09-22 -->
### Previews SMD V8.1

O preview do Catálogo representa o ambiente de pintura/modelo, não o ambiente de animação. A ferramenta não carrega Actions para gerar a miniatura. Modelos rígidos usam INX/LOD somente quando a cobertura do modelo é válida; caso contrário, podem usar o skeleton comprovado para uma visualização read-only.

Para retomar depois de interrupção:

```bash
cd app
python3 pt_asset.py preview render-all-smd --mode warmup --workers 1
```

`Ctrl+C` cancela o batch e os processos Blender em andamento sem descartar previews `READY` já gerados.

<!-- PT_MANAGEMENT_LEGACY_MANUAL_V9_2026-09-23 -->
## Management Legacy — guia operacional V9

1. Configure a raiz do servidor. A página detecta `GameServer`, `DataServer` e bases SQLite locais.
2. Escolha uma tarefa no topo. Item, Monstro, NPC e Mapa possuem editor próprio dentro da tarefa; trocar de tab não mistura spec/path/manifest.
3. Em Item/Postbox, selecione `código — nome` nas listas carregadas pelo backend. Personagens e contas também vêm do DataServer.
4. Use **Inspecionar** antes de editar. `Stage` grava somente em `pt_build`; o servidor real não é alterado nesse passo.
5. Revise o manifest gerado. **Publicar bundle** só fica disponível para o manifest produzido pelo Stage atual.
6. Personagem/Conta/Postbox/Admin usam **plano → revisão → confirmação → apply** quando a escrita é suportada.
7. Admin local usa SQLite por schema. Se houver mais de uma base, a UI mostra os candidatos e escolhe uma que suporte SoD/BPRank/bloqueio conforme a operação.
8. World Closure é descoberta/diagnóstico: REVIEW explica o motivo e encaminha para a tarefa apropriada.
9. Interpretação de erros: `404` = não encontrado; `409` = pré-requisito/armamento; `422` = valor/payload rejeitado; `500` = bug/falha inesperada.
10. Arquivos gerados permanecem sob `app/pt_build/**`; runtime/user data em `app/pt_build/**` e `enhancement/**` nunca é limpo pelo patch.

<!-- PT_PORTABLE_APP_V10_2026-09-24 -->
### Executável portátil Linux

O release portátil usa um único `pt-asset-tool` Linux x86_64. Python, Pillow, NumPy, scripts first-party, contratos/UI e o vendor de enrichment são incorporados ao bundle; Real-ESRGAN também é incorporado quando está presente em `tools/realesrgan/`. Blender continua externo e opcional.

No binário congelado, estado e configuração não ficam no diretório temporário do executável: `pt_build` persiste em `~/.local/share/pt-asset-tool/pt_build`, configuração em `~/.config/pt-asset-tool/` e cache em `~/.cache/pt-asset-tool/`. Para uma instalação autocontida, defina `PT_ASSET_HOME=/caminho`.

Build de release recomendado: `./build_portable_container.sh`. O artefacto sai em `dist-portable/pt-asset-tool`. Build local de desenvolvimento: `cd app && ./build_portable_linux.sh`.

## Atualização operacional 2026-09-28 — nomes coerentes no Legacy Authoring

A criação/edição de Item, Monster, NPC e Field agora usa o catálogo semântico empacotado. Procure pelo nome visível e escolha a entrada canônica; a ferramenta resolve o path e os identificadores necessários. `canonical_id` distingue variantes que compartilham o mesmo código runtime. Para mapas, o catálogo resolve Map → Stage/Spawn → SPM/SPP/SPC; para placements, SPM oferece mobs e SPC oferece NPCs. A seleção não publica nada: o fluxo de stage/publish/restore continua obrigatório.
