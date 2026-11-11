# Etervale V30 — Cobertura experimental de folhas, árvores e paredes

## Problema confirmado no `Field/forest/fore-1.smd`

- V29: 56 grupos com tronco, 3.711 faces mascaradas, 43 grupos sem tronco excluídos.
- V24 (mesmo SHA-256 do Stage): 99 grupos = 56 com tronco e 43 só folhagem.
- V30 completa: 99 instâncias LOD0 (enquanto nenhum grupo tiver sido rejeitado/aprovado como ligação V25), 4.817 faces mascaradas — mais 1.106 que a V29.
- As 43 regiões só de folhas **não são árvores certificadas**: podem ser arbustos, copas duplicadas, ou vegetação na parede. O botão V30 é intencionalmente experimental.

## Mudanças

1. O ensaio V29 continua disponível, inalterado: apenas 56 grupos com tronco.
2. Novo botão V30 **Testar todos grupos LOD0 (rever)**. Inclui regiões de folhagem sem tronco, mas não altera quaisquer aprovações V25/V26 ou assets do jogo.
3. Cada instância partilha a mesma biblioteca LOD0 preparada pela V28.1, sem copiar 99 vezes a geometria no ficheiro `.blend`.
4. A máscara Geometry Nodes temporária é aplicada ao **único proxy V19** e inclui todos os grupos selecionados. O proxy pode ser restaurado com o botão já existente. As 4.817 faces são apenas do plano semântico existente: mais folhas fora dele podem continuar visíveis.
5. A V30 remove cópias temporárias criadas para inspeção V23/V24/V25/V27, que de outra forma continuariam a mostrar folhas antigas. Os JSON de classificação e as decisões são preservados.
6. Opcionalmente, para os 43 grupos sem tronco, procura uma superfície aproximadamente vertical próxima numa BVH formada pelas faces não vegetais. Se a encontrar, encosta e inclina a instância nesse sentido. **Não há certificação de implantação, colisão ou de que esse grupo seja árvore.** A opção pode ser desligada.
7. O relatório `.v30_full_preview.json` inclui uma contagem diagnóstica de outras faces que usam os materiais identificados na V22 como relacionados com árvores, sem as esconder cegamente — elas podem pertencer a chão, arbustos ou paredes.

## Limitações e segurança

- **Não substitui no cliente Etervale:** sem SMD writer, sem alteração dos ficheiros do jogo, sem novas colisões, sem aprovação automática.
- Não considera que todas as folhas sem tronco são árvores: este é um **ensaio de cobertura visual**. A substituição por modelos de árvores de grupos que na realidade são arbustos deve ser corrigida depois.
- A associação à parede é um palpite geométrico, **não um ponto de fixação validado**. Pode ser necessário ajustar manualmente rotação e implantação.
- A V30 só consegue ocultar faces anteriormente identificadas. O campo `residual_suspect_material_faces` ajuda a localizar o trabalho restante sem apagar material inocente.
- 99 instâncias de `island_tree_01` LOD0 representam aproximadamente 10,19 milhões de faces desenhadas. Usar Solid para inspecionar; teste de desempenho do runtime ainda necessário.
- Uma cena Blender guardada com o modificador de ocultação é uma pré-visualização, não uma versão do cenário adequada a publicação. Clicar **Restaurar árvores antigas (V29/V30)** repõe a vista.
- Se houver associações V25 aprovadas, a quantidade de grupos pode ser inferior a 99.

## Teste no Blender

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

N > Etervale > Modernizar ambiente:
1. Selecionar `island_tree_01_1k.blend.zip` (já preparado como LOD0 pela V28.1).
2. Marcar `Ocultar árvores antigas (só preview)`.
3. Marcar `Tentar apoiar na parede` se se quiser testar a heurística de paredes.
4. Clicar `Testar todos grupos LOD0 (rever)`.
5. Analisar especificamente as 43 regiões sem tronco e as plantas nas paredes. Não aprovar alterações no jogo com base nesta inspeção.
6. `Restaurar árvores antigas (V29/V30)` para reverter.

Resultado esperado com os JSON originais e sem rejeições:

```text
PT_V30_BATCH=PASS instances=99 with_trunk=56 foliage_only_unverified=43 wall_candidates_unverified=<variável> original_faces_hidden=4817 residual_material_suspects=<variável> source_unchanged=true game_unchanged=true publish=false
```

Se persistirem folhas antigas, enviar `residual_material_suspects`, `wall_candidates_unverified` e o novo JSON `.v30_full_preview.json`. As contagens de parede e materiais só podem ser verificadas na cena Blender do utilizador.
