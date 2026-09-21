# Management Legacy + Legacy Authoring Python

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

**Data:** 2026-09-21  
**Status:** guia operacional atual para a integração Management/World Closure/Authoring.

## 1. Objetivo

Esta integração substitui o uso operacional de ferramentas históricas onde o formato/workflow já foi provado. O princípio é:

```text
EXE histórico → evidência estática
source/corpus  → contrato
contrato       → parser/writer Python
writer         → stage/transação verificada
```

Nenhum executável histórico precisa ser iniciado.

## 2. O que veio do Management

### PriTaTor

Evidência para:

- Monster search/edit;
- EXP/gold/drop lines;
- map actor membership;
- boss membership;
- spawn rate/times;
- item search/add-remove workflow;
- NPC workflow;
- backup/restore workflow.

### NPCManager

Evidência para `Field/*.spc` e campos visíveis de NPC fixo. A autoria atual usa o ABI/corpus SPC provado pelo projeto, não o EXE como writer.

### ItemDistributor / scanners / admin tools

Fornecem evidência de workflow, mas userdata/warehouse continuam fora do authoring de assets.

### ItemEditor / Editor de Monstros

A existência do workflow é confirmada. Internals nativos não provados não são usados como autoridade de writer.

## 3. Taxonomia PriTaTor

A classificação de code usa longest-prefix e preserva ambiguidades. Ela ajuda navegação/diagnóstico, mas não substitui a identidade runtime `sITEM`.

Exemplo:

```text
WA121 → Weapons / Axe
```

## 4. Contrato runtime sITEM

O adapter expõe os nomes C++ corretos, incluindo:

- `code`;
- `ItemFilePath`;
- `Class`;
- `DorpItem`;
- `SetModelPosi`;
- `SoundIndex`;
- `WeaponClass`.

Paths derivados:

```text
image/Sinimage/Items/<ItemFilePath>/it<DorpItem>.bmp
image/Sinimage/Items/DropItem/it<DorpItem>.ASE
```

Isso é usado para closure física e identity gating.

## 5. Auditoria Management

A auditoria é suporte à autoria. Com roots configurados, cruza:

```text
SPM → Monster → item code → OpenItem → sITEM → DorpItem → client assets
```

Sem `server_root`, pode operar apenas em modo contrato/evidência.

## 6. World Closure Explorer

O explorer não é um editor. Ele responde “o que está conectado, presente, ausente ou ambíguo?”.

### Itens

Mostra code, runtime identity e presença do ícone/drop model esperado.

### Maps/SPM

Mostra metadata de campo e referências resolvidas.

### Monster/NPC

Mostra definição e resolução correspondente.

## 7. Ponte para Authoring

Ao selecionar uma linha:

```text
ITEM row    → ITEM / EDIT
SPM row     → SPM / EDIT
MONSTER row → MONSTER / EDIT
NPC row     → NPC / EDIT
```

O path exato é transportado para o editor. Em ITEM, a resolução vem do census de OpenItem; duplicidade fica bloqueada.

## 8. Authoring pipeline

```text
Inspect
→ Spec
→ Stage
→ Validate
→ Publish
→ Verify
→ Runtime review
→ Restore
```

### Inspect

Lê o source target e produz identidade/hash/layout/fields.

### Spec

JSON Python-native que descreve apenas a mudança pretendida.

### Stage

Gera overlay/manifest em `pt_build`. Não escreve target.

### Publish

Publica somente o bundle validado, com backup/hash/replace atómico/post-verify.

### Restore

Restaura o backup da própria transação e recusa drift desconhecido.

## 9. ITEM

### CREATE

Exemplo:

```json
{
  "kind": "ITEM",
  "mode": "CREATE",
  "path": "GameServer/OpenItem/WA121.txt",
  "fields": {
    "name": "Created Axe",
    "code": "WA121",
    "price": 1000
  }
}
```

O code precisa existir na runtime table source-verificada.

### EDIT

```json
{
  "kind": "ITEM",
  "mode": "EDIT",
  "path": "GameServer/OpenItem/WA121.txt",
  "expected_sha256": "...",
  "patch": {
    "set": {"name": "New Axe", "price": 999}
  }
}
```

Unknown lines são preservadas.

## 10. MONSTER

```json
{
  "kind": "MONSTER",
  "mode": "EDIT",
  "path": "GameServer/Monster/Cuepy.inf",
  "patch": {
    "set": {"experience": 777},
    "drops": [
      {"percentage": 70, "items": ["WA121", "WC108"]},
      {"percentage": 30, "money": [1, 10]}
    ]
  }
}
```

O writer suporta item drop, money drop, NoItem, extra drop, dialogs e linked file.

## 11. NPC

```json
{
  "kind": "NPC",
  "mode": "EDIT",
  "path": "GameServer/NPC/Shop.npc",
  "patch": {
    "shops": {
      "weapon": ["WA121", "WS210"],
      "defence": ["DA112"],
      "etc": []
    },
    "dialogs": ["Hello player"]
  }
}
```

## 12. SPM

Operações:

```text
ADD_ACTOR
REMOVE_ACTOR
ADD_BOSS
REMOVE_BOSS
SET_DIRECTIVE
```

Diretivas SET:

```text
MAX_ACTOR_POS
MAX_ACTOR
DELAY
```

Boss pode receber `slave_count` e lista de `hours`.

## 13. SPP

Canónico:

```text
200 records × 12 bytes
<state:int32, x:int32, z:int32>
```

Somente índices válidos e layout canónico são aceitos.

## 14. SPC

Canónico:

```text
100 records × 504 bytes
```

Operações:

```text
ADD
REPLACE
REMOVE
```

O record é construído pelo writer nativo do projeto.

## 15. CLI

```bash
python3 pt_asset.py legacy-authoring capabilities
python3 pt_asset.py legacy-authoring inspect --kind ITEM --path GameServer/OpenItem/WA121.txt
python3 pt_asset.py legacy-authoring stage --spec spec.json
python3 pt_asset.py legacy-authoring publish --confirm 'APPLY ASSET BUNDLE'
python3 pt_asset.py legacy-authoring restore --confirm 'RESTORE ASSET BUNDLE'
```

## 16. GUI

Na aba Management Legacy:

1. escolha no World Closure ou informe kind/path;
2. Inspect;
3. ajuste template/spec;
4. arme BUILD;
5. Stage;
6. revise manifest;
7. arme ASSET DEPLOY;
8. Publish;
9. valide em runtime;
10. Restore se necessário.

## 17. Por que `REVIEW` e authoring podem coexistir?

`REVIEW` pertence à closure/auditoria. O writer possui gates próprios.

Um item pode ter:

```text
OpenItem OK
sITEM OK
icon PRESENT
DropItem ASE MISSING
→ REVIEW
```

Se a definição OpenItem está identificada e o code runtime é válido, ela pode continuar editável. A ausência do ASE ainda fica visível e não é escondida.

## 18. Boundaries

Bloqueado:

- novo code runtime `sITEM`;
- userdata/warehouse;
- internals não provados de executáveis nativos;
- target ambíguo;
- non-canonical SPP/SPC;
- source drift;
- publish/restore sem confirmação;
- write fora da transação tipada.

## 19. Regra operacional

Não use os executáveis históricos para “completar” uma operação que o Asset Tool bloqueou. Um bloqueio significa que falta contrato/evidência para aquele write. Recupere/prove o formato primeiro e então promova o writer com testes/corpus/roundtrip.
