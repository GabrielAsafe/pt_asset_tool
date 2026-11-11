# Etervale — M1.1: primeira alteração REAL do Stage dentro do jogo

**O que faz:** aplica as máscaras guardadas na V30 e V31/V32 à **renderização do
`Field/forest/fore-1.smd`**. Para cada face que pode ser alterada sem modificar a
classificação de colisão/água/gelo, troca o material por um material já existente que
o renderer não desenha e limpa apenas a referência de TexLink dessa face. **Não mexe
nos vértices, coordenadas, UVs da tabela, texturas, colisões, luzes ou áreas.**

**O que ainda NÃO faz:** carregar as árvores LOD0 modernas no cliente. Guarda uma lista
de instâncias previstas em `planned_models_not_yet_in_game.json`, com
`rendered_in_game=false`. No primeiro teste no jogo, é esperado que a vegetação
antiga desapareça **sem que as árvores 3D modernas já apareçam**. O carregamento
3D é a etapa seguinte, não está aqui apresentado como concluído.

## 1. Instalar o kit (não altera o jogo)

Fecha o cliente Etervale antes de qualquer operação com `--publish-game` ou
`--restore-game`.

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_M1_1_STAGE_REAL_COMMIT_ROLLBACK.zip" -d .
```

Este kit apenas adiciona `tools/m1_real_stage_delta.py`, documentação e testes;
não modifica os módulos existentes do PT Asset Tool ou os JSON de classificação.

## 2. Pré-teste de leitura

```bash
python3 tools/m1_real_stage_delta.py --tool-root . \
  --game-root "$HOME/Transferências/Etervale-git"
```

Esperado: `READY_FOR_STAGE_BUILD`, `game_assets_written: false`.

## 3. Commit e rollback em clone, com ficheiro realmente ALTERADO

```bash
python3 tools/m1_real_stage_delta.py --tool-root . \
  --game-root "$HOME/Transferências/Etervale-git" --clone-test
```

Esperado: `CLONE_MODIFIED_STAGE_COMMIT_ROLLBACK_PASS`,
`clone_publish_state=APPLIED_VERIFIED`,
`clone_restore_state=RESTORED_VERIFIED`, e SHA de `output_sha256` **diferente**
do original `df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62`.

Se surgir `BLOCKED_UNSAFE_FACES`, `BLOCKED_BUNDLE_PLAN` ou `FAILED`, **pára** e envia
o JSON/log. Não contornar o teste.

## 4. Commit experimental no cliente real — só após o PASS do clone

**Fecha o cliente antes de executar.** Esta é a primeira operação que muda
`Etervale-git/assets/Field/forest/fore-1.smd`, usando a pipeline
`asset_compiler` / `asset_bundle_deploy` que já existe, com backup da transação.

```bash
python3 tools/m1_real_stage_delta.py --tool-root . \
  --game-root "$HOME/Transferências/Etervale-git" \
  --publish-game --confirm PUBLICAR_STAGE_EXPERIMENTAL
```

Esperado: `GAME_PUBLISHED_VERIFIED`; guarda o relatório/transação no `pt_build`.
Verifica que o hash mudou:

```bash
sha256sum "$HOME/Transferências/Etervale-git/assets/Field/forest/fore-1.smd"
```

**Reabre o cliente** para não usar um Stage em cache e entra na área `fore-1`.
Deves notar ausência das faces de vegetação antigas selecionadas. A contagem
`faces` no log pode continuar a ser **35.519** porque as faces existem no formato,
mas estão associadas a um material invisível. As colisões devem comportar-se como
no original. **Não esperes ainda árvores modernas nesse local.**

## 5. Rollback para o Stage original

Fecha o cliente e executa:

```bash
python3 tools/m1_real_stage_delta.py --tool-root . \
  --game-root "$HOME/Transferências/Etervale-git" \
  --restore-game --confirm RESTAURAR_STAGE_ORIGINAL

sha256sum "$HOME/Transferências/Etervale-git/assets/Field/forest/fore-1.smd"
```

O SHA restaurado tem de ser **exatamente**
`df138775e3b2d15f35e330f2368f7e6e15376af1dd563932cfa5ef100258dc62`.
`GAME_RESTORED_VERIFIED` prova a reversão pelo mecanismo transacional existente.

## Limites e segurança

- Não executar `--clone-test` enquanto um Stage experimental estiver publicado;
  o script exige o SHA original para preparar o clone.
- Se não existir material invisível compatível com uma face, recusa publicação
  do ensaio completo. Não altera a colisão para forçar a ocultação.
- O modelo LOD0 de 300 mil vértices **não é serializado dentro do SMD Stage 0.72**.
  As instâncias previstas são apenas metadados para futura integração com o renderer.
- Não existem builds do cliente ou testes Blender 5.2 executados nesta máquina.
  O teste de execução real é no teu Etervale.
- A publicação recusa alvo com SHA inesperado, manifestos fora da pasta da
  transação e atualizações concorrentes. Não usar `--force`.

## Testes unitários

```bash
PYTHONPATH=app python3 -m pytest -q tests/test_m1_real_stage_delta.py
```
