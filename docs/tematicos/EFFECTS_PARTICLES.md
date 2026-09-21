# Effects / Particles `.part`

## Estado atual

A aplicação possui suporte de desenvolvimento para os scripts `.part` usados pelos efeitos de partículas:

- inspeção lexical e perfil semântico;
- ocorrência editável por chave;
- draft transacional;
- diff/verify;
- mutation corpus gate;
- aba **Partículas** integrada na UI principal;
- serviço first-party compartilhado (`pt_asset_tool/particle_service.py`);
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


## Integração na UI principal

O Particle Editor não é vendor nem uma aplicação externa. O domínio `.part` é first-party e a UI principal expõe: busca, inspect, edição em staging, verify de draft, geração de plano e preview Blender. O launcher histórico `pt_part_ui.py` permanece apenas como compatibilidade e reutiliza o mesmo `particle_service`, evitando duas implementações funcionais divergentes.

O preview usa o mesmo resolver central de Blender do diagnóstico `python3 pt_asset.py dependencies`: `PT_BLENDER_COMMAND` tem prioridade, depois Blender nativo e então Flatpak. Assim o diagnóstico e a execução não podem discordar sobre qual launcher usar. **Gerar plano** não exige Blender; só **Gerar preview Blender** exige o runtime externo. Fontes `.part` legadas com braces inconsistentes podem gerar preview aproximado com warning, mas continuam bloqueadas para authoring.
