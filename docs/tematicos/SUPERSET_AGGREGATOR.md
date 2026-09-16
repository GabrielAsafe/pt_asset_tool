# Summit Superset Aggregator — 0.17.0

> Estado corrente: veja `../CURRENT_STATUS_2026-09-14.md` e `../release/RELEASE_1_READINESS.md`.

## Objetivo

O Superset Aggregator transforma o catálogo multi-source e o Asset Contract Graph num build de **staging auditável**. Ele não tenta substituir o cliente/servidor Summit nem fazer um `cp -r` cego. O objetivo é reunir o maior conjunto possível de assets e dados úteis, mantendo proveniência, variantes e segurança.

O fluxo é:

```text
Summit target + donors + source evidence
                |
                v
       Contract / path resolver
                |
                v
       Aggregation planner
        /       |       \
      KEEP   RECOVER   REVIEW
                |
                v
         pt_build overlay
                |
                v
       manifest + validation
```

Nenhum comando desta família escreve no cliente, servidor ou source C/C++.

## Fontes conhecidas

A aplicação aceita roots configurados ou explicitamente passados no CLI. Na workstation Summit, a descoberta limitada conhece:

### Cliente

- Target Summit: `Summit Tale Client Full/cliente`
- `OFFICIAL`: `/path/to/donor/client`
- `PT_EU`: `/path/to/reference/client`

### Servidor

- Target Summit: `Servidor`
- `PT_EU_SERVER`: `/path/to/reference/server`
- `EXMACHINA_SERVER`: `/path/to/alternate/server`

### Source

- Summit current source: `/path/to/current/source`
- EU reference source: `/path/to/reference/source`

A ordem dos donors é a ordem de preferência quando o target está ausente e existem variantes divergentes. O conteúdo Summit existente sempre vence no superset genérico.

## Modos

### 1. `aggregate player-classes`

Agrega apenas conteúdo alcançável pelos contratos das 10 classes:

- Mechanician
- Fighter
- Pikeman
- Archer
- Knight
- Atalanta
- Priestess
- Magician
- Assassin
- Shaman

Mantém separação entre:

- core obrigatório;
- variantes opcionais de body/head/costume/armor;
- gaps opcionais;
- conflitos;
- blockers de runtime/source.

Saída:

```text
pt_build/aggregate/player_classes/all/
├── client_overlay/
├── reference_variants/
├── manifest.json
├── validation.json
├── provenance.tsv
├── recover.tsv
├── variants.tsv
├── optional_gaps.tsv
├── conflicts.tsv
└── missing.tsv
```

### 2. `aggregate client-superset`

Percorre todos os donor clients e monta um overlay com paths runtime/data que não existem no Summit.

Classificação principal:

- `MODEL_OR_MOTION`: `.smd`, `.smb`, `.inx`
- `TEXTURE_OR_UI`: `.bmp`, `.tga`, `.dds`, `.png`, `.jpg`, ...
- `AUDIO`: `.wav`, `.ogg`, `.mp3`, `.mid`
- `EFFECT`: `.part`
- `CLIENT_DATA`: formatos data/config conhecidos
- `AUTHORING_SOURCE`: `.ase`, `.max`, `.4ase`, `.psd`, `.blend`
- `ARCHIVE`
- `TOOLING_OR_BINARY`
- `NOISE`
- `UNKNOWN`

Authoring, archives e extensões desconhecidas são preservadas em `reference_only/`, não promovidas automaticamente ao runtime.

### 3. `aggregate server-superset`

Faz o mesmo para dados do servidor, com normalização de namespaces conhecidos.

Normalizações atuais:

```text
PT_EU game-server/GameServer/... -> GameServer/...
ExMachina GameServer/OpenItem - Copia/... -> GameServer/OpenItem/...
```

`login-server/` é preservado como referência até existir contrato seguro para o namespace Summit.

São excluídos do overlay:

- `LogItemData/`
- logs
- saves/userdata/warehouse
- temporários/backups
- executáveis, DLLs, object files e tooling

Isto evita confundir estado runtime com assets/dados distribuíveis.

### 4. `aggregate summit-superset`

É o modo recomendado para o objetivo atual. Executa:

1. contrato das 10 classes;
2. superset geral do cliente;
3. superset geral do servidor;
4. verificação de cobertura das recuperações de classe pelo superset genérico;
5. relatório combinado.

Saída:

```text
pt_build/aggregate/
├── player_classes/all/
├── client_superset/all/
│   ├── client_overlay/
│   ├── reference_variants/
│   └── reference_only/
├── server_superset/all/
│   ├── server_overlay/
│   ├── reference_variants/
│   └── reference_only/
└── summit/all/
    ├── manifest.json
    ├── validation.json
    └── reports_bundle.zip
```

`reports_bundle.zip` contém somente relatórios pequenos; não duplica os assets materiais. É o artefacto preferido para feedback/debug.

## Ações do planner

### `KEEP_TARGET`

O path já existe no Summit. O superset genérico não substitui silenciosamente o conteúdo existente por um donor.

### `RECOVER`

O target não possui o path e existe exatamente uma fonte física apropriada.

### `RECOVER_DEDUPED`

Mais de um donor possui o path, mas todos têm o mesmo SHA-256. Uma única cópia é materializada.

### `RECOVER_PREFERRED_VARIANT`

O target não possui o path e os donors divergem. A fonte prioritária é usada no overlay e todas as variantes são preservadas em `reference_variants/`.

### `ARCHIVE_REFERENCE_ONLY`

O conteúdo é útil para investigação/authoring, mas não é promovido automaticamente ao runtime.

### `EXCLUDE_NON_DEPLOYABLE`

Ruído, state, logs ou tooling conhecido. É registado, mas não copiado.

### `TARGET_CASE_COLLISION`

O target Linux contém dois paths que colidem no namespace case-insensitive esperado pelo runtime Windows. Requer revisão.

### `DONOR_CASE_COLLISION`

Um donor contém múltiplos paths casefold-equivalentes com conteúdos diferentes. Requer revisão.

### `SOURCE_FILE_MISSING`

O índice apontou para candidato que deixou de existir durante o run. Fail-closed.

## Proveniência e hashes

Para cada recuperação, `provenance.tsv` regista:

- path canónico;
- categoria/deployability;
- source escolhido;
- path físico original;
- SHA-256;
- tamanho;
- quantidade de candidatos;
- quantidade de conteúdos distintos;
- destino de staging;
- verificação hash pós-cópia.

O cache de hashes é persistente em:

```text
~/.cache/pt_asset_tool/asset_hashes.sqlite3
```

Ele não faz parte da FULL release.

## Estados combinados

O `summit-superset` separa prontidão física e runtime:

### `READY`

O superset de assets passou e os contratos de runtime das classes estão prontos.

### `ASSET_SUPERSET_READY_RUNTIME_BLOCKED`

Os assets recuperáveis estão resolvidos, mas há blocker de source/runtime. Atualmente Assassin/Shaman podem cair aqui enquanto `MAX_JOBNUM`, registry/handlers e demais migrações não forem concluídos.

### `REVIEW_REQUIRED`

Existe colisão, source desaparecido ou falha de integridade que impede considerar o staging seguro.

## Segurança

Garantias da 0.17.0:

- target client não é escrito;
- target server não é escrito;
- source C/C++ não é escrito;
- staging fica exclusivamente sob `app/pt_build/aggregate/`;
- path traversal é rejeitado;
- cópia materializada é re-hasheada;
- conflitos não são sobrescritos silenciosamente;
- authoring e unknown client extensions não são promovidos automaticamente;
- server runtime state é excluído.

## CLI

Run combinado recomendado:

```bash
cd app
python3 pt_asset.py aggregate summit-superset
```

Plan-only:

```bash
python3 pt_asset.py aggregate summit-superset --plan-only
```

Runs individuais:

```bash
python3 pt_asset.py aggregate player-classes
python3 pt_asset.py aggregate client-superset
python3 pt_asset.py aggregate server-superset
```

Roots explícitos continuam suportados:

```bash
python3 pt_asset.py \
  --client-root "/path/client" \
  --server-root "/path/server" \
  aggregate summit-superset \
  --source-root "/path/source-current" \
  --reference-source-root "/path/source-eu" \
  --donor-client "OFFICIAL=/path/official" \
  --donor-client "PT_EU=/path/pt-eu-client" \
  --donor-server "PT_EU_SERVER=/path/pt-eu-server" \
  --donor-server "EXMACHINA_SERVER=/path/exmachina"
```

## GUI

Na aba Servidor / Asset Enrichment:

1. configure client/server/source roots se a descoberta automática não os encontrar;
2. configure donor clients e donor servers, um `LABEL=PATH` por linha;
3. clique **Salvar fontes**;
4. use **Agregar Summit completo (staging)**;
5. acompanhe o job;
6. consulte `Summit superset` e o `reports_bundle.zip`.

## Como integrar novos providers

O agregador não deve conhecer regras específicas de Item/Field/Monster diretamente. Novas entidades devem publicar contratos/grafos e o planner continua genérico.

Próximas closures previstas:

```text
ITEM
OpenItem -> item catalog -> DorpItem -> model -> textures -> icon -> drop/shop/quest

FIELD
field id -> SMD/textures/minimap/title -> SPP/SPM/SPC -> NPC/monster references

MONSTER/NPC
server definition -> model/config -> textures -> motion root -> sounds/effects
```

A regra de extensão é: **o provider prova o que a entidade precisa; o agregador decide de onde obter e como preservar variantes**.
