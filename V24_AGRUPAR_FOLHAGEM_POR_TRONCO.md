# Etervale V24 — Juntar folhagem a troncos, sem tocar no SMD

## Contexto

A V23.1 reconstruiu 103 propostas a partir do `Field/forest/fore-1.smd` (SHA source-locked), com 56 troncos candidatos e 47 propostas de folhas sem tronco. A separação em objetos Blender foi aprovada (`objects=103`) mas vários objetos ainda são fragmentos de folhagem. Uma face pertence à **única malha original** no Stage 0.72; as coleções V23/V24 contêm **cópias descartáveis**, não componentes binários publicados.

## V24

- **Lê**, não reescreve, os JSON V22 e V23.
- Usa os *troncos candidatos da V23 como âncoras*, procura grupos sem tronco com material de folhagem compatível, proximidade horizontal e altura local semelhantes.
- **Autoassociação intencionalmente restrita:** só para fragmentos pequenos muito perto de um único tronco, sem outro tronco concorrente. Dois grupos com tronco **nunca** são fundidos automaticamente.
- Grupos maiores ou ambíguos permanecem intactos e, quando viável, apresentam o tronco próximo como **sugestão** (necessita confirmação humana).
- **Agrupar → Criar grupos no Outliner → Selecionar e rever → Associar sugerida, se correta**.
- Existe pré-visualização GLB individual, usando o campo `.glb` da V23; preserva visualmente a malha original e nunca publica no cliente.
- A associação manual conserva todas as faces e regista os identificadores das propostas V23 de origem.

Saída separada: `app/pt_build/etervale/stage072_semantic_v21/maps/6cd0d6e8c7586543.v24_groups.json`. O arquivo é bloqueado por SHA da fonte e assinatura do plano de faces V23, contém o mapeamento completo das 103 origens, e não permite publicação de runtime. Verificações recusam faces duplicadas, desaparecidas ou reaproveitadas em dois grupos. A ação **Agrupar** não sobrepõe um plano V24 já existente, protegendo associações manuais e decisões de revisão.

## Instruções Blender

1. Abrir `python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd`.
2. Painel `N → Etervale → V24 · Juntar folhas por tronco`.
3. Primeiro reconstruir a V23 se ainda não existir plano. **Não clicar Detetar V22**: as 103 propostas já estão guardadas.
4. Clicar `1. Agrupar propostas V23`, e depois `2. Criar grupos no Outliner`.
5. Selecionar cada grupo, observar faces + tronco. Um grupo com folhas apenas e `Tronco próximo` pode ser associado manualmente usando `Associar à árvore sugerida`. Após a associação, clicar novamente em `Criar grupos no Outliner` para recriar as cópias.
6. Se houver um GLB **de árvore** válido, preencher `Modelo GLB` e fazer prévia da árvore selecionada. GLBs `village-2*.glb` são modelos de mapa, não árvores.

## Limitações e riscos

A heurística não pode provar que uma folha pertence à copa de um dado tronco; especialmente com árvores muito próximas, rochas com relevo, copa no terreno ou materiais repetidos. A contagem V24 poderá continuar maior que o número real de árvores — isso é **esperado** enquanto houver casos duvidosos, e preferível a apagar geometria incorretamente. Não certifica colisões, renderer, animações, materiais PBR nem exportação. Todos os testes foram offline; validação Blender 5.2 está pendente.

A V24 usa cópias das faces com UVs, cores e materiais. O comando original V20/V21 continua a abrir um `.blend` temporário; **não guardar o Stage original** nem remover a sua geometria a partir do Outliner. O JSON V24 persiste entre sessões. A V24 não altera os assets de jogo, os previews Stage ou as decisões de revisão das versões anteriores.
