# Asset Retention + Cooked DDS — integração com o ecossistema existente

## Objetivo

Esta extensão não cria um segundo asset manifest nem substitui o ContractGraph/manifests já usados pelo PT Asset Tool. Ela acrescenta duas projeções read-only sobre a evidência existente:

1. `asset_retention`: responde se um ficheiro físico está protegido por alguma ligação conhecida ou se é apenas um `ORPHAN_CANDIDATE`.
2. `cooked_texture_evidence`: importa `client/cooked/manifest.json` e `client/cooked/failed.json` do Summit DDS cooker e anexa estado de cook/failure ao asset físico correspondente.

Nenhuma das duas projeções escreve, move, põe em quarantine ou apaga ficheiros do client/server.

## Componentes existentes reutilizados

A implementação foi integrada em cima dos recursos já presentes no tool:

| Recurso existente | Papel nesta integração |
|---|---|
| `contract_graph.py` | modelo de relações com evidence/confidence/status |
| `general_asset_census.py` | composição principal de reachability client/server |
| `client_manifest_evidence.py` | presença em `setfile.lst` / `_update.inf` como evidência positiva |
| `source_evidence.py` | literals/contratos do source atual |
| `enrichment_vendor_adapter.py` + `summit_asset_enrichment_v9/build_dependency_graph.py` | grafo físico cross client/server |
| `server_bundle_census.py` | monster/NPC bundle evidence |
| `server_field_census.py` | Field/SPC/SPM reachability |
| `server_item_census.py` | OpenItem/server item evidence |
| `texture_overlay.py` | promoção de material/texture realmente usados por faces Model0.62 |
| `class_ui_alias_audit.py` | alias/duplicação de UI de classes |
| `general_asset_recovery.py` | recuperação fechada por donor; não é usada para deletar |
| `texture_codec_devtest.py` | validação de codecs PT; permanece separada do estado DDS cooked |
| `texture_upscale.py` | enhancement/publish de textura; permanece independente do cooker DDS |

A nova camada **não duplica** essas responsabilidades.

## Política de retenção

Um asset é protegido se existir qualquer evidência positiva relevante. Em particular:

```text
strong runtime root
      ↓
transitive ContractGraph closure
      ↓
dependency
```

Também protegem o asset:

- qualquer incoming/outgoing edge no dependency graph;
- presença exata no manifest do client;
- literal no source atual;
- evidência review existente;
- pertencimento a bundle `char/monster/<entity>` ou `char/npc/<entity>` quando algum membro do mesmo bundle está ligado.

### Regra especial Monster/NPC

Nunca inferir lixo a partir de grep no C++.

```text
monster catalog
  -> monster definition
  -> INX
  -> SMD / SMB
  -> material
  -> TGA / BMP / DDS
```

Se um membro desta cadeia possui ligação conhecida, o bundle físico da entidade fica protegido. Isto é deliberadamente conservador para cobrir parsers que ainda não exponham todo material/texture edge.

### Estado `ORPHAN_CANDIDATE`

Só significa:

```text
zero strong root
AND zero transitive reachability
AND zero graph edge
AND zero entity-bundle guard
AND zero monster/NPC entity-catalog membership
AND zero manifest evidence
AND zero source literal
AND zero review evidence
```

Mesmo assim:

```text
delete_authorized = false
quarantine_before_delete_required = true
```

O relatório é evidência para revisão, não uma operação de cleanup.

## Outputs

O `audit general-asset-census` passa a gerar também:

```text
pt_build/cooked_texture_evidence/result.json
pt_build/cooked_texture_evidence/entries.tsv
pt_build/asset_retention/result.json
pt_build/asset_retention/assets.tsv
```

Estes quatro artefatos também entram em:

```text
pt_build/general_asset_census/reports_bundle.zip
```

O `result.json` do General Census expõe contadores resumidos:

```text
cooked_texture_state
cooked_texture_entry_count
cooked_texture_failure_count
cooked_texture_failure_class_counts
asset_retention_state
asset_retention_asset_count
asset_retention_orphan_candidate_count
asset_retention_state_counts
```

A GUI mostra `Cooked DDS`, `Cook failures`, `Retention` e `Orphan candidates` no resumo do General Census.

## CLI

### Ler somente o estado cooked

```bash
python3 pt_asset.py --client-root /path/client audit cooked-textures
```

Manifest alternativo:

```bash
python3 pt_asset.py --client-root /path/client audit cooked-textures \
  --manifest /path/client/cooked/manifest.json
```

### Retention / orphan evidence

Como reachability usa source + server + dependency graph, o comando reutiliza o pipeline completo do General Census:

```bash
python3 pt_asset.py \
  --client-root /path/client \
  --server-root /path/server \
  audit asset-retention \
  --source-root /path/SourceCode \
  --reference-source-root /path/reference-source
```

Ou execute diretamente:

```bash
python3 pt_asset.py ... audit general-asset-census ...
```

## Summit DDS cooker V2

O cooker do Summit continua a produzir o layout determinístico:

```text
client/cooked/<logical path>.dds
```

O runtime continua a usar o source original como fallback. O manifest é auditoria/build evidence, não lookup authority.

O contrato V2 acrescenta ao `cooked/manifest.json`:

- `format=SUMMIT_TEXTURE_COOK_MANIFEST_V2`;
- todos os estados observados (`cooked`, `up-to-date`, `skipped`, `error`);
- `failure_stage`;
- `failure_class`;
- `error_type` / `error_message`;
- `source_bytes` / `source_mtime_ns`;
- `source_sha256` nos failures;
- primeiros 32 bytes em `source_header_hex` nos failures;
- failure summary por classe/stage;
- `failures[]` dedicado.

Também grava:

```text
client/cooked/failed.json
```

### Retry somente failures persistidos

```bash
python3 SourceCode/tools/cook_textures_dds.py \
  --input /path/client \
  --retry-failed
```

Ou um manifest específico:

```bash
python3 SourceCode/tools/cook_textures_dds.py \
  --input /path/client \
  --retry-failed /path/client/cooked/manifest.json
```

### Bootstrap a partir de um log antigo

```bash
python3 SourceCode/tools/cook_textures_dds.py \
  --input /path/client \
  --retry-log old_cook.log
```

Isto permite transformar um log do cooker V1 em estado persistente V2 sem recookar os milhares de assets que já estão corretos.

## Relação entre retention e cook failures

Um `cook failure` é diagnóstico do pipeline DDS, nunca evidência de asset morto.

Exemplo:

```text
Field/Iron/foo.tga
  graph-linked/reachable = yes
  cook_status = error
  failure_class = IMPLAUSIBLE_IMAGE_DIMENSIONS

=> PROTECTED_*
=> corrigir decoder/cook
=> nunca ORPHAN por causa do failure
```

Um DDS bem-sucedido também não autoriza apagar a fonte, porque o runtime Summit mantém fallback para o asset original.

## Compatibilidade

- manifest antigo V1 continua legível pelo PT Asset Tool;
- `stats` e `entries` continuam presentes no cooker V2;
- o runtime não depende dos novos campos;
- `general_asset_census` continua plan-only;
- nenhum writer/client/server permission foi ampliado.

## Recursos de catálogo já existentes e reutilizados

A integração não introduz um segundo catálogo de entidades nem um segundo manifesto de UI.
Ela reutiliza os recursos já distribuídos pelo PT Asset Tool:

- `app/data/reference/entity_catalog/monster_npc_entities_v1.json`
  - formato `PT_ENTITY_CATALOG_SEED_V1`;
  - catálogo físico de Monster/NPC;
  - `folder_root` é usado como guarda conservadora de bundle no relatório de retenção;
  - o próprio catálogo continua declarando `runtime=UNPROVEN`, portanto presença protege contra remoção, mas não prova uso runtime.
- `app/data/ui_catalog/ui_tree_summary_v1.json`
  - formato `PT_UI_TREE_EVIDENCE_V1`;
  - evidência agregada de árvore/path/folder;
  - não é usada como prova individual de uso runtime porque sua política declara `no runtime claim from path alone`.

Os dois arquivos fornecidos para esta integração correspondem byte-a-byte aos recursos já empacotados no projeto. Por isso a implementação referencia os recursos existentes em vez de criar cópias ou novas fontes de verdade.

## GUI

O workflow `Servidor -> Censo & recuperação` expõe agora uma segunda tabela, **Retenção / órfãos do client**. Ela lê `pt_build/asset_retention/assets.tsv` através da API read-only `/api/asset-retention` e permite filtrar por estado, família física e texto. A tabela mostra:

- estado de retenção;
- família;
- path físico;
- contagem incoming/outgoing de edges;
- evidência/bundle;
- estado e classe de falha do DDS quando aplicável.

A GUI não possui ação de delete/quarantine nessa superfície. `ORPHAN_CANDIDATE` continua sendo somente uma classificação para revisão.

## Integração de integridade do cooker — metadata revision 3

A revisão 3 do cooker mantém as mesmas autoridades: o DDS manifest continua
sendo build evidence e o `asset_retention` continua sendo a projeção de
reachability. A mudança é que os dois estados agora podem ser vistos juntos sem
misturar seus significados.

### Skipped válido

`status=skipped` pode significar que a imagem foi decodificada corretamente,
mas a política de DDS não exige um artefato cooked. O cooker grava
`skip_class`, `asset_integrity_state=VALID_IMAGE_POLICY_SKIPPED` e o modo de
decode legado. O PT Asset Tool importa esses campos e não conta esse asset como
failure.

### Failure + reachability

`asset_retention/assets.tsv` passa a expor `integrity_action` sem alterar o
`state` de retenção:

```text
PROTECTED_* + documented/error
  -> INVALID_REFERENCED_NEEDS_RECOVERY_OR_RUNTIME_PROOF

PROTECTED_* + unknown decode error
  -> DECODE_FAILURE_REFERENCED_REVIEW

ORPHAN_CANDIDATE + documented/error
  -> INVALID_UNREACHABLE_QUARANTINE_REVIEW

ORPHAN_CANDIDATE + unknown decode error
  -> DECODE_FAILURE_UNREACHABLE_REVIEW

skipped after valid decode
  -> VALID_DECODE_POLICY_SKIPPED
```

Nenhum desses estados autoriza delete. Em particular, um asset inválido mas
referenciado precisa ser restaurado de donor, provado como não-runtime, ou ter
seu decoder certificado; um asset inválido e sem reachability continua exigindo
quarantine/review antes de qualquer remoção.

### Outliers históricos já mapeados

A integração reutiliza o mapa existente de `rare_support`/`rare_outliers`:

- `Field/Ricarten/ch_tree1.tga`: payload HTML/IIS sob path `.tga`;
- `Effect/AssaEffect/MonsterFury/m_fury.tga`: payload zero-filled;
- `Effect/Particle/ArchivoTmp.tga`: recuperação de preview conhecida, runtime não certificado;
- `Effect/AssaEffect/force.bmp` e `Effect/sky/s.bmp`: assets históricos inválidos/sem adapter runtime certificado.

Estes itens não recebem DDS fabricado para tornar o cooker artificialmente
verde. O ContractGraph/retention decide se exigem recuperação, prova runtime ou
quarantine review.

## Root reachability revision 4 — graph-linked não significa runtime-reachable

A revisão 4 separa duas propriedades que antes apareciam juntas na projeção de
retenção:

```text
graph_linked    = existe pelo menos um ContractGraph edge incoming/outgoing
root_reachable  = existe caminho dirigido desde um strong runtime root
```

Somente `strong_paths` produzidos pelo General Asset Census são usados como
roots de runtime. Isto preserva a semântica já existente do census:

- source literals podem existir em código morto/opcional e não viram runtime root;
- presença em manifest continua evidência positiva de retenção, mas não promove
  transitivamente um componente inteiro a runtime-reachable;
- catálogo Monster/NPC continua sendo proteção conservadora, sem converter
  `runtime_status=UNPROVEN` em prova runtime.

Para assets genéricos, um ContractGraph edge isolado agora resulta em:

```text
REVIEW_GRAPH_LINKED_ROOT_UNREACHABLE
```

em vez de `PROTECTED_GRAPH_LINKED`. Isso evita que subgrafos mortos permaneçam
protegidos indefinidamente só porque seus próprios membros se referenciam.
`deletion_authorized` continua sempre `False`.

Monster/NPC mantém a política mais estrita definida para o projeto:

```text
PROTECTED_ENTITY_BUNDLE_ROOT_REACHABLE
PROTECTED_ENTITY_BUNDLE_LINKED
PROTECTED_ENTITY_CATALOG
```

Ou seja, um actor bundle com qualquer linkage conhecido continua fail-closed,
mesmo quando o componente ainda não é alcançável de uma root forte. Remoção de
monster/NPC continua exigindo ausência de linkage e revisão explícita.

### Novos campos em `asset_retention/assets.tsv`

- `graph_linked`;
- `root_reachable`;
- `root_distance`;
- `root_source_count`;
- `root_sources`;
- `root_source_evidence`;
- `incoming_edge_sources`;
- `outgoing_edge_targets`;
- `incoming_edge_details`;
- `outgoing_edge_details`.

`root_distance=0` identifica a própria strong root. Distâncias maiores são o
menor número de edges observado desde uma root forte.

### Consulta curta de um asset

Depois de executar o Censo geral/asset-retention não é necessário usar
`grep -R` sobre `pt_build`.

```bash
python3 pt_asset.py audit asset-retention-query \
  --path 'Effect/AssaEffect/MonsterFury/m_fury.tga'
```

Esse comando é read-only, não reroda o census e retorna apenas a linha persistida
(com root reachability e amostras de edges).


## Revisão 5 — runtime effect roots e revisão por componente

A revisão 5 cobre uma lacuna visível após a separação `graph_linked` /
`root_reachable`: efeitos legacy podem ser selecionados por nome lógico em C++ e só
depois resolvidos para um INI físico. Por isso, zero literal de `foo.tga` não é prova de
que uma textura de `Effect/ImageData` esteja morta.

`effect_runtime_coverage.py` faz uma promoção deliberadamente estreita:

- `StartBillRect`, `StartDestPath` e `StartBillRectPrimitive` podem fornecer INIs por
  basename; o resolver prefere `Effect/AnimationData/<nome>.ini`;
- literals `Effect/...` só são promovidos quando aparecem dentro de calls de loaders
  legacy conhecidos;
- basename ambíguo ou path físico ausente vira REVIEW witness;
- source literal isolado continua não sendo runtime root;
- nenhuma etapa escreve client/server.

O relatório fica em:

```text
pt_build/effect_runtime_coverage/result.json
```

O General Asset Census injeta os roots fortes resolvidos nessa mesma autoridade de
`strong_paths`, antes de calcular retention/closure.

### Componentes root-unreachable

Assets client com edges, mas sem caminho desde strong root, são agrupados por componente
fraco e recebem ID estável dentro de cada execução:

```text
URC-00001
URC-00002
...
```

Outputs:

```text
pt_build/asset_retention/components.tsv
pt_build/asset_retention/components.json
```

Campos por asset incluem `component_id`, `component_size`, `component_entry_nodes` e
contagens de edges externos. A intenção é revisar uma cadeia (`INI -> ASE/SMD -> texture`)
como unidade, em vez de milhares de arquivos isolados.

Importante: `component_id` é identificador de relatório, não identidade persistente de
asset e não autoriza escrita. A política permanece:

```text
graph linked + root unreachable -> REVIEW
zero linkage + zero root/evidence -> ORPHAN_CANDIDATE
ORPHAN_CANDIDATE -> nunca delete automático
```

Quarantine em massa permanece fora desta revisão até a cobertura de runtime/effects ser
considerada suficiente. Monster/NPC continua fail-closed por catálogo/bundle/linkage.
