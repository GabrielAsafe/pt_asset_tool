# Integração das ferramentas legacy `Management` — 2026-09-20

## Objetivo

O `pt_asset_tool` agora incorpora, como **evidência histórica versionada e fail-closed**, contratos recuperados do pacote original `Management(1).zip`, do reverse estático `Management_reverse_python(1).zip` e do conjunto `@Tutoriais.zip`.

Os executáveis legacy **nunca são executados** pelo asset tool. A integração usa somente hashes, configuração textual, strings/metadata já recuperadas, tutoriais e correlação com os formatos atuais do servidor/source.

## Proveniência

- `Management(1).zip`: SHA-256 `18a126f6346fedec501738eda0c65233110571a3ba130aa172a1c24e03206d6c`
- `Management_reverse_python(1).zip`: SHA-256 `0b381de0bb76d5d2587e6fb70da3c98a4d4ae01056329606b5497c61d2959200`
- `@Tutoriais.zip`: SHA-256 `90ce8941ffd85301a01767b37c390b77e0ea7806b336ad9d95388b28b5706858`
- `PriTaTor_1.8.857.exe`: SHA-256 `2ccd73fe0fee7f4aa65eaafae7a0d4921ec375211c1d0dd93342a7ddfc4b1869`
- `NPCManager.exe`: SHA-256 `9a404b7745f7d27cdcbcfa2c93863ba5da6f40a25da5fe8bd9ef1f14d09bd9d8`
- `ItemDistributor.exe`: SHA-256 `68cbe9fa73f9b57ee24dd4bddb624b7450b1adabe63a7b46c316ea5f37ca3982`

O contrato empacotado fica em `app/pt_asset_tool/contracts/legacy_management_tools.json`.

## O que foi promovido

### Taxonomia histórica de item do PriTaTor

`PriTaTor.Config.txt` prova uma classificação operacional por prefixos. O asset tool agora pode classificar códigos como:

- `WA121` → `Weapons / Axe`
- `DA118` → `Defence / Armor`
- `DA223` → `Defence / Robe`
- `WS224` → `Weapons / Sword`

A resolução usa **longest-prefix**. Prefixos historicamente ambíguos continuam ambíguos; por exemplo `SP` aparece tanto em Quest Items quanto Event Items e não é arbitrariamente escolhido.

Essa classificação é evidência histórica de authoring/navegação. Ela **não substitui** a tabela runtime recuperada do source (`item_catalog.json`). Um código só ganha identidade runtime `SOURCE_VERIFIED` se estiver nessa tabela.

### PriTaTor: closure mapa → monstro → drop

Strings estáticas e os tutoriais confirmam o workflow:

`GameServer/Field/*.spm` → actor → `GameServer/Monster/*.inf` → códigos de item/drop → `GameServer/OpenItem/*.txt` + `.zhoon`.

A nova auditoria reconstrói essa cadeia com os parsers atuais do projeto e reporta:

- actors SPM resolvidos/ambíguos/não resolvidos;
- candidatos de código de item encontrados em Monster INF;
- presença do OpenItem correspondente;
- taxonomia PriTaTor e presença no catálogo runtime atual;
- referências `.zhoon` ausentes;
- visão agregada de item codes por mapa.

Nenhum arquivo de servidor é alterado.

### NPCManager

O assembly original confirma um editor `Field SPC` com os campos históricos `Name`, `ID`, `X`, `Y`, `Z`, `Angle`, `Enabled` e operações Load/New/Add/Remove/Save.

Isso passa a ser evidência histórica do workflow usado pelo pipeline `new-character --role NPC`. Não é usado para substituir o contrato Win32 100x504 já derivado do source: o layout binário exato continua source/corpus-derived, enquanto o NPCManager confirma o **workflow e significado operacional**.

### Item writer

O writer `item.definition.txt` continua source-strict. Ele agora anexa `legacy_management_category` ao metadata de compilação. O bundle ITEM também reporta a categoria histórica quando classificável.

O antigo `Editor de Itens.exe` é nativo e possui pouca evidência interna recuperável. Portanto a sua existência **não autoriza** novos offsets/estruturas, `DorpItem` ou mutação binária inventada.

## Novos comandos

### Ver resumo dos contratos legacy

```bash
python3 app/pt_asset.py legacy-management summary
```

### Classificar um item

```bash
python3 app/pt_asset.py legacy-management item-code WA121
```

### Verificar um diretório original `Management`

```bash
python3 app/pt_asset.py legacy-management verify \
  --management-root /caminho/Management
```

A verificação compara SHA-256; nenhum `.exe` é iniciado.

### Cruzar Management + tutoriais + servidor atual

```bash
python3 app/pt_asset.py \
  --server-root /caminho/servidor \
  audit legacy-management \
  --management-root /caminho/Management \
  --tutorial-root /caminho/@Tutoriais
```

O relatório é escrito em:

`pt_build/devtest/legacy_management/result.json`

Sem `--server-root`, o comando funciona em modo `CONTRACT_ONLY` e ainda verifica Management/tutoriais.

## Fronteiras de segurança mantidas

Não foram promovidos para writer de produção:

- layout interno do `Editor de Itens.exe`/`Editor de Monstros.exe`;
- mutação de `DataServer/userdata/*.dat` ou warehouse `.war`;
- formato original da fila binária do ItemDistributor;
- qualquer gramática de shop NPC inferida somente por regex;
- novos item IDs ausentes da tabela runtime recuperada do source.

Códigos encontrados em NPCs são reportados como **candidate shop item refs**, não como relação certificada, até existir gramática do source ou roundtrip de corpus real.

## Impacto nos pipelines existentes

- `audit server-items`: ganhou classificação histórica PriTaTor por código.
- `asset_compiler item.definition.txt`: metadata inclui categoria legacy sem alterar bytes produzidos.
- bundle `ITEM`: adiciona warning informativo de categoria legacy; continua exigindo runtime code table.
- `new-character NPC/MONSTER`: plano registra qual workflow histórico corrobora o caminho (`NPCManager SPC` ou `PriTaTor SPM/Monster`).
- não houve alteração da autorização de publish/restore.

## Próximos gates

1. Rodar `audit legacy-management` contra o server real e guardar o relatório.
2. Comparar os candidatos NPC-shop com a gramática real do `GameServer/NPC` no C/C++ source.
3. Localizar no source o `DorpItem`/item visual catalog para fechar o `NEW ITEM BUNDLE` sem usar offsets inventados.
4. Somente depois promover authoring adicional de item/shop/drop para writer transacional.

## Item runtime visual contract recovered

O source snapshot contém 1.819 linhas `sITEM(...)` em `item_catalog_recovered.inc`, exatamente a mesma contagem do contrato `item_catalog.json`. A comparação de todas as 1.819 linhas confirmou igualdade dos valores, mas revelou aliases históricos com nomes semânticos imprecisos no JSON V1. O adaptador `item_runtime_catalog.py` preserva compatibilidade e expõe os nomes reais do construtor C++:

- `item_position` (V1) -> `Class`;
- `last_category` (V1) -> `DorpItem`;
- `class_flags` (V1) -> `SetModelPosi`;
- `class_id` (V1) -> `SoundIndex`;
- `kind_id` (V1) -> `WeaponClass`.

O source também prova os paths de consumo de `DorpItem`: `image/Sinimage/Items/<ItemFilePath>/it<DorpItem>.bmp` para ícone e `image/Sinimage/Items/DropItem/it<DorpItem>.ASE` para modelo de chão. Isto é exposto como evidência/closure esperada; **não promove escrita automática do catálogo cliente**.
