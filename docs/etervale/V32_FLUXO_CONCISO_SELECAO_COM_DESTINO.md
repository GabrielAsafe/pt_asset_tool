# V32 — Refatoração do fluxo e ações semânticas

## UI normal

`Modelo` → `Mostrar floresta` → `Clicar` → `Alcance/raio` → `Só ocultar folhas` OU `Substituir árvore` → `Desfazer última`.
Os painéis V21–V25, V27 e V31 ficam acessíveis atrás de `Ferramentas avançadas`.
Nenhuma migração destrutiva dos dados antigos.

## Semântica

- `HIDE_LEAVES`: acrescenta os índices de faces selecionadas à máscara V31/V30;
  **não** coloca modelo novo.
- `REPLACE_TREE`: acrescenta os mesmos índices à máscara e guarda uma colocação
  `LOD0` na chave opcional `v32_replacements` do JSON V31, contendo seed, modelo,
  digest do arquivo, escala, base de vista e altura de inspeção.
- A gravação é atómica num único JSON, mantendo a intenção de substituição e a
  ocultação como uma única unidade persistida. Cada decisão V32 guarda exatamente
  as faces para permitir desfazer só a última, sem tocar nas seleções V31 anteriores.
- LOD0 é carregado exclusivamente da cache V28.1, partilhando a biblioteca com V30.
- Após refazer o preview global V30, as substituições V32 são reconstruídas.
  Registos cujo modelo já não corresponde ao hash original são ignorados com aviso.
- Não aceita seleção global para criar uma árvore: somente ilha local ou árvore
  local. Máximo de 12 instâncias extras; nunca certifica implantação no solo.

## Restrições

Base aproximada usa as coordenadas mínimas da seleção no proxy V19. Folhas sem
tronco e vegetação em paredes podem exigir ajuste no Blender. A aprovação visual
não é exportação. Não é implementado um escritor de Stage SMD nem um publicador.

## Validação

Testes: regras de estado legado, escolha de ocultar vs substituir, base/escala,
limites, desfazer, integração estática Blender, regressões V21–V31.
