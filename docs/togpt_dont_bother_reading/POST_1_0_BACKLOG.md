# Backlog pós-Release 1.0

## Mixed Physique — certificação física

Status na Release 1.0: **`NOT_CERTIFIED / OUT_OF_SCOPE`**.

Esta decisão retira Mixed Physique do gate de Release 1.0. Não converte a feature
em PASS e não remove o código existente. O pipeline sintético/candidate permanece
preservado e fail-closed para trabalho futuro.

### Quando retomar

Retomar somente depois da Release 1.0, quando existir uma amostra real/autoritativa
com contexto suficiente para provar o comportamento.

### Evidência necessária para certificar no futuro

1. asset Model0.62 Mixed Physique real e provenance conhecida;
2. skeleton/config context autoritativo;
3. import rigid + static por objeto;
4. edit/build/reimport sem drift fora do alvo;
5. validação de geometria, normals, materials, Physique e transforms;
6. teste manual do usuário dentro do jogo;
7. somente depois, promoção explícita da capability de `NOT_CERTIFIED` para `CERTIFIED`.

### Segurança

Até essa futura certificação:
- não anunciar suporte físico Mixed Physique;
- não promover writer Mixed para produção;
- não inferir skeleton/context por heurística;
- não transformar ausência de representative em PASS.
