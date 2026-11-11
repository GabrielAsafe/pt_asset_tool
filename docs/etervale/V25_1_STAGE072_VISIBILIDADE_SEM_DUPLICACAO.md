# V25.1 — Stage oculto e limpeza das cópias de inspeção

## Causa

O `.blend` de Stage 0.72 contém duas malhas com funções diferentes:

- `PT_STAGE072_STAGE`: fonte nativa com coordenadas originais do jogo, mantida como evidência e para transporte/roundtrip.
- `PT_STAGE072_VIEW_STAGE`: proxy V19 centrado e com eixos corrigidos, para trabalho visual no Blender.

A V25 permitia que a malha de origem ficasse visível após manipular a visibilidade no fluxo de isolar/restaurar pares, mostrando um *segundo mapa* longe do proxy. Isso não significava que o asset do jogo tivesse sido modificado.

## Correção

- `_hide_native_stage_sources` encontra a malha original **somente** através da referência `pt_stage072_source_object` no proxy e do SHA da fonte, em vez de ocultar nomes genéricos.
- Oculta e deseleciona as malhas de origem ao inicializar a V25, isolar um par, restaurar e gerar objetos de inspeção. Não altera vértices nem materiais.
- Novo botão **Ocultar Stage original duplicado** para corrigir manualmente a vista da sessão.
- Novo botão **Limpar cópias temporárias** para remover apenas as coleções de inspeção `PT_V23_ARVORES_INSPECAO_SO_COPIA`, `PT_V24_ARVORES_AGRUPADAS_INSPECAO`, `PT_V25_PAR_COPA_TRONCO_SO_INSPECAO` e `PT_V25_ARVORES_APROVADAS_SO_INSPECAO`.
- **Não apaga** a fonte `PT_STAGE072_STAGE`, o proxy `PT_STAGE072_VIEW_STAGE`, as coleções GLB ou os JSON V21–V25.

## Limitações

O objetivo é corrigir a visibilidade da V25, não reconstruir árvores novas nem certificar uma publicação. A pré-visualização real do Blender 5.2 deve ser validada pelo utilizador. A criação de cópias pequenas de faces por árvore continua a ser opcional, por inspeção — não é feita nova cópia integral do mapa.

## Comportamento esperado

```text
PT_V25_NATIVE_SOURCE=HIDDEN_ON_START changed=1
PT_V25_NATIVE_SOURCE=HIDDEN changed=1 source_mesh_unchanged=true
PT_V25_CLEANUP=PASS objects_removed=N source_mesh_unchanged=true json_preserved=true
```

O valor `changed=0` é normal se a malha original já estiver oculta.
