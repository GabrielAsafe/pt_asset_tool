# PT Asset Tool R14 1.0.0 — Manual Completo do Desenvolvedor

**Estado:** código da 1.0 certificado; documentação consolidada.  
**Regra:** alterações de engenharia continuam fail-closed e não autorizam client/server publish por si só.

## A. Arquitetura autoritativa da 1.0

Leia primeiro:

- `ARCHITECTURE_1_0.md` — camadas e data flow;
- `MODULE_REFERENCE_1_0.md` — inventário dos módulos;
- `CLI_REFERENCE_1_0.md` — superfície pública real gerada do parser;
- `FORMATS_WRITERS_1_0.md` — matriz de parsers/writers;
- `SECURITY_SAFETY_1_0.md` — autoridade e zonas de escrita;
- `RELEASE_1_CERTIFICATION.md` — baseline certificado.

### Entry points

`pt_asset.py` é a camada consolidada/compatibilidade. A maior parte do CLI é definida em `pt_asset_tool.cli`; comandos históricos/forenses adicionais são interceptados no launcher. A GUI usa `ui_app/ui_actions/ui_capabilities` e sempre chama comandos allowlisted.

### Artefactos mutáveis

Todo estado operacional mutável grava em `app/pt_build`; o pacote limpo exclui esse diretório. Isso inclui configuração local, registry gerado, certifications, caches, evidence e reports. Uma instalação fresh não transporta estado da máquina usada para construir o pacote.

### Regra de mudança

1. parser/read-only evidence;
2. corpus e negativos;
3. deterministic temp/candidate writer;
4. reparse/semantic witness;
5. Blender/human review quando necessário;
6. policy/coverage;
7. package verifier/snapshot;
8. publish continua autorização separada.

### Testes mínimos antes de distribuir

A política canónica de validação está em `VALIDACAO_TESTES_DESENVOLVIMENTO.md`. Não presuma que o Python global possui `pytest`; selecione explicitamente o Python/venv de desenvolvimento.

Resumo, a partir de `app/`:

```bash
PY="${PT_ASSET_TEST_PYTHON:-python3}"

PYTHONDONTWRITEBYTECODE=1 \
"$PY" -m pytest -q dev_tests tests

node --check pt_asset_tool/ui_static/app.js
```

Da raiz, depois de revisar a mudança e o estado gerado:

```bash
./VERIFY_PACKAGE.sh
```

Use `arquivo.py::test_nome` para fechar um bug específico, mas não trate esse PASS focado como substituto da regressão aplicável. `compileall` é opcional e cria `.pyc`; para sintaxe sem cache use a checagem AST documentada no runbook.

Gates que precisam de client/server/Blender real devem ser executados somente onde essas roots existirem; nunca substitua ausência de ambiente por mock que transforme um gate físico em PASS.

### Documentação como contrato

Novos comandos públicos devem entrar em `cli.py`/launcher, testes e documentação. A referência `CLI_REFERENCE_1_0.md` pode ser regenerada do parser; atualize também `FEATURE_MATRIX_1_0.md` se a capability mudar.

---

## B. Reverse engineering e engenharia acumulada

Abaixo está preservado o conteúdo técnico acumulado da linha R14, porque ele contém invariantes e decisões que continuam relevantes para manutenção da 1.0.

**Estado:** Release 1.0.0 certificada / safety-locked  
**Público:** desenvolvedores que vão manter, ampliar ou auditar o reverse engineering do Summit Tale / Priston Tale Asset Tool.  
**Este documento não é um manual de utilização.** Comandos operacionais, instalação e “como clicar” pertencem ao `MANUAL_UTILIZADOR.md`.

---

# 1. O que este manual deve preservar

O principal patrimônio deste projeto não é apenas o código. É o conjunto de **conclusões técnicas já provadas** sobre formatos antigos, as evidências usadas para prová-las e os limites de cada writer.

Um novo desenvolvedor deve conseguir responder, sem repetir meses de investigação:

- qual é o layout físico conhecido de SMD Model0.62, SMB, INX, Stage0.72, BMP e TGA protegidos;
- como o tool diferencia `STATIC`, `RIGID_PHYSIQUE`, Stage0.72, variants/outliers e famílias semânticas;
- quais campos são tratados como source truth e quais ainda são apenas diagnósticos;
- quais scripts são parsers, audits, probes, candidates, bridges, production writers e promoção;
- por que alguns writers são certificados somente para um asset/escopo muito pequeno;
- quais invariantes de preservação de bytes devem continuar valendo;
- como Blender entra no fluxo sem virar “autoridade” do formato;
- como continuar reverse engineering sem transformar uma hipótese em feature de produção.

A regra de engenharia é:

```text
observar bytes/source/corpus
→ formular hipótese
→ escrever parser/audit read-only
→ provar invariantes no corpus
→ construir witness/roundtrip em cópia
→ provar negativos/fail-closed
→ provar Blender/artista quando necessário
→ somente então considerar um writer
→ produção exige gate/policy/certificação adicional
```

---

# 2. Níveis de evidência usados no projeto

Não use a palavra “suportado” sem indicar **em qual nível**.

| Nível | Evidência | Exemplo | Pode autorizar write? |
|---|---|---|---|
| `FORMAT_IDENTIFIED` | magic/header/layout reconhecido | `SMD Model data Ver 0.62` | não |
| `PARSE_PASS` | parser fecha bounds/counts/pointers | Model0.62 object blocks | não |
| `CORPUS_PASS` | mesma regra passa em muitos assets reais | TGA 2720/2722 reconhecidos historicamente | não |
| `SEMANTIC_LINK_PASS` | relações entre arquivos são comprovadas | INX `LinkFile` → SMB | não |
| `BLENDER_PREVIEW_PASS` | representação no Blender faz sentido | Ahin geometry/material | não |
| `ROUNDTRIP_NOOP_PASS` | decode/rebuild sem alteração é byte-idêntico | BMP/TGA/INX/SMB candidates | ainda não |
| `WITNESS_WRITE_PASS` | alteração pequena controlada sobrevive ao parser/gate | UV/geometry witness | somente naquele witness |
| `ARTIST_WORKFLOW_PASS` | `.blend` salvo por artista é aceito por guard | rare rigid | somente escopo provado |
| `PRODUCTION_POLICY_PASS` | política, hashes, negativos e evidência manual fechados | at_dragon rare writer | sim, no escopo exato |
| `PUBLISH/RESTORE_PASS` | destino/backup/drift/transação verificados | restore hardened | somente destino gerenciado |

Um `PASS` de um nível **não promove automaticamente o próximo**.

---

# 3. Fontes de verdade e metodologia de reverse

O projeto usou cinco tipos principais de evidência:

## 3.1 Código-fonte legado / ABI

Quando existe source antigo do engine, tamanhos, offsets e fórmulas são reproduzidos explicitamente. Exemplos preservados no código:

- `sizeof(smDFILE_HEADER) = 556`;
- `sizeof(smDFILE_OBJINFO) = 40`;
- `sizeof(smOBJ3D) = 2236`;
- `sizeof(smMATERIAL_GROUP) = 88`;
- `sizeof(smMATERIAL) = 320`;
- estruturas de keys `TmRot/TmPos/TmScale`;
- fórmulas de `GetSpeedSum`, keyword encoding de INX;
- semântica de `TexLink` e `TextureStageState`;
- multiplicação de matrizes usada no runtime.

## 3.2 Corpus físico do client

O source pode descrever uma versão idealizada, mas o client real contém variantes históricas. Por isso o parser só é promovido após varredura física.

Exemplos descobertos por corpus:

- INX `MODERN_172` e `LEGACY_120`;
- SMB com trailing payload depois do último object block;
- StageArea em `DWORD32`, `WORD16` e variantes com trailing opaque;
- TGA protegido em dois modos de header;
- BMP protegido com 8/24/32 bpp;
- representações INX semanticamente equivalentes mas binariamente não-canónicas.

## 3.3 Roundtrip byte-idêntico

Quando o tool afirma que conhece um transporte/rebuild, o primeiro gate é:

```text
source bytes
→ parse/decode
→ rebuild sem alteração
→ bytes exatamente iguais ao source
```

Isso é muito mais forte do que “abre no Blender”.

## 3.4 Witness controlado

Para provar escrita, muda-se deliberadamente **uma classe muito pequena de dados**:

- um UV;
- uma posição de vértice;
- um normal;
- uma key INX/SMB;
- uma região de pixel;

Depois o comparator prova que somente o conjunto de bytes permitido mudou.

## 3.5 Inspeção humana / runtime

Algumas propriedades não podem ser provadas apenas estruturalmente. Geometria, rig, animação e material precisam de Blender e, idealmente, runtime do jogo.

O registro de certificação é append-only para não apagar FAILs históricos.

---

# 4. Visão física do ecossistema de arquivos

```text
SMD Model0.62
  ├─ geometria
  ├─ materiais
  ├─ TexLinks/UV
  ├─ transform/object-local keys
  └─ opcional Physique (nome de bone por vertex)

INX
  ├─ configuração/model groups
  ├─ LinkFile / códigos de vínculo
  └─ MotionInfo (estado, frames, repeat, key/motion frame)

SMB
  ├─ skeleton object hierarchy
  ├─ bind transforms
  ├─ TmFrame segments
  └─ rotation/position/scale key arrays

Stage0.72 SMD
  ├─ stage header/map
  ├─ vertices/faces
  ├─ materials
  ├─ TexLinks (inclusive multilayer)
  ├─ lights
  └─ StageArea spatial index

BMP/TGA
  └─ texture/UI payload, às vezes com header proprietário
```

`MONSTER`, `NPC`, `PLAYER`, `UI`, `EQUIPMENT` etc. são **papéis semânticos**; não são necessariamente formatos binários diferentes.

---

# 5. SMD Model data Ver 0.62

A referência byte-a-byte fica em `REVERSE_ENGINEERING_FORMATOS.md`. Aqui está a arquitetura que interessa para implementar adapters.

## 5.1 Header e tabela de objetos

Magic:

```text
SMD Model data Ver 0.62
```

Layout comprovado:

```text
smDFILE_HEADER      556 bytes
smDFILE_OBJINFO      40 bytes por objeto
smMATERIAL_GROUP     88 bytes
smMATERIAL          320 bytes
smOBJ3D            2236 bytes
smVERTEX              24 bytes
smFACE                36 bytes
smTEXLINK              32 bytes
smTM_ROT               20 bytes
smTM_POS               16 bytes
smTM_SCALE             16 bytes
matrix                 64 bytes
```

Campos do header usados pelo parser:

```text
0x00  char szHeader[24]
0x18  ObjCounter
0x1C  MatCounter
0x20  MatFilePoint
0x24  First_ObjInfoPoint
0x28  TmFrameCounter
```

A tabela `smDFILE_OBJINFO` armazena nome, tamanho e offset físico de cada object block.

## 5.2 Layout serializado de cada smOBJ3D

O block é reconstruído por counts, não por “procurar padrões”:

```text
smOBJ3D header (2236)
vertices  = nVertex   * 24
faces     = nFace     * 36
texlinks  = nTexLink  * 32
rot keys  = nRot      * 20
pos keys  = nPos      * 16
scale keys= nScale    * 16
prev rot  = nRot      * 64
physique  = nVertex   * 32   # somente se Physique pointer != 0
```

O parser exige que o cursor calculado feche **exatamente** no tamanho registrado em `smDFILE_OBJINFO`.

## 5.3 Vértices

Cada `smVERTEX` é 6 `int32`:

```text
x y z nx ny nz
```

Posição usa fixed point com escala histórica de `256`:

```text
blender/source_float = serialized_int / 256.0
```

## 5.4 Faces e TexLink

Cada face guarda três índices de vertex, material e um ponteiro runtime serializado para o primeiro `TexLink`.

Nunca trate o valor do ponteiro como endereço válido do processo atual. O tool converte a relação usando:

```text
index = (serialized_pointer - serialized_texlink_base) / sizeof(smTEXLINK)
```

A chain `NextTex` permite múltiplos stages de UV/material por face.

## 5.5 Physique

No formato estudado, Physique não é weight arbitrário por bone. Para cada vertex do object rigid existe um nome de bone fixo de 32 bytes.

O importer transforma isso em grupo Blender com peso 1.0. Portanto:

```text
RIGID = todos os objects possuem Physique
STATIC = nenhum object possui Physique
MIXED = mistura no mesmo SMD
```

No audit canónico atual:

```text
Model0.62 total = 3148
RIGID           = 1953 raw
STATIC          = 1195
MIXED           = 0
```

`MIXED` permanece fail-closed porque não há representante real canónico para provar importer/writer.

## 5.6 Rigid não significa “o SMD contém o skeleton”

O SMD rigid contém nomes de bones usados por seus vertices. O skeleton/motion context pode vir de SMB resolvido por INX/root binding.

Esse é o motivo de `AssetRegistry` manter separadamente:

```text
physical family
binding mode
binding skeleton SMB
binding root models
config paths
```

---

# 6. Materiais Model0.62

O material parser nasceu da combinação de ABI/source e corpus.

Campos relevantes em `smMATERIAL`:

```text
0    InUse
4    TextureCounter
8    historic smTexture[8] pointers
40   TextureStageState[8]
72   TextureFormState[8]
104  ReformTexture
108  MapOpacity
112  TextureType
116  BlendType
120  Shade
124  TwoSide
128  SerialNum
144  Transparency
148  SelfIllum
152  TextureSwap
156  MatFrame
160  TextureClip
164  UseState
168  MeshState
172  WindMeshBottom
176  historic smAnimTexture[32] pointers
304  AnimTexCounter
308  FrameMask
312  Shift_FrameSpeed
316  AnimationFrame
```

Os pointers históricos dentro de `smMATERIAL` **não são usados como nomes de arquivo**. Quando `InUse` está ativo, SaveFile acrescenta um bloco:

```text
int StrLen
Name\0 NameA\0 ...
```

com pares para texturas normais e animadas.

Campos com evidência forte de runtime/visual incluem `SelfIllum`, `TwoSide`, `BlendType`, `BlinkColor/UseState` histórico e preservação de `Shade`. Não ampliar sem nova prova os significados de transparency/order/Z-write.

---

# 7. Multilayer TexLink

`TexLink` é a ligação entre uma face e um ou mais stages de coordenadas/textura.

O reverse comprovou:

- chain por `NextTex`;
- `hTexture` reconstruível em relação ao array runtime de material/stage;
- `TextureStageState` corresponde a códigos `D3DTOP_*` extraídos do source;
- `TextureFormState` corresponde a `FS_*` (`FORMX`, `SCROLL`, `REFLEX` etc.);
- existem assets reais com depth > 1, inclusive Stage0.72 depth 3 nos fixtures.

O módulo `multilayer_texlink.py` classifica perfis como:

```text
SINGLE_STAGE
REFLEX_ADD
SECOND_UV_LIGHTMAP_MODULATE
SECOND_UV_MODULATE
SAME_TEXTURE_DYNAMIC_FORM
DUPLICATE_TEXTURE_DEFAULT_STAGE
GENERIC_TWO_STAGE
```

`validate texlinks` **não é** “validar qualquer material”. É um workflow visual especializado para uma forma multilayer específica. O generic inspector é `asset texlinks`/semantics.

---

# 8. Object-local animation em SMD static

Alguns SMDs sem Physique contêm transforms/keys no próprio `smOBJ3D`.

O reverse atual usa:

- `Tm`, `TmInvert`, quaternion/base transform, scale e position do object;
- arrays `TmRot`, `TmPos`, `TmScale`;
- matriz `TmPrevRot` serializada ao lado de rotation keys;
- hierarquia `NodeName`/`NodeParent`.

Ponto importante: as rotation keys podem ser incrementais. O `TmPrevRot` acumulado é tratado como source truth quando necessário.

Existem effects antigos com quaternion não-unitário; o código possui caminho compatível que não normaliza automaticamente, porque o runtime antigo pode transformar magnitude em scale/shear affine.

Esse parser é deliberadamente para static/no-Physique. Chamar `object-local` em um rigid Physique deve ser recusado.

---

# 9. INX

O INX não foi tratado como “config textual”. É uma estrutura binária com duas famílias físicas comprovadas.

## 9.1 Layouts

```text
MODERN_172
  file size   95,268 bytes
  MotionInfo  172 bytes

LEGACY_120
  file size   67,084 bytes
  MotionInfo  120 bytes
```

Constantes atuais:

```text
MotionInfo max = 512
MotionInfo base offset = 0x18C
CHRMOTION_EXT = 10
```

Offsets específicos por layout ficam em `pt_inx_motion_core_v2.py`.

## 9.2 MotionInfo

O parser extrai:

```text
state/state_name
start frame
end frame
repeat
key_code
motion_frame
encoding
```

Estados conhecidos incluem `STAND`, `WALK`, `RUN`, `ATTACK`, `DAMAGE`, `DEAD`, `SKILL` etc.

## 9.3 Keyword encoding

Parte dos frames não está serializada como int simples. O tool reconstrói `file_code` e `link_code` e reordena bytes entre keyword/frame DWORDs conforme o algoritmo do source.

Um detalhe importante descoberto no corpus: nem todo registro estendido usa a representação “canónica” que o encoder produziria. Há registros semanticamente válidos com bytes diferentes. Por isso o writer candidato atual **preserva a representação original dos campos não editados**.

Na prova de desenvolvimento mais recente:

```text
542/542 INX NPC/Monster → no-op byte-identical
531 MODERN_172
11  LEGACY_120
73 arquivos / 100 records com start encoding alternativo válido
542/542 controlled edit probes passaram
```

Isso ainda é `CANDIDATE_PT_BUILD_ONLY`, não produção.

## 9.4 LinkFile e binding

INX contém relação física que pode apontar para outro config/skeleton context. `verified_inx_link_target` não aceita apenas texto do path; ele também compara os códigos de arquivo/link quando disponíveis.

Essa evidência é usada por `AssetRegistry` para resolver root skeletons sem adivinhar por nome.

---

# 10. SMB

SMB usa a mesma magic/header family de Model0.62, mas é usado como container de skeleton/motion.

O evaluator conhece:

```text
smOBJ3D name/parent
Tm / TmInvert / TmRotate
position
rotation/position/scale key counts
TmFrame segments
```

Tamanhos principais coincidem com a ABI Model0.62:

```text
smTM_ROT   20
smTM_POS   16
smTM_SCALE 16
matrix     64
```

## 10.1 Regra importante sobre EOF

O primeiro parser assumia que o final do último object block deveria coincidir com EOF. O corpus provou SMBs legítimos com trailing payload (`Vampiric`, `SN-002`, `MN-005`, `MN-009`).

A correção foi **local ao parser SMB**. Não relaxar a regra global de SMD Model0.62 por causa disso.

## 10.2 Hierarquia fechada x preservação binária

`Ahinf.smb` provou outro caso útil: um support skeleton pode referenciar parent externo (`Bip01 Head`).

Foram separados dois contratos:

- **binary preservation parser**: pode preservar/regravar tracks sem precisar avaliar toda a hierarquia;
- **animation evaluator**: exige hierarquia suficiente para calcular world transforms.

Não enfraquecer o evaluator para fazer um roundtrip binário passar.

## 10.3 Writer candidato

Estado da prova de desenvolvimento:

```text
18/18 SMB fornecidos → no-op byte-identical
14 arquivos tinham keys editáveis e passaram controlled edit
4 não possuíam key adequada ao probe
0 failures
```

Ainda não é writer de produção.

---

# 11. Animação: INX + SMB + Blender

A cadeia técnica é:

```text
asset
→ binding/context
→ INX MotionInfo
→ motion selected
→ MotionFrame → SMB TmFrame segment
→ evaluate keys no espaço source
→ parent-first hierarchy
→ converter para pose-space Blender
→ criar Actions
```

## 11.1 O que já foi aprendido com Monbagon

Historicamente, `ATTACK` era reconhecível, mas o rig explodia durante frames intermediários e voltava ao normal no final. Isso separou duas hipóteses:

- seleção da motion / leitura de frame provavelmente correta;
- transformação source pose → Blender pose era suspeita.

Um bug real corrigido foi quaternion nulo tratado como `(0,0,0,0)` quando o identity esperado era `(0,0,0,1)` em determinado caminho. Também foram acrescentadas continuidade de sinal, interpolation e proteções no baker.

A investigação correta sempre compara por bone/frame:

```text
source world
parent source world
derived source local
bind world
Blender edit bone
intended pose matrix
pose_basis
final hierarchy result
```

Não volte a mexer no parser INX apenas porque uma pose visual falhou.

---

# 12. Stage SMD data Ver 0.72

Stage0.72 é uma vertical separada de Model0.62.

Magic:

```text
SMD Stage data Ver 0.72
```

Estruturas comprovadas no parser atual:

```text
DFILE header            556 bytes
raw stage header     262260 bytes
StageArea pointer map 256 x 256 entries
material group           88 bytes
material                320 bytes
stage vertex              28 bytes
stage face                28 bytes
TexLink                   32 bytes
light                     28 bytes
```

O parser valida runtime pointer relocation para vertices/faces/TexLinks e material stages.

## 12.1 StageArea

Esta foi uma descoberta importante porque source e arquivos físicos não são uniformes.

Encodings conhecidos:

```text
WORD16
WORD16_TRAILING_OPAQUE
DWORD32
DWORD32_TRAILING_OPAQUE
```

O código preserva a família física. Não converter WORD16 legado para DWORD32 só porque o source mais novo declara `DWORD*`.

No caminho DWORD observado, existe comportamento de capacity/pointer counter que seria fácil “corrigir” incorretamente se olhássemos apenas para C source moderno. Os arquivos físicos são a evidência final de serialização.

## 12.2 TexLink Stage0.72

Fixtures atuais provaram depth 3. Portanto qualquer rewriter que assuma “um TexLink por face” é incorreto para o corpus completo.

## 12.3 Writers atuais

Existem writers de **witness** para:

- UV;
- geometry;
- transporte/preview;
- texture-paint workspace.

Isso ainda não equivale a um generic saved-Blender Stage0.72 builder.

---

# 13. TGA protegido

O adapter está em `pt_protected_tga_v1.py`.

A família conhecida preserva todo o payload/footer e transforma somente os 18 bytes do header usando adição byte-wise módulo 256 com uma key fixa.

Modos físicos:

```text
FULL18
  bytes 0..17 protegidos

KEEP_00_16
  bytes 0..1 permanecem 00 00
  bytes 2..17 protegidos
```

Key atual:

```text
47 38 04 09 10 19 24 31 40 51 64 79 90 a9 c4 e1 00 21
```

Para protected TGA o gate também espera footer TGA 2.0:

```text
TRUEVISION-XFILE.\0
```

No build:

- header proprietário original é preservado byte-for-byte;
- footer original é preservado byte-for-byte;
- somente body/pixels do editable standard TGA entram no artefato;
- estrutura e tamanho devem continuar compatíveis.

Histórico de corpus: 2720/2722 TGAs do levantamento entraram nas duas famílias conhecidas; os dois anômalos não devem ser “forçados” pelo codec.

---

# 14. BMP protegido

O runtime-proven family substitui o `BITMAPFILEHEADER` de 14 bytes e mantém `BITMAPINFOHEADER` DIB40.

O adapter atual suporta:

```text
BI_RGB
8 bpp + palette
24 bpp
32 bpp
dimensões variadas
trailing bytes
```

O editable é convertido para standard BMP (`BM`) mantendo a estrutura física. No rebuild:

```text
baseline[antes dos pixels]  = preservado exatamente
pixel payload               = vem do editable
baseline[depois dos pixels] = preservado exatamente
```

Isso é mais seguro que reserializar o BMP inteiro com Pillow/encoder genérico.

---

# 15. Registry: separar formato físico de papel semântico

`AssetRegistry` não deve inferir “monstro” apenas porque um SMD parece rigid.

Exemplo de modelo mental:

```text
physical_family = SMD_MODEL_062_RIGID_PHYSIQUE
semantic_category = MONSTER
entity = Monbagon
binding_mode = ROOT_SKELETON_BOUND
binding_skeleton = ...smb
```

O catálogo físico pode listar arquivos que ainda não são first-class semantic assets. Por isso INX/SMB/WAV/support files têm fallback de inspeção física.

## 15.1 Binding modes

```text
SELF_CONTAINED
ROOT_SKELETON_BOUND
CONFIG_ONLY
NONE
```

Binding é **contexto técnico comprovado**, não sinônimo de “cabeça anexada”.

## 15.2 Cross-folder pairing

Pairing físico pode provar que um INX em uma pasta aponta para modelo/skeleton em outra. Essa informação é evidência de relação, não licença para fundir duas entidades com nomes parecidos.

---

# 16. Profiles e LOD

Os profiles históricos foram importantes para entender composição de personagens e LODs, mas não são autoridade por si só.

A camada atual faz cross-check de:

```text
path exato
casing físico
hash/size quando disponível
INX associado
skeleton
LOD groups High/Default/Low
```

Uma associação global só por basename é proibida, pois é fácil colidir nomes em subárvores diferentes. Quando um profile histórico traz apenas o basename do INX, a camada atual só o aceita como evidência se o asset já tiver sido identificado por path exato e esse basename resolver para **um único INX associado àquele asset**.

O fluxo profile-driven de import é agora explícito e read-only:

```bash
python3 pt_asset.py profiles authoring-plan priestess_c01_m5 --lod default
python3 pt_asset.py import char/tmABCD/MfbC01.smd --profile priestess_c01_m5 --lod default --no-open
```

`profiles authoring-plan` exige, no mesmo contexto, target SMD exato, componente INX resolvido, skeleton, `lod_groups` e uma única configuração registry compatível. `import --profile` apenas transforma essa prova numa seleção exata de import Blender; o `selected_context` persiste o `profile_id/profile_version` como `selection_basis`, mas isso **não autoriza writer, produção nem client write**.

Workspaces rigid reutilizados também são context-bound: se uma nova chamada pedir outro `--model-info`, outro LOD explícito ou outro profile, a reutilização é recusada e exige `--reset`. Isso evita abrir silenciosamente um `.blend` criado sob outro contexto.

O audit `rigid-model-info-contexts` e o discovery de profiles usam assinatura semântica composta por skeleton + todos os grupos `high/default/low`. Configs multi-INX realmente diferentes continuam exigindo `--model-info` explícito.

---

# 17. Arquitetura dos writers: por que existem tantos scripts `rare_rigid_*`

Essa família de arquivos registra **a evolução da prova**, não apenas duplicação acidental.

O padrão é:

```text
context / binding / preview / geometry
        ↓
small roundtrip/bridge
        ↓
probe de novos limites
        ↓
saved-Blender candidate
        ↓
live-writer candidate em isolamento
        ↓
production promotion audit
        ↓
production policy
        ↓
production dispatcher
```

## 17.1 `bridge`

Um bridge codifica uma transformação muito específica já compreendida, por exemplo normal, extent ou multibone. Ele é uma peça de prova, não necessariamente API de produto.

## 17.2 `probe`

Probe procura representantes/limites e executa alterações em cópia para responder uma pergunta de engenharia. Nunca deve autorizar produção por si só.

## 17.3 `candidate`

Candidate exercita a possível ampliação do writer com:

- certificação isolada;
- client unchanged;
- writer hashes unchanged;
- negativos esperados;
- `production_authorized=False`.

## 17.4 `production_promotion`

Só cria/promove policy após reexecutar provas anteriores, verificar hashes, client, registry real, bounds e negativos.

## 17.5 `production`

O production writer valida a policy no momento da execução. Não confia em “um teste passou meses atrás”.

Essa escada é uma das partes mais importantes do projeto e deve ser repetida para qualquer futuro writer arriscado.

---

# 18. Writers certificados atuais

Os quatro módulos abaixo são tratados como evidência congelada:

```text
pt_asset_tool/rare_rigid_edit.py
3ff2769bbc9762c04fb992fbad52ba7d60ae6a53f19c22d4f1d68e274697eec3

pt_asset_tool/rare_rigid_multivertex.py
0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991

pt_asset_tool/rare_rigid_multibone_bridge.py
010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0

pt_asset_tool/rare_rigid_normal_bridge.py
2c0f75931e54a72cd87be2bc6694370f849c24c3f2b4b44afbdbc288dcaf622c
```

Não fazer “cleanup”, formatter ou refactor nesses arquivos sem iniciar nova certificação.

---

# 19. Blender: editor/transporte, não especificação do formato

Blender é usado para:

- representação visual;
- testemunho humano;
- edição artística;
- extração de geometry/UV/vertex groups;
- geração de Actions.

Mas Blender não decide:

- layout binário;
- quais bytes podem mudar;
- pointer relocation;
- material IDs válidos;
- qual skeleton é correto;
- se um writer está autorizado.

O writer sempre volta à baseline/source e aplica um contrato explícito.

Todo `.blend` editável novo deve ficar em:

```text
pt_build/blender_edits/<workflow>/<asset-descritivo>/
```

---

# 20. Segurança de publish / restore

A estratégia histórica hardened é transacional.

Estados relevantes:

```text
workspace == source && client == source
  → UNCHANGED

workspace == source && client == known managed build
  → restoration pode ser permitida

client hash desconhecido
  → CLIENT_DRIFT
  → overwrite recusado
```

O restore deve:

1. validar containment;
2. conferir source/build hashes;
3. preparar backup de todos os alvos;
4. verificar backups;
5. substituir atomicamente;
6. verificar hash/tamanho pós-write;
7. rollback se qualquer target falhar.

O produto 0.12 não amplia isso para generic publish automático.

---

# 21. Organização do código

O mapa completo está em `MAPA_MODULOS_SCRIPTS.md`.

Macro-famílias:

```text
pt_asset_tool/
├─ core/runtime                config, resolver, registry, validation, certification
├─ catalog/product             entity_catalog, semantic_census, profile_registry, tree_compare
├─ motion/binding              motion_core, binding_coverage, animation_source_regression
├─ candidate binary writers    inx_writer, smb_writer, writer_corpus_audit
├─ Model0.62 static            object_local*, texlink*, static_roundtrip
├─ Stage0.72                   stage072_*
├─ rare rigid evidence ladder  rare_rigid_*
├─ historical official research official_*
├─ archive/container forensics update_tmp_*
└─ GUI                         ui_*
```

---

# 22. Scripts top-level de runtime

Eles existem fora do package porque vários são executados diretamente pelo Blender/subprocess ou nasceram antes da consolidação.

Os mais importantes:

- `pt_smd_blender_import_v4_generic.py`: dispatcher importer Model0.62 STATIC/RIGID; mixed rejeitado;
- `pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py`: importer rigid comprovado e parser central ainda vivo;
- `pt_blender_to_smd_free_mesh_v3.py`: writer artist-oriented de mesh rígida em escopo próprio;
- `pt_blender_to_smd_static_v1.py`: wrapper writer static estrito;
- `pt_character_structural_gate_v2.py`: gate físico Model0.62/skeleton;
- `pt_inx_motion_core_v2.py`: parser/decoder INX moderno/legacy e relação com SMB;
- `pt_asset_tool/legacy_runtime/pt_smb_motion_evaluator_v1.py`: evaluator source-equivalent de motion/skeleton;
- `pt_protected_tga_v1.py`: protected TGA transport;
- `pt_character_texture_v1_4.py`: protected BMP workflow;
- `pt_blender_bind_editable_texture_v2.py`: troca de textura em cópia do `.blend`;
- `summit_workspace_asset_bridge_v1_2.py`: bridge de build aprovado para workspace registry;
- `summit_roundtrip_restore_v4.py`: restore transacional hardened.

`pt_asset_tool/legacy_runtime/` contém duas dependências legadas ainda vivas, migradas do antigo `history_py`. Elas continuam código ativo até serem substituídas por implementações modernas equivalentes.

---

# 23. Como ler os nomes de módulos de pesquisa

## `official_*`

Arqueologia de containers/update payloads oficiais. Serve para responder origem/proveniência/donor compatibility. Não é requerido no caminho normal do programa.

## `update_tmp_*`

Forensics de LHA/LH5 e arquivos temporários/update containers. É ferramenta de pesquisa, não parser de assets de runtime.

## `*_audit`

Read-only sempre que possível. Produz evidência agregada/corpus.

## `*_corpus`

Executa a mesma pergunta sobre muitos assets e procura exceções.

## `*_roundtrip`

Exige reconstrução e comparação estrita; escopo deve ser explicitado no nome/report.

## `*_candidate`

Nunca significa produção. Deve preservar `production_authorized=False` e normalmente usa output isolado.

## `*_promotion`

É um gate de passagem candidate → production, não o writer final.

## `*_production`

Só deve executar após policy/hashes/evidências específicas.

---

# 24. Como desenvolver um novo parser

1. Comece read-only.
2. Declare magic/tamanho/offsets conhecidos em constantes.
3. Faça bounds checks antes de unpack.
4. Exija counts plausíveis.
5. Feche exatamente os blocks quando o formato exige.
6. Trate pointers serializados como relações, nunca como ponteiros válidos.
7. Colete corpus e registre outliers em vez de relaxar globalmente.
8. Separe layout físico de papel semântico.
9. Só depois conecte ao registry/UI.

---

# 25. Como desenvolver um novo writer

Ordem obrigatória recomendada:

```text
parser PASS
corpus PASS
no-op byte-identical
controlled witness
allowlist de changed offsets
negative tests
artifact reparse
client unchanged
writer hash gate (quando aplicável)
Blender/artista proof
candidate isolated
promotion audit
production policy
```

## Nunca faça

- reserializar estruturas desconhecidas “da forma que parece correta”;
- zerar reserved/padding porque “não é usado”;
- normalizar encoding binário semanticamente equivalente sem necessidade;
- alterar client para testar writer;
- usar sucesso visual como substituto de byte preservation;
- ampliar thresholds de produção dentro do mesmo writer só para obter PASS.

---

# 26. Como tratar um outlier

Quando um arquivo quebra uma regra que passa no resto do corpus:

1. preserve o arquivo como fixture;
2. compare magic/tamanho/header/offsets;
3. descubra se é outra family, damaged/placeholder ou conteúdo incorretamente nomeado;
4. crie tratamento específico;
5. não enfraqueça o parser principal antes de provar que a exceção pertence à mesma família.

Exemplo histórico: um `.tga` que revela conteúdo semelhante a HTML depois do codec conhecido não deve ser aceito como “nova variante de TGA” automaticamente.

---

# 27. Testes que realmente protegem reverse engineering

Além de unit tests, mantenha:

- corpus parse tests;
- byte-identical no-op tests;
- changed-offset allowlist;
- source SHA unchanged;
- certification registry unchanged em candidates;
- output containment;
- negative tests para um passo além do escopo autorizado;
- writer hash tests;
- fixture tests de variantes físicas reais;
- Blender tests separados de parsers source-side.

A suíte rápida não deve carregar centenas de MB em toda execução. Corpus pesado fica opt-in, mas deve existir e ser repetível antes de promoção.

---

# 28. Estado técnico atual das grandes frentes

| Frente | Estado de engenharia |
|---|---|
| Model0.62 rigid parse/import | forte evidência / operacional |
| Model0.62 static parse/import | operacional em escopo conhecido |
| Mixed-Physique | bloqueado: zero representante canónico |
| Materials Model0.62 | parser/audits fortes; writer completo não universal |
| Multilayer TexLink | semantics + witnesses em escopos provados |
| Object-local static | parser/evaluator/audits; não usar em rigid |
| INX | modern/legacy parser forte; writer ainda candidate |
| SMB | evaluator + candidate key writer; produção não promovida |
| Animation | source-side forte; certificação visual ainda requer máquina Blender/runtime |
| Protected BMP | transporte/rebuild forte no family conhecido |
| Protected TGA | transporte forte nos dois modes conhecidos; outliers separados |
| Stage0.72 | parser/corpus/UV/geometry/paint avançados; generic saved-edit build ainda não certificado |
| Monster/NPC | entidade/censo/binding evidence; generic writers não autorizados |
| Profiles/LOD | registry + cross-check + profile-driven exact import context; não autoriza geometry writer/build de produção |
| rare at_dragon | writers certificados em escopos estreitos |
| generic build | dispatcher fail-closed; não inventa adapter |
| publish/restore | infraestrutura histórica hardened; generic publish não habilitado |

---

# 29. Próximas linhas de pesquisa recomendadas

Sem inventar formato:

1. terminar certificação visual da ponte de animação em Blender real;
2. usar os audits de binding para fechar casos config-only somente com evidência física;
3. ampliar profiles/LOD a partir de path/hash/INX reais e levar o profile-driven import já exato até candidate build apenas após novos runtime gates;
4. continuar proving INX/SMB candidate writers antes de qualquer promoção;
5. transformar Stage0.72 corpus em gates de writer mais amplos somente onde byte-preservation permitir;
6. manter Mixed-Physique congelado até aparecer representante;
7. aproximar `import/build/publish/restore` de dispatchers genéricos, mas cada family deve continuar fail-closed;
8. reduzir `pt_asset_tool/legacy_runtime` gradualmente, somente quando houver substitutos testados e sem alterar bytes de writers certificados.

---

# 30. Regra de manutenção final

Antes de mudar qualquer parser/writer, escreva em uma frase:

```text
Qual hipótese sobre o formato esta alteração está fazendo?
```

Depois identifique a evidência que permite essa hipótese.

Se a resposta for “parece certo”, “Blender aceitou” ou “funcionou num arquivo”, a evidência ainda não é suficiente para ampliar produção.

A filosofia do projeto é preservar o desconhecido e ampliar capacidade **somente depois de provar o novo escopo**.

## Stage0.72 saved-Blender candidate

A linha de desenvolvimento possui agora um candidate de authoring Stage0.72 deliberadamente menor que um writer genérico de mapas.

O `.blend` importado continua ancorado ao SHA-256 do SMD por `authoring_manifest.json`. Antes de escrever qualquer SMD candidato, `extract_stage072_saved_edit.py` compara o estado salvo no Blender com o source físico e tenta classificá-lo em **exatamente um** dos contratos já provados:

```text
UV_ONLY
```

ou:

```text
GEOMETRY_GRID_MULTI
```

`UV_ONLY` exige geometria, topologia, material assignment/metadata, vertex colors, lights e controles Stage intactos. `GEOMETRY_GRID_MULTI` aceita múltiplos vértices e componentes XYZ, desde que cada posição continue exatamente representável na grelha fixa 1/256; UVs e restantes metadados permanecem imutáveis. O writer de geometria recompõe StageArea/StageMapRect e normals de todas as faces incidentes através das rotinas já provadas.

O candidate não permite mistura de UV + geometria nem alteração de topologia, materiais, cores ou luzes. Depois da extração do witness, o host chama os mesmos `strict_write_stage072_*` e `compare_stage072_*` usados pelos roundtrips de certificação. O resultado continua `CANDIDATE_PT_BUILD_ONLY`, com `production_authorized=false` e `client_write_authorized=false`.

## Deployment transaction preparation (sem apply)

A arquitetura de publish genérico agora possui três níveis separados:

```text
deploy plan
→ deploy prepare
→ deploy verify
→ [não implementado] deploy apply
```

`deploy plan` resolve o asset, o destino físico no client, o writer de produção disponível e a identidade SHA-256/tamanho do artefacto em `pt_build`.

`deploy prepare` continua **read-only em relação ao client**. Ele cria em `pt_build/deploy_transactions/...`:

- cópia de backup do source atual;
- verificação SHA-256/tamanho do backup contra o source;
- cópia staged do artefacto;
- verificação SHA-256/tamanho da cópia staged;
- segundo hash do source após as cópias para detectar uma mutação concorrente;
- `transaction.json` com identidade, paths, hashes e blockers restantes.

`deploy verify` relê esse manifesto e confirma novamente que o client ainda está no SHA snapshot, que o backup continua íntegro e que o staged artifact continua íntegro.

Isso fecha a parte **pré-write** do contrato transacional sem conceder autorização para escrever no client. Ainda faltam uma política genérica de atomic replace, post-write verification e testes de failure injection/rollback antes de existir qualquer `deploy apply`.

### Proveniência do artefacto de build

Um path estar dentro de `pt_build` não é evidência suficiente para publish. Builds novos geram um sidecar:

```text
<artifact>.build.json
```

no formato `PT_ASSET_BUILD_PROVENANCE_V1`. Ele fixa:

- asset id/path/family/kind;
- SHA-256 e tamanho do source usado pelo writer;
- SHA-256 e tamanho do artefacto;
- adapter/writer;
- modo `CANDIDATE_*` ou `PRODUCTION_CERTIFIED`;
- resultado do build;
- `production_authorized` do **writer**, separado de `client_write_authorized`.

`deploy plan` verifica esse sidecar contra o asset, source atual e bytes do artefacto. Um candidate pode ter provenance totalmente íntegra e ainda assim recebe `BUILD_PROVENANCE_NOT_PRODUCTION_AUTHORIZED`. Um ficheiro arbitrário copiado manualmente para `pt_build` recebe `BUILD_PROVENANCE_INVALID`. Isso impede que containment seja confundido com cadeia de confiança.


## Object Local writer candidate

A camada `object_local_writer.py` permite alterar **keys ROT/POS/SCALE já existentes** em SMD Model0.62 static que passe `parse_object_local_smd(..., strict_v1=True)`. O frame e o número de keys não mudam. SCALE continua na grelha inteira 1/256. Para ROT, o writer recompõe a cadeia cumulativa `TmPrevRot` a partir da key alterada, inclusive no layout legacy affine/raw quaternion.

`TmFrameCnt` segmentado também é preservado: as tabelas de segmentos ficam no header fixo do objeto, e o writer altera apenas valores de keys existentes/reconstrói o sufixo `TmPrevRot` quando necessário. Inserção/remoção de keys e alteração da própria tabela de segmentos continuam fail-closed. A maturidade é `CANDIDATE_PT_BUILD_ONLY`, não produção. O gate reproduzível `audit object-local-writer-corpus` procura amostras físicas static com keys POS/SCALE existentes, faz uma alteração temporária em `pt_build`, reparsa o resultado e exige preservação byte-exata fora do campo autorizado. `EMPTY` significa apenas que o client/fixture configurado não contém uma amostra editável; não é promoção de capacidade.


## Stress rigid por profile

Para evitar certificação manual vértice-a-vértice, o fluxo de desenvolvimento possui um stress candidate explícito para profiles canónicos:

```bash
python3 pt_asset.py build char/tmABCD/MfbC01.smd --candidate --stress-profile
```

O workspace Blender continua vindo de `import --profile`. O stress scope é a união dos `lod_groups` HIGH/DEFAULT/LOW do `selected_context`; todos os alvos precisam satisfazer o contrato físico do `pt_blender_to_smd_free_mesh_v3.py`. O writer é aplicado sequencialmente a todos os meshes do profile no mesmo candidate e a validação final exige que **cada alvo tenha sido realmente alterado**, que todos os objetos fora do stress scope permaneçam byte-idênticos, que não existam bones desconhecidos e que o candidate permaneça em `pt_build`.

O writer aceita mudanças de geometria substanciais, incluindo topologia nova, desde que cada mesh continue com uma única UV ativa, materiais já existentes no objeto source, 3..30000 vértices, faces válidas e exatamente um bone group rígido de peso 1.0 por vértice apontando para o SMB selecionado. Esse stress candidate não promove runtime/produção e não escreve no client.

Após o build, `view rigid-candidate` reimporta o candidate combinado e `certification rigid-candidate-review` registra uma única decisão visual para o artefato; no caso stress, essa decisão é expandida de forma auditável para todos os profile/LOD/object contexts ligados ao mesmo SHA-256.

## Release 1.0 — gate automático consolidado (R14)

A definição da 1.0 é tratada como matriz **tipo de conteúdo × capacidade**, e não apenas como uma lista de formatos. Os domínios obrigatórios são PLAYER, NPC, MONSTER, WEAPON_ITEM, EFFECT e MAP. O comando de integração é:

```bash
python3 pt_asset.py validate release-1-auto
```

Ele executa, dentro de `pt_build`, representatives Model0.62 rigid/static, Stage0.72, pose-space de animação, object-local, multilayer TexLink, codecs proprietários BMP/TGA e corpus INX/SMB. Uma família que exista no inventário mas não tenha representante automatizável é blocker; não pode ser omitida silenciosamente.

### Object-local atualizado

`object_local_writer.py` suporta agora alteração de **keys ROT, POS e SCALE já existentes**, inclusive tracks com `TmFrameCnt` segmentado. Para ROT, o quaternion editado e a cadeia cumulativa serializada `TmPrevRot` são reconstruídos em conjunto a partir da key alterada, incluindo o layout legacy affine/raw quaternion. As tabelas de segmentos são preservadas byte-a-byte; inserção/remoção de keys ou edição dos limites de segmento continua fora do contrato. `validate release-1-auto` executa o corpus físico e torna qualquer full-parse failure um blocker explícito.

### Stage0.72 atualizado

O candidate saved-Blender deixa de estar limitado a `SINGLE_VERTEX_X_GRID`. O modo geométrico atual é `GEOMETRY_GRID_MULTI`: aceita múltiplos vértices e componentes XYZ, todos exatamente representáveis em 1/256, recompõe StageArea e as normals das faces incidentes e continua bloqueando topology/material/light/vertex-color. O runner automático edita e reimporta o candidate para verificar os bytes gerados, não apenas a workspace de entrada.

### Rigid standalone sem INX

O corpus contém Model0.62 rigid em EFFECT/MAP (e alguns outliers NPC/Monster) que não têm configuração INX associada, embora possuam SMB irmã no diretório. Esse caso não usa o contexto de personagem. O planner apenas cria uma hipótese `EXACT_SIBLING_STEM` ou `UNIQUE_DIRECTORY_SMB`; o runner só utiliza a SMB se `pt_character_structural_gate_v2.py` provar fisicamente a compatibilidade de todos os Physique bones. Depois disso o candidate permanece `pt_build`-only e é reimportado automaticamente. Nome de arquivo isolado nunca concede binding ou autorização de produção.

### Mixed-Physique

O corpus canónico continua com zero representantes Mixed-Physique. O pipeline, porém, já está implementado sinteticamente: análise por objeto, dispatch para o adapter rigid ou static, preservação do modo Physique e verificação combinada de non-target blocks. Para a definição da Release 1.0, o que permanece é um **blocker externo de certificação física**, não um blocker de arquitetura. É necessária uma amostra autêntica para executar import/build/reimport real antes de qualquer claim de suporte Mixed.


## Release 1.0 — gate físico Mixed e estado final automático

O `validate release-1-auto` não considera a simples presença de um arquivo Mixed-Physique como certificação. Todo `SMD_MODEL_062_MIXED_PHYSIQUE` físico presente no corpus deve passar `mixed_real_devtest.py`: contexto de skeleton/model-info determinístico, structural gate, edição automática de targets rigid e static, build combinado pelos adapters existentes, verificação byte/Physique e reimport. Sem amostra real, o único blocker de formato Mixed é externo. Mesmo quando todos os gates automáticos passam, o runner reporta `BLOCKED_EXTERNAL` enquanto permanecem o gate integrado runtime/game e a promoção controlada dos writers/publish-restore; ele nunca autoriza escrita no client.

## Integração Summit Server / Asset Enrichment 1.0

A arquitetura server-aware, os lifecycles excluídos, os bundles Monster/NPC/Field/Item e os gates read-only estão documentados em `docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md`. A especificação original recebida é preservada em `docs/reference/Summit_Server_Arquivos_e_Funcionamento_2026-09-04.docx`.

### Contrato UI server-aware

`UIContext` mantém `client_root` e `server_root` separadamente. A UI lê resumos pelo módulo `server_ui.py` e dispara gates através de processos CLI allowlisted; ela não implementa parsers/writers próprios. `server_root` pode ser persistido em `pt_build/state/pt_asset_app_config.json`, mas qualquer alteração de source server continua desabilitada.

O endpoint local `/api/server/analyze` aceita somente modos fixos (`environment`, `design`, `inventory`, `entities`, `fields`, `items`). Não há interpolação de shell nem endpoint de deploy server.


## R14.1 — regressão integrada client/server e animação affine

O primeiro `physical-regression-auto` real confirmou que materiais Model0.62 e vários caminhos rigid/static já podem passar, mas isolou três classes de outlier: bases de animação `NON_TRS_SOURCE_BASIS`, um SMB com bloco Physique não contabilizado (`Phoenix.smb`) e um probe SMB que podia quantizar para no-op (`skullma_A.smb`). O desenvolvimento posterior mantém política fail-closed: não aumenta tolerâncias para esconder shear e não converte support-SMB com parent externo em hierarquia standalone certificada.

A estratégia de animação experimental `SVD_BLENDER_RESIDUAL_TWO_BONE_TRS_V2` representa uma base affine full-rank através de dois transforms TRS persistentes: o primeiro factor fica num helper bone não-deformável e o segundo é derivado com `Bone.convert_local_to_pose(..., invert=True)` contra o target global. Rank-deficient + non-TRS permanece fail-closed na camada Blender. Antes de qualquer gate físico de pose, `affine_animation_selftest.py` exige save/reopen Blender headless e comparação de matriz global em `pt_build`.

O comando focado é `validate integration-regression-auto`. Ele valida environment client/server, self-test affine, pose-space bound/standalone, SMB corpus/outliers exatos, TGA outlier/codecs e os censos Monster/NPC/Field/OpenItem server-aware. Não autoriza escrita no client/server nem promoção de candidates.
