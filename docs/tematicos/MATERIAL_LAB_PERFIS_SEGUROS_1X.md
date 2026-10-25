# Material Lab — perfis seguros para restauro por IA 1× (Summit / Priston Tale)

**Objetivo:** avaliar paredes, pedra, chão, madeira, metal e personagens já ampliados a 4×, mantendo sempre a resolução. **Não faz upscale nem publica no cliente.** O DEDXT é opcional, adquirido à parte; não é incluído no patch.

## O que muda

`--profile safe-game-v1` é **opcional** (a CLI existente continua em `legacy` para não quebrar operações anteriores). Quando ativo, a seleção deixa de usar um único `--denoise` para tudo:

| Material inferido | Ação predefinida | Observação |
|---|---|---|
| Pedra / paredes (`stone`) | IA 1× | Requer `--model-config` com pesos e SHA-256 válidos |
| Terreno / chão (`terrain`) | IA 1× | Não é upscale |
| Madeira, metal, tecido, NPC/pele | IA 1× | Sujeito a revisão manual |
| Folhagem (`foliage`) | Ignorar | Preservar contornos e alpha |
| UI / máscara / céu / FX / luzes / mapas técnicos | Ignorar | Bloqueio de segurança mesmo com uma regra manual |
| Desconhecido | Ignorar | Não adivinhar sem rever padrões |

**Proteção adicional para nomes antigos (2026-10-24):** diretórios compostos com
`Effect`/`Particle`/`Sprite` (por exemplo `image/Sinimage/AssaEffect/.../ground_ring.bmp`)
são bloqueados antes de interpretar `ground` como terreno. Ficheiros com o sufixo
ambíguo `_m` (por exemplo `Field/dungeon/sand_m.bmp`) ficam por rever; o sufixo
sozinho não prova que sejam máscaras. Estas proteções não podem ser contornadas
com regras de perfil. Um ficheiro aprovado manualmente pode continuar a ser
inspecionado fora do perfil automático, sem publicar no cliente.

A classificação é **heurística**, baseada em nomes e partes dos caminhos. Não demonstra a semântica do material no jogo. O programa escreve a decisão e o motivo no `manifest.json`. Nomes opacos podem exigir regras por pasta/ficheiro. Mesmo quando o perfil escolhe IA, **não garante melhoria visual**: a comparação antes/depois continua obrigatória.

**Segurança:** o perfil não altera a origem, não chama o Real-ESRGAN 4×, não ativa parallax e não publica materiais; escreve apenas numa pasta nova. A opção `--maps off` é recomendada até serem identificados materiais compatíveis com o renderizador.

## 1. Inventário sem processamento, desde a instalação atual

```bash
cd "$HOME/Transferências/pt_asset_tool/app"
export PYTHONDONTWRITEBYTECODE=1
CLIENT="$HOME/Área de Trabalho/summit/cliente"
MODEL_CONFIG="$HOME/Transferências/material_lab_barba/dedxt.json"
SCAN="$HOME/Transferências/material_lab_scan.json"
python3 pt_asset.py texture-material profile-scan \
  --input-root "$CLIENT" --model-config "$MODEL_CONFIG" --all > "$SCAN"
python3 - "$SCAN" <<'PY'
import json,sys
from collections import Counter
obj=json.load(open(sys.argv[1], encoding='utf-8'))
print('Texturas encontradas:',obj['texture_count'])
print('Ações:',obj['action_counts'])
for kind in ('stone','terrain'):
    selected=[r['source'] for r in obj['decisions'] if r['action']=='ai' and r['material']==kind]
    print(f'\n{kind}: {len(selected)} candidatas; primeiras 12:')
    for name in selected[:12]: print(' ',name)
PY
```

O inventário não carrega modelos nem edita imagens. Se não aparecerem candidatos de chão/paredes, é preferível classificar manualmente algumas texturas por regras (abaixo), em vez de processar todos os ficheiros desconhecidos.

## 2. Escolher até três texturas de chão e três de parede

A partir do inventário, cria um lote pequeno de avaliação sem copiar texturas do cliente:

```bash
cd "$HOME/Transferências/pt_asset_tool/app"
CLIENT="$HOME/Área de Trabalho/summit/cliente"
SCAN="$HOME/Transferências/material_lab_scan.json"
MODEL_CONFIG="$HOME/Transferências/material_lab_barba/dedxt.json"
OUTPUT="$HOME/Transferências/material_lab_paredes_chao_$(date +%Y%m%d_%H%M%S)"

mapfile -d '' -t SELECTED < <(python3 - "$SCAN" <<'PY'
import json,sys
from pathlib import Path
obj=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
chosen=[]
for material in ('stone','terrain'):
    candidates=[r['source'] for r in obj['decisions'] if r['action']=='ai' and r['material']==material]
    chosen.extend(candidates[:3])
    print(material,':',len(candidates),'candidatos,',len(candidates[:3]),'selecionados',file=sys.stderr)
for path in chosen:
    print('Selecionado:',path,file=sys.stderr)
    sys.stdout.buffer.write(path.encode('utf-8')+b'\0')
PY
)

if [ "${#SELECTED[@]}" -eq 0 ]; then
    echo 'SEM_CANDIDATOS: rever nomes / criar regras específicas antes do teste'
else
    INCLUDES=()
    for p in "${SELECTED[@]}"; do INCLUDES+=(--include-exact "$p"); done
    python3 pt_asset.py texture-material run \
      --input-root "$CLIENT" --output-root "$OUTPUT" \
      --model-config "$MODEL_CONFIG" --profile safe-game-v1 \
      --maps off "${INCLUDES[@]}"
    echo "Resultado: $OUTPUT/review_001.html"
fi
```

O DEDXT **não** faz parte do patch. O seu `--model-config` deve apontar para o `.pth` correto, com o SHA-256 verificado, tal como no teste da pasta `Barba`. Cada execução exige uma pasta de saída nova.

Para abrir sem depender de `xdg-open`, usar o `python3 -m http.server 8123 --bind 127.0.0.1 --directory "$OUTPUT"` e aceder a `http://127.0.0.1:8123/review_001.html`. O servidor local serve os previews, não altera o cliente. Encerrar com Ctrl+C.

## 3. Regras de material para nomes opacos (opcional)

Exemplo de `~/Transferências/perfis_summit.json`:

```json
{
  "format": "PT_TEXTURE_MATERIAL_PROFILES_V1",
  "actions": {"foliage": "skip", "unknown": "skip"},
  "rules": [
    {"pattern": "*/dungeon/ground*.bmp", "material": "terrain", "action": "ai"},
    {"pattern": "*/walls/stone*.tga", "material": "stone", "action": "ai"},
    {"pattern": "*/special_decals/*", "action": "skip"}
  ]
}
```

Regras são testadas pela ordem declarada (primeira correspondente vence), sem diferenciação de maiúsculas/minúsculas. São padrões glob sobre o caminho **relativo à pasta `--input-root`**. Usar padrões específicos para evitar falsos positivos; nomes `mask`, `sky`, `ui`, `fx`, `normal`, `height`, `light` etc. permanecem bloqueados mesmo que uma regra peça `ai`.

Usar `--profile-config "$HOME/Transferências/perfis_summit.json"` tanto no `profile-scan` como no `run`. O manifesto guarda o SHA-256 desta configuração; não é possível alterar retroativamente a origem/candidato sem invalidar a auditoria.

## 4. Interpretação, validações e limites

- Uma alteração RGB maior **não prova** qualidade superior; comparar rugosidade, costuras UV, transições, aspeto da superfície e artefactos exagerados.
- As texturas já ampliadas não recuperam automaticamente detalhes que nunca existiram. DEDXT 1× é um restauro de artefactos de compressão, não um novo desenho da textura.
- Uma imagem `skipped_profile` não foi processada. Verificar contagens e motivos no manifesto.
- Antes de uma eventual exportação, a revisão e auditoria por SHA-256 continuam obrigatórias. Exportar candidatos **não é** publicar no jogo.
- O efeito de normal/height/parallax e eventuais mesh fixes requerem suporte e testes específicos do cliente Summit; não estão certificados.
- Para percursos UI, máscaras e personagens com transparência crítica, manter candidatos separados e não substituir ficheiros originais sem inspeção.

### Testes automatizados

```bash
cd "$HOME/Transferências/pt_asset_tool"
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  -W error::DeprecationWarning \
  app/dev_tests/test_texture_material_profiles.py \
  app/dev_tests/test_texture_restoration_phase2.py \
  app/dev_tests/test_texture_material_pipeline.py \
  app/dev_tests/test_texture_material_finalization.py
```

Após aplicar um patch ao código, regenerar a referência e o manifesto **apenas depois de verificar alterações locais**:

```bash
python3 docs/validation/generate_source_api_reference.py
python3 app/update_snapshot_manifest.py --current-root .
bash VERIFY_PACKAGE.sh
```

Se o manifesto enumerar caches, `.serena`, `.gitnexus` ou outras ferramentas locais, preservar essas pastas fora do projeto antes da atualização, como no processo anterior.

## Revisão de segurança — perfis v1 (24/10/2026)

Foi detetado um falso positivo no teste real de `Field/Fall_Game/floor_002lightingmap.bmp`: um mapa de iluminação não é um diffuse map, mesmo que o nome comece por `floor`. A heurística `lightmap`/`lightingmap`/`normalmap`/`heightmap`/`occlusion` agora bloqueia automaticamente estes nomes compostos, inclusive com regras manuais. Os nomes `grass`, como `Field/Slab/a2_grass_01.bmp`, deixam de ser tratados automaticamente como chão difuso e passam a `foliage: skip`, por precaução com alpha e cutouts. É uma classificação conservadora: pode haver relva de solo sem alpha, mas só deve ser processada depois de inspeção manual.

Os lotes anteriores de seis candidatos foram apenas experiências offline; **não os publiques** e não voltes a fazer upscale. Repetir primeiro `profile-scan` e confirmar que `floor_002lightingmap.bmp` e `a2_grass_01/02.bmp` aparecem com ação `skip`.
