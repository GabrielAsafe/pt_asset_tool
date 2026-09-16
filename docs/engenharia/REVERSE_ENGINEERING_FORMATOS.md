# PT Asset Tool — Referência de Formatos e Layouts Reversados

Este documento é uma referência rápida de estruturas físicas comprovadas no código atual. Ele deve ser lido junto do `MANUAL_DESENVOLVEDOR.md`.

> **Importante:** offsets aqui descrevem o layout já usado pelos parsers atuais. Campos não documentados continuam sendo preservados, não “livres para zerar”.

---

# 1. SMD Model0.62 / SMB common ABI

Magic:

```text
SMD Model data Ver 0.62
```

## Estruturas

| Estrutura | Tamanho |
|---|---:|
| `smDFILE_HEADER` | 556 |
| `smDFILE_OBJINFO` | 40 |
| `smMATERIAL_GROUP` | 88 |
| `smMATERIAL` | 320 |
| `smOBJ3D` | 2236 |
| `smVERTEX` | 24 |
| `smFACE` | 36 |
| `smTEXLINK` | 32 |
| `smTM_ROT` | 20 |
| `smTM_POS` | 16 |
| `smTM_SCALE` | 16 |
| `smFMATRIX` | 64 |

## `smDFILE_HEADER`

```text
0       char[24] header
24      int ObjCounter
28      int MatCounter
32      int MatFilePoint
36      int First_ObjInfoPoint
40      int TmFrameCounter
```

## `smDFILE_OBJINFO`

```text
0       char[32] name
32      int serialized_object_length
36      int serialized_object_start
```

## offsets usados em `smOBJ3D`

```text
12      lpTexLink / serialized TexLink runtime base
16      Physique pointer/presence
76      vertex capacity (writer paths)
80      face capacity (writer paths)
84      nVertex
88      nFace
92      nTexLink
172     NodeName[32]
204     NodeParent[32]
240     Tm
304     TmInvert
432     TmRotate
628     quaternion/base area (object-local path)
644     scale
656     position
684     nRot
688     nPos
692     nScale
696     rotation-frame area
1208    position-frame area
1720    scale-frame area
2232    TmFrame count/field
```

## serialized object payload order

```text
smOBJ3D
smVERTEX[nVertex]
smFACE[nFace]
smTEXLINK[nTexLink]
smTM_ROT[nRot]
smTM_POS[nPos]
smTM_SCALE[nScale]
smFMATRIX[nRot]
PhysiqueBoneName[nVertex][32]   # if Physique present
```

## `smVERTEX`

```text
int32 x,y,z,nx,ny,nz
```

Coordinates are fixed-point `/256` in the import path.

## `smFACE`

Known fields include:

```text
+0  uint16 vertex[3]
+6  uint16 material
+32 uint32 first TexLink pointer
```

## `smTEXLINK`

```text
+0   float u[3]
+12  float v[3]
+24  uint32 hTexture
+28  uint32 NextTex
```

---

# 2. smMATERIAL

```text
0    InUse
4    TextureCounter
8    smTexture[8] legacy pointers
40   TextureStageState[8]
72   TextureFormState[8]
104  ReformTexture
108  MapOpacity
112  TextureType
116  BlendType
120  Shade
124  TwoSide
128  SerialNum
132  Diffuse raw 12 bytes
144  Transparency
148  SelfIllum
152  TextureSwap
156  MatFrame
160  TextureClip
164  UseState
168  MeshState
172  WindMeshBottom
176  smAnimTexture[32] legacy pointers
304  AnimTexCounter
308  FrameMask
312  Shift_FrameSpeed
316  AnimationFrame
```

Strings são serializadas após material block com `StrLen` e pares NUL-terminated `Name/NameA`.

---

# 3. INX

## common

```text
MotionInfo base   0x18C
MotionInfo slots  512
CHRMOTION_EXT     10
```

## MODERN_172

```text
file size     95268
motion size     172
repeat         +0xA0
key_code       +0xA4
motion_frame   +0xA8
```

## LEGACY_120

```text
file size     67084
motion size     120
repeat         +0x6C
key_code       +0x70
motion_frame   +0x74
```

Cada motion começa com campos usados como:

```text
+0 state
+4 keyword1
+8 raw_start
+12 keyword2
+16 raw_end
```

Para certos records `idx >= 10`, start/end podem estar keyword encoded. Legacy clones podem manter os DWORDs de keyword em zero e frames plain.

---

# 4. SMB motion/skeleton

Usa common Model0.62 ABI.

Tamanhos de key:

```text
rotation   20 = int frame + 4 floats quaternion
position   16 = int frame + 3 floats
scale      16 = 4 ints
prevrot    64 = 16 floats
```

`TmFrameCounter` vem do file header offset 40. O evaluator usa segmentos para mapear `MotionFrame` INX ao intervalo SMB.

O parser de preservação pode aceitar trailing payload e support skeleton com parent externo; o evaluator de animação continua mais estrito.

---

# 5. Stage0.72

Magic:

```text
SMD Stage data Ver 0.72
```

## tamanhos

```text
file header         556
raw stage header 262260
map dimension        256 x 256
material group        88
material             320
vertex                28
face                  28
TexLink               32
light                 28
```

## offsets do raw stage header usados

```text
4       StageArea pointer table (256*256 uint32)
262148  AreaList
262152  AreaListCnt
262156  MemMode
262160  SumCount
262164  CalcSumCount
262168  Vertex pointer
262172  Face pointer
262176  TexLink pointer
262180  Light pointer
262184  MaterialGroup pointer
262188  StageObject pointer
262192  Material pointer
262196  nVertex
262200  nFace
262204  nTexLink
262208  nLight
262212  nVertColor
262216  Contrast
262220  Bright
262224  VectLight
262236  AreaBuffer pointer
262240  wAreaSize
262244  StageMapRect[4]
```

## StageArea encodings observados

```text
WORD16
WORD16_TRAILING_OPAQUE
DWORD32
DWORD32_TRAILING_OPAQUE
```

Cada serialized list começa com `int32 slen`, seguido de face IDs no width físico correspondente.

---

# 6. Protected TGA

Header standard TGA: 18 bytes.

Protection key:

```text
47380409101924314051647990a9c4e10021
```

Modes:

```text
FULL18
KEEP_00_16
```

Footer gate:

```text
26 bytes
TRUEVISION-XFILE.\0
```

Writer policy: preserve protected header/footer exactly, transplant only compatible body/pixel region.

---

# 7. Protected BMP

Known gate:

```text
BITMAPINFOHEADER = 40 bytes
planes = 1
compression = BI_RGB (0)
bpp = 8, 24 or 32
```

Protected family replaces/preserves proprietary first 14 bytes. Standard editable recebe um canonical `BITMAPFILEHEADER` começando em `BM`.

Row stride:

```text
((width * bpp + 31) // 32) * 4
```

Writer policy: only pixel payload comes from editable; prefix, DIB/palette/trailing baseline bytes remain byte-identical.

---

# 8. Pointer rule

Valores `uint32` serializados que eram pointers no processo legado são usados somente como **relative relocation evidence**.

Nunca dereferenciar diretamente. Exemplo TexLink:

```text
index = (ptr - serialized_base) / stride
```

O parser deve validar:

- delta >= 0;
- delta alinhado ao stride;
- index dentro do count;
- chain sem loop.

---

# 9. Unknown/reserved fields

A ausência de documentação neste arquivo significa:

```text
PRESERVE / DO NOT ASSUME
```

não:

```text
UNUSED / SAFE TO ZERO
```

## Integração Summit Server / Asset Enrichment 1.0

A arquitetura server-aware, os lifecycles excluídos, os bundles Monster/NPC/Field/Item e os gates read-only estão documentados em `docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md`. A especificação original recebida é preservada em `docs/reference/Summit_Server_Arquivos_e_Funcionamento_2026-09-04.docx`.
