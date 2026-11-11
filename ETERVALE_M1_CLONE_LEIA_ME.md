# M1 — Ensaiar commit e rollback com a pipeline existente (clone isolado)

Este kit NÃO modifica o jogo, NÃO toca nos assets originais, NÃO publica alterações V32 e NÃO substitui um teste no cliente. Executa `plan_asset_bundle`, `compile_asset_bundle`, `publish_asset_bundle` e `restore_asset_bundle` do teu PT Asset Tool, usando `fore-1.smd` como artefacto real, mas com publicação apenas numa cópia de teste.

## Instruções

Descompactar o ZIP na raiz do `pt_asset_tool` com o Blender e o cliente fechados:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_M1_CLONE_COMMIT_ROLLBACK.zip" -d .
python3 tools/m1_clone_commit_rollback.py --tool-root . --game-root "$HOME/Transferências/Etervale-git"
```

Se a primeira análise apresentar `READY_FOR_ISOLATED_TEST`, executar:

```bash
python3 tools/m1_clone_commit_rollback.py --tool-root . --game-root "$HOME/Transferências/Etervale-git" --run
```

Esperado: `CLONE_COMMIT_ROLLBACK_PASS` com estados `APPLIED_VERIFIED` e `RESTORED_VERIFIED`, hashes idênticos antes e depois. A cópia e a transação ficam em `app/pt_build/etervale/m1_clone_rehearsals/` para auditoria.

Se surgir `BLOCKED_NO_WRITES`, examina `missing_dependencies` e `plan_errors`. **Não contornar as validações**. Caso existam texturas em falta, o FIELD visual closure recusa a publicação — isso é uma descoberta útil antes do jogo.

## Carregar o Stage original no cliente

Depois do teste isolado, iniciar o cliente pelo processo já usado. Conforme o `README.md` do repositório Etervale, o comando na raiz do repositório é:

```bash
cd "$HOME/Transferências/Etervale-git"
dotnet run --project Client/PristonTale -c Release --no-build
```

Com o servidor de desenvolvimento já a funcionar, entrar na região de `fore-1.smd`. Verificar material, iluminação, colisão, logs e FPS. Este é o baseline, ainda **sem árvores modernas no runtime**.

## Critérios

- `M1A`: parser/hash/fixtures: PASS (já observado nos logs enviados).
- `M1B`: commit/rollback isolado com Stage real: PENDENTE até executar `--run`.
- `M1C`: cliente carrega o Stage original em jogo: PENDENTE.
- `M1D`: cliente carrega a versão modernizada + rollback real: BLOQUEADO — V32 só guarda decisões e instâncias de preview e ainda não há artefacto Stage compatível com o cliente.

O ensaio de `--run` usa um ficheiro de origem e de destino com os mesmos bytes. Portanto prova backups, cópia transacional e restauração verificadas por hash, mas **não prova que modificações geométricas funcionem no jogo**.
