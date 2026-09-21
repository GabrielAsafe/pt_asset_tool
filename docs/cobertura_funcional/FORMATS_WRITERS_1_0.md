# PT Asset Tool R14 1.0.0 — Formatos, Parsers e Writers

<!-- PT_MANUAL_LEGACY_AUTHORING_2026-09-21 -->

Este guia resume a superfície de formato suportada. O detalhe histórico/reverse-engineering permanece em `REVERSE_ENGINEERING_FORMATOS.md` e no `MANUAL_DESENVOLVEDOR.md`.

## Model0.62 (`SMD Model data Ver 0.62`)

Famílias físicas tratadas pela 1.0:

- static;
- rigid Physique;
- object-local transforms;
- materiais/TexLinks multilayer;
- referências de textura;
- rigid contexts via INX/model-info/LOD/skeleton.

Writers/candidates relevantes:

- static authoring/roundtrip;
- rigid authoring candidate e rare-rigid policies;
- material writer;
- object-local existing-key writer;
- TexLink/UV roundtrip.

Mixed Physique real permanece fora da certificação de produção 1.0; o tool contém synthetic/devtest/candidate paths para pesquisa fail-closed.

## Stage0.72 (`SMD Stage data Ver 0.72`)

Suporte:

- parse/corpus;
- StageArea;
- materiais e texturas;
- normals e provenance de normal;
- UV roundtrip;
- geometry roundtrip com atualização de estruturas derivadas;
- preview Blender;
- Texture Paint em cópias privadas;
- writer de material/geometry em artefactos de build.

## INX

O pipeline cobre variantes observadas Modern 172 e Legacy 120, MotionInfo, LinkFile/model-info contexts, no-op preservation e edição allowlisted de MotionInfo em cópia.

Comandos principais:

- `validate inx-roundtrip`;
- `write inx-motion`;
- `audit inx-writer-corpus`;
- `audit inx-writer-edit-corpus`.

## SMB

Suporte para tracks existentes de rot/pos/scale/PrevRot, segmentação/frames e source-side semantic evaluation. O writer não insere/remove keys em `write smb-key`; edita key existente em cópia.

## Texturas

### BMP protegido

O codec identifica prefix14 exact/variant e mantém capability separada de target-content readiness.

### TGA legacy/não-standard/protegido

O corpus reconhece variantes legacy/protected. Payloads estruturalmente inválidos (por exemplo HTML de erro ou arquivo zero-filled) são classificados como **target-content invalid**, não como falha do codec.

## `.part`

A ferramenta oferece parse lexical/semântico, drafts, mutation corpus e preview Blender `BLENDER_PREVIEW_APPROXIMATE`. O preview não prova equivalência completa de timing/blend/billboard/event semantics do runtime.

## Field server metadata

### SPM

Texto legacy com aliases observados para ACTOR/BOSS_ACTOR/MAX_ACTOR_POS/MAX_ACTOR/DELAY. O Legacy Authoring suporta CREATE/EDIT, ADD/REMOVE actor, ADD/REMOVE boss e SET_DIRECTIVE. EDIT preserva encoding/newline detectados.

### SPP

Layout Summit canónico certificado na superfície de autoria: 200 records × 12 bytes (`state,x,z` int32 LE) = 2400 bytes. Legacy Authoring edita records por índice e preserva tamanho. Layouts diferentes ficam bloqueados.

### SPC

Corpus canónico: 100 records × 504 bytes. Legacy Authoring suporta CREATE e EDIT com ADD/REPLACE/REMOVE de records fixos via writer nativo `build_spc_record`. Layout/slot incompatível permanece fail-closed.
\n## Legacy text definitions (OpenItem / Monster / NPC)\n\nA camada `legacy_authoring.py` possui writer source-preserving para definições textuais existentes. Ela detecta encoding/newline, substitui apenas tokens suportados e preserva diretivas desconhecidas.\n\nPatch kinds de EDIT publicados pelo Asset Bundle Deploy:\n\n- `LEGACY_TEXT_PATCH` — `.txt`, `.inf`, `.npc`;\n- `LEGACY_SPM_PATCH` — `.spm`;\n- `LEGACY_SPP_PATCH` — `.spp`;\n- `LEGACY_SPC_PATCH` — `.spc`.\n\nCREATE usa os contracts nativos do Asset Compiler:\n\n- `item.definition.txt`;\n- `character.monster.inf`;\n- `character.npc.npc`;\n- `field.spawn.spm`;\n- `field.startpoints.spp`;\n- `field.fixed_npc.spc`.\n\n### ITEM runtime boundary\n\nOpenItem CREATE/EDIT é permitido somente quando o item code pertence à runtime table source-verificada. O authoring não registra novo code em `sITEM`.\n\n### Publish\n\n`stage` gera overlay/manifest em `pt_build`. `publish` é transacional, exige `APPLY ASSET BUNDLE`, compara hashes do target, cria backup e verifica os bytes pós-write. `restore` exige `RESTORE ASSET BUNDLE` e bloqueia drift externo.\n
## ASE e outros

ASE aparece como authoring/reference em várias cadeias de Field/Enrichment, mas não recebe automaticamente a mesma autoridade de writer dos formatos certificados acima.

## Regra para novos writers

Parser → corpus → no-op preservation → witness controlado → negativos/fail-closed → Blender/human review quando aplicável → policy/certification. Nenhuma hipótese de formato deve saltar diretamente para writer de produção.
