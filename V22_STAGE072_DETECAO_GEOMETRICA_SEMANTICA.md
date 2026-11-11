# Etervale V22 — Detetor geométrico de objetos no Blender (piloto)

## Decisão e estado

**Piloto de classificação semântica, não de publicação.** V22 acrescenta propostas automáticas à V21.1 sem substituir malhas, texturas, colisões, SMD/SMB/INX ou código do cliente. Executar primeiro em `Field/forest/fore-1.smd`.

Os 58 mapas Stage 0.72 foram previamente aprovados em **transporte e proxy** no Blender V19, não certificados visualmente nem em Texture Paint. V22 **não altera** esse marco e não declara que uma proposta é um objeto completo, mesmo que tenha classe `ARVORE`.

## Fontes e eixos

- A geometria analisada é a do **proxy V19** no Blender, onde **Z é altura**.
- O Stage original tem **Y vertical**; a saída `game_anchor` converte o ponto local `(X, Y, Z)` de volta para o jogo e a proposta fica marcada como **não certificada**.
- As regiões da V21 são **exemplos fracos** e **não** são transformadas automaticamente em árvores: 118 regiões não representam necessariamente 118 objetos.
- Os 257 materiais da análise anterior quase não tinham nomes descritivos. O classificador usa palavras explícitas quando existem, ou exemplos V21 apenas se o material tiver várias marcações substanciais e sem indícios de arquitetura.

## Método

1. Ler topologia e geometria do proxy descartável. Calcular centro, orientação, área e limites por face no espaço Blender.
2. Aproximar o terreno local a partir de faces predominantemente horizontais voltadas para cima. Isto **não prova** piso caminhável nem colisão.
3. Filtrar materiais com evidência de vegetação, pedra ou fogo; descartar pisos horizontais e arquitetura com marcadores fortes de nome.
4. Agrupar faces **espacialmente**, mesmo quando não estão ligadas (como *foliage cards*). Impor diâmetro máximo ao grupo para reduzir o risco de unir uma floresta inteira.
5. Classificar candidatos por altura, largura, distância ao chão e material. Sem evidência de material/rotulagem, **não** inventar que uma elevação é uma pedra ou árvore.
6. Criar propostas com `PENDING`, confiança limitada, lista de faces do SMD, materiais, caixa 3D e âncora em coordenadas do jogo.
7. No Blender, destacar as faces da proposta ativa em uma **malha temporária wire-only**, sem tocar no proxy.
8. O utilizador pode aprovar, rejeitar, marcar revisão, trocar categoria, anotar e ajustar posição. `APPROVED` significa **aprovado para revisão semântica**, não aprovação para o runtime.

## Interface e comandos

Instalar V22 incremental sobre V21.1 e iniciar o mesmo comando:

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

Blender: painel `N > Etervale > Classificação V21 > V22 · Detetor automático`.

- `Distância de agrupamento`: iniciar com **1.5**, ajustar entre 0.4 e 4.0 quando há grupos partidos ou fundidos.
- `Máximo de propostas`: 120 por execução. Se truncado, analisar um subconjunto de cada vez; a V22 não realiza *split* manual automático.
- `Detetar elementos no mapa`: produz candidatos, não os aprova nem esconde geometria.
- Selecionar uma proposta para ver a **malha de arame laranja**. Verificar fisicamente se abrange uma única árvore ou arbusto antes de aprovar.
- `Aprovar` / `Rejeitar` / `Precisa de revisão`: regista a decisão sem alterar os assets.
- A edição de categoria, nota, rotação, escala e deslocamento atua **apenas no JSON** de propostas.

O histórico e as marcações V21 permanecem em:

```
app/pt_build/etervale/stage072_semantic_v21/maps/<id>.json
```

As novas propostas ficam em:

```
app/pt_build/etervale/stage072_semantic_v21/maps/<id>.v22_proposals.json
```

A identidade está ligada a `source_sha256`, ao mapa e à topologia. Ao repetir a análise, decisões anteriores são mantidas quando o conjunto de faces corresponde (exatamente ou com sobreposição >= 90%). Alterações de geometria obrigam a nova revisão.

## Limitações obrigatórias

- Classificação **heurística**, não aprendizagem de IA nem deteção garantida de objetos completos.
- Planos de copa podem representar apenas parte de uma árvore. Tronco e folhas com materiais diferentes podem ficar separados.
- Terrenos em diferentes níveis, cavernas, telhados, árvores justapostas e vegetação embebida em malhas arquitetónicas causam falsos positivos ou agrupamentos incompletos.
- Não classificar `WALL` como colisão real. O algoritmo não o interpreta como árvore ou rocha apenas por ser alto.
- Não usar `APPROVED` para suprimir faces, substituir visual, exportar SMD, instanciar GLB no runtime, gerar partículas ou publicar material PBR.
- A primeira execução real do botão V22 precisa ser confirmada no **Blender 5.2 da máquina do utilizador**. Os testes executados sem Blender cobrem lógica, formatos, segurança e o código do painel.

## Critérios para V23

Validar manualmente pelo menos 10 propostas de árvores, 5 arbustos e 5 casos negativos (paredes, rochas, chão); registar taxa de candidatos corretos e fragmentação. A seguir acrescentar agrupamento tronco + copa e ajuste da âncora por terreno, antes de integrar modelos externos Poly Haven e bibliotecas ambientCG.
