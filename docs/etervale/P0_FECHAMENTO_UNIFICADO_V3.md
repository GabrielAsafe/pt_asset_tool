# Etervale — P0 fechamento unificado V3 (9 nov 2026)

## Escopo e condições de aprovação

Este patch acrescenta provas reais de escrita **SMD Stage0.72, SMD Model0.62, SMB e INX**, autoria por JSON em **OpenItem, Monster, NPC e Field**, aliases de tokens e um protocolo de publicação controlada com rollback. O projeto de jogo e os leitores C# não são alterados pelo instalador.

**IMPORTANTE:** o patch instala capacidades; somente os testes efetuados sobre o seu checkout, especialmente os dotnet reais, podem fechar a matriz de evidências. `reader accepted` não é certificação visual/game runtime. A aprovação em SQL descartável não é importação no banco de produção. Os 80 `unresolved refs` pré-existentes não devem ser corrigidos automaticamente ou confundidos com regressão.

### 1. Writers reais, somente staging

Execute, um comando por vez:

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_asset.py etervale p0-binary-probe --asset 'Field/Ricarten/village-2.smd' --execute --build
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.smd' --execute
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.smb' --execute
python3 app/pt_asset.py etervale p0-binary-probe --asset 'char/monster/Acero/Acero.inx' --execute
```

**SMD:** altera exclusivamente `SelfIllum` de um material em arquivo de mesmo tamanho; todos os outros bytes, inclusive Physique, UVs, área de colisão e regiões desconhecidas, permanecem idênticos. Se o parser Stage/Model não fechar, bloqueia. **Não** implementa edição arbitrária de geometria ou rigging.

**SMB/INX:** usa `smb_writer.patch_key` e `inx_writer.patch_motion` existentes. Faz alteração em offsets permitidos e mantém bytes opacos, como o bloco final do SMB de Acero. A prova C# é executada somente com `--execute`.

Os probes são intencionalmente **impublicáveis**; são alterações experimentais.

### 2. Autoria dos quatro domínios nativos

```bash
python3 app/pt_asset.py etervale p0-content-probe --auto --execute --build
```

A seleção automática procura, dentro das pastas reais `GameServer/OpenItem`, `Monster`, `NPC`, `Field`, um arquivo existente por domínio que tenha uma diretiva segura para teste. Ao falhar, informe arquivos específicos:

```bash
python3 app/pt_asset.py etervale p0-content-probe \
  --item 'OpenItem/SEU_ARQUIVO.txt' \
  --monster 'Monster/SEU_ARQUIVO.inf' \
  --npc 'NPC/SEU_ARQUIVO.npc' \
  --field 'Field/Dcave.ase.spm' --execute --build
```

O teste prepara uma receita JSON e a importa com `WorldImport` em cópias isoladas do GameServer, com SQLite baseline/candidato. Ele recusa novas referências não resolvidas e mudanças ignoradas pelo catálogo. **NUNCA publique uma receita/prova com `probe_only: true`.** O comando de plano recusa essas receitas.

### 3. Aliases e edição de conteúdos nativos intencionais

`native-content-build` agora aceita `*DELAY` mesmo quando a fonte CP949 contém `*출현간격`. Também cobre `ACTOR`, `BOSS_ACTOR`, `MAX_ACTOR_POS`, `MAX_ACTOR` e nomes lógicos de nível/preço/peso (itens) e nível/XP/defesa (monstros). Resolve para a **grafia exata já presente no arquivo**. Múltiplas ocorrências exigem `occurrence`; não inventa novas diretivas em inglês quando o importador só entende coreano.

Para uma edição intencional, utilize os comandos previamente instalados:

```bash
python3 app/pt_asset.py etervale native-content-snapshot --asset 'Field/Dcave.ase.spm'
# Edite operations no recipe JSON, por exemplo:
# {"op":"set","key":"*DELAY","values":[3,2]}
python3 app/pt_asset.py etervale native-content-build --spec 'CAMINHO_REAL_DA_RECEITA.json'
python3 app/pt_asset.py etervale native-content-verify --manifest 'CAMINHO_REAL_DO_MANIFEST.json' --execute --build
```

O `native-content-verify` deverá retornar `PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED`. Só é publicação elegível se a origem permanecer idêntica ao SHA-256 capturado, houver diferença semântica no catálogo, nenhum novo `unresolved ref`, e **nenhuma entidade nova** que exija registro de identidade.

### 4. Edição binária intencional e limitada

Para preparar um material com valor escolhido explicitamente (sem alterar jogo):

```bash
python3 app/pt_asset.py etervale p0-binary-edit \
  --asset 'char/monster/Acero/Acero.smd' --material 0 --self-illum 0.2 --execute
```

INX oferece `--motion <nome-ou-índice> --repeat N`. SMB oferece `--bone <nome> --track pos|rot|scale --key-index N --x N [--y ...]`. São edições de campos existentes com preservação binária, **não** substitutos de Blender.

### 5. Publicação manual, backup e rollback

**Não aplique candidatos experimentais ao jogo.** Apenas um arquivo intencional, com leitor C# aprovado, ou overlay JSON intencional com `WorldImport` aprovado, pode entrar no plano.

Para conteúdo nativo (não probe):

```bash
python3 app/pt_asset.py etervale p0-release-plan \
  --manifest 'CAMINHO_DO_MANIFEST.json' \
  --verification 'CAMINHO_DO_REPORT_DO_WORLDIMPORT.json'
```

Para binário editado via `p0-binary-edit --execute`:

```bash
python3 app/pt_asset.py etervale p0-release-plan \
  --binary-evidence 'CAMINHO_DO_RELATORIO_DO_P0_BINARY_EDIT.json'
```

O plano informa `plan` e `approval_sha256`. **Apenas se você decidir publicar os valores de verdade**, execute:

```bash
python3 app/pt_asset.py etervale p0-release-apply \
  --plan 'CAMINHO_EXATO_DO_PLAN.json' --approve 'SHA256_EXATO_DO_PLANO'
```

O resultado contém o `journal`. Para restaurar o arquivo anterior:

```bash
python3 app/pt_asset.py etervale p0-release-rollback \
  --journal 'CAMINHO_EXATO_DO_JOURNAL.json' --approve 'MESMO_SHA256_DO_PLANO'
```

O rollback falha de forma segura se o arquivo tiver sido modificado depois da publicação. Não executa WorldImport no banco real. Backups e journal ficam sob `app/pt_build/etervale/p0_release/`.

### 6. Fechamento e UI

```bash
python3 app/pt_asset.py etervale p0-closure-audit
python3 app/pt_asset.py etervale ui-board
bash app/pt-asset-gui
```

A UI é somente leitura e mostra P0 Writers, P0 Closure, P0 Publication e P0 Content. O gate retorna `P0_AUTHORING_GATES_PASSED_NOT_RUNTIME_CERTIFIED` **somente depois** de quatro tipos binários reais aceitos pelo C# e de alterações semânticas nos quatro domínios nativos. Isso **não significa** certificado de runtime nem que novos NPCs/monstros podem ser publicados sem a atualização dos JSONs `WorldImport/Identities` embutidos no build.

## Limites deliberados

- Não altera `Client/`, `Shared/`, leitores C#, HLSL ou assets de jogo na instalação.
- Não publica novos NPCs/monstros, porque os IDs/keys estáveis exigem revisão do registro e novo build do importer. `p0-release-plan` bloqueia entidades novas.
- Não afirma que formatos Summit `.scfg`/`.smap`/`.sres` sejam consumidos pelo runtime unificado.
- Não implementa edição genérica de vértices/Physique/tempos de keyframe nem glTF -> jogo; essas funcionalidades pertencem à adaptação gráfica posterior e necessitam provas próprias.
- Não executa validação visual/funcional do jogo em produção.
