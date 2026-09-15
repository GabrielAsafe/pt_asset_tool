# Field Metadata Editor — SPM / SPP / SPC

## Objetivo

Integrar no Design Tool a edição segura da metadata de Field observada no Summit Server sem transformar o server root em workspace gravável.

O editor está na aba **Servidor / Asset Enrichment**. Selecione `Fields` no Explorador de bundles e depois use **Abrir SPM**, **Abrir SPP** ou **Abrir SPC**.

Para criar um draft é necessário armar temporariamente **workspace/build**. Esse arm permite escrever em `pt_build`; ele **não** autoriza escrever no servidor.

## SPM — spawn/atores

SPM é texto legacy. O parser reconhece os aliases observados para:

- `ACTOR`;
- `BOSS_ACTOR`;
- `MAX_ACTOR_POS`;
- `MAX_ACTOR`;
- `DELAY`.

A UI edita o texto completo e grava somente um draft. O writer preserva o encoding detectado e normaliza o texto para o estilo de newline do source.

Validação runtime continua necessária para provar spawn, pesos, limites e timing.

## SPP — start points

O layout Summit canónico é:

- 200 registros;
- 12 bytes por registro;
- `int32 state`, `int32 x`, `int32 z` little-endian;
- tamanho total 2.400 bytes.

A UI altera registros por índice e preserva tamanho e ordem. Um SPP de 600 bytes é legado/50-record e fica bloqueado para esta superfície de autoria.

## SPC — NPCs fixos / merchants

O layout canónico observado é 100 registros × 504 bytes = 50.400 bytes.

O gate runtime real é `code != 0`. O código `0x48470070` é o `ADD_NPC` standard observado no corpus atual.

A autoria disponível é deliberadamente limitada:

1. escolher um record `ADD_NPC` conhecido como template;
2. escolher um slot não ativo (automaticamente, apenas slot totalmente blank);
3. clonar o record;
4. editar somente nome, model path, server NPC path, posição/ângulos/state;
5. zerar identidades donor-specific que não são portáveis;
6. gravar o resultado em `pt_build`.

**Não existe writer sintético-from-zero.** Campos desconhecidos de `smCHAR_INFO` continuam sem semântica justificada e não são inventados.

### Merchants

O SPC posiciona/liga o NPC fixo no Field. Shop, quest e comportamento do merchant continuam na definição `.NPC`/lógica server-side correspondente. Alterar placement no SPC não cria uma loja funcional sozinho.

## Outputs

Todos os drafts e manifests ficam em:

```text
app/pt_build/server_field_editor/<GameServer/Field/...>/
```

Cada manifest contém SHA-256 do source, SHA-256 do draft, operação e prova de `server_write_authorized=false`.
