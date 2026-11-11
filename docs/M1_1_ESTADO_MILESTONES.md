# Etervale Environment Modernizer — Estado após M1.1

| Marco | Critério | Estado |
|---|---|---|
| M0 | Substituição visual, seleção e rollback Blender | **PASS (prova de conceito)** |
| M1-A | Stage original e carregamento cliente | **PASS** (relatórios do utilizador) |
| M1-B | Publish/rollback de Stage diferente em clone | **PASS em fixture sintética; pendente no Stage real** |
| M1-C | Máscaras V30/V32 reproduzidas no cliente, colisão preservada | **Pendente de teste no cliente** |
| M1-D | Instâncias modernas LOD0 carregadas no renderer | **Não implementado neste kit** |
| M2 | Colocação de novos objetos no Blender/jogo | Pendente |
| M3 | Pedras, pilares e outros materiais | Pendente |
| M4 | Portais, casas e objetos com comportamento | Pendente |
| M5 | Fogo por efeitos do jogo | Pendente |

M1.1 altera apenas um campo `material` (16 bits) e a referência ao TexLink
(32 bits) de cada face oculta. Não remove triângulos nem usa a geometria moderna
no Stage. A modificação do jogo passa pelo Asset Bundle existente e é reversível.

**O teste em runtime ainda NÃO foi executado.** No clone sintético, 51 testes
relacionados com Stage, transações, regressões e M1.1 passaram.
