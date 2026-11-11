# Etervale Environment Modernizer — milestones de aceitação

M0 — **Blender visual, CONCLUÍDO como prova de conceito**: seleção por textura/face, ocultação, substituição por árvores LOD, desfazer. Não é certificado no jogo.

M1 — **Commit e rollback no cliente**: validar SHA e origem de `Field/forest/fore-1.smd`; executar testes transacionais existentes (Asset Bundle e workspace); ensaio de deploy em clone; validar um artefacto Stage 0.72 próprio para publicação; carregar o mapa no Etervale; confirmar materiais, alpha, geometria, colisões, performance; restaurar backup; verificar SHA do original. Só concluído se todos estes critérios passarem.

M2 — **Placement de objetos novos**: colocar, mover, rodar, escalar e fixar a chão/parede no Blender; persistir posição em coordenadas do jogo; carregar no renderer; fazer rollback.

M3 — **Categorias de ambiente**: pedras, pilares, arbustos, chão, materiais PBR. Classificação por textura + componente geométrico, sem supor que a textura representa sempre um só objeto.

M4 — **Objetos compostos e dinâmicos**: casas, portais e outras estruturas. Preservar colisão, transparência, navegação, interação e scripts.

M5 — **Fogo e efeitos visuais**: substituir imagens/cards de chamas por efeitos de partículas/animação suportados pelo renderer; perfis de LOD, comportamento no jogo e rollback.

## Regra de segurança

Nenhuma gravação no SMD original sem manifesto com source SHA, artefacto válido, backup verificado, comparação pré-deploy, confirmação explícita, pós-verificação e restore testado. Distinguir sempre transação tecnicamente válida de comportamento correto no jogo.
