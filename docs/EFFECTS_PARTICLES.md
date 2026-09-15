# Effects / Particles `.part`

## Estado atual

A aplicação possui suporte de desenvolvimento para os scripts `.part` usados pelos efeitos de partículas:

- inspeção lexical e perfil semântico;
- ocorrência editável por chave;
- draft transacional;
- diff/verify;
- mutation corpus gate;
- UI local;
- preview Blender visual.

## Preview Blender

Fluxo atual:

```text
.part source ou draft
  → plano semântico determinístico
  → Blender headless
  → .blend + PNGs
  → pt_build
```

A certificação do preview é **`BLENDER_PREVIEW_APPROXIMATE`**. Ele serve para inspeção e iteração visual; não prova equivalência com blend/timing/billboard/event semantics do runtime Summit.

O bridge possui limites de complexidade e timeout/process-group kill para evitar Blender órfão. Texturas legacy são resolvidas de forma case-insensitive; referências não resolvidas continuam visíveis como warning.

## Segurança

Nenhum `.part` do client é alterado. Todos os outputs permanecem em `pt_build`.
Publish/runtime certification continuam gates separados.
