# P0/02 — Integração nativa de conteúdo com o Etervale

Esta entrega acrescenta autoria por JSON diretamente para o formato de arquivos de texto reconhecido pelo `WorldImport`: OpenItem, Monster, NPC e Field (SPM). **Não** altera leitores C#, não incorpora os packs binários Summit ao runtime e não toca no banco/servidor real.

## Instalação

Coloque o ZIP completo na pasta `~/Transferências/` e execute **na raiz do Asset Tool**:

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_P0_02_NATIVE_CONTENT_2026-11-09.zip" -d .
python3 patches/aplicar_p0_02_native_pipeline.py --project-root "$PWD" --dry-run
python3 patches/aplicar_p0_02_native_pipeline.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_native_pipeline.py
```

Se você preferir guardar o ZIP da entrega em outra pasta, altere apenas o caminho do `unzip`. O instalador encontra automaticamente o patch ao lado do seu próprio arquivo e aceita `--project-root`, inclusive quando extraído numa pasta aninhada.

## Fluxo — primeiro teste real

```bash
cd "$HOME/Transferências/pt_asset_tool"
python3 app/pt_asset.py etervale native-content-snapshot --asset 'Field/Dcave.ase.spm'
```

O retorno mostra o caminho de uma receita JSON em `pt_build`. No arquivo, acrescente às operações da entrada:

```json
{"op": "append", "key": "*DELAY", "values": [3, 2]}
```

Esse é um **exemplo de alteração de spawn**, não uma sugestão de publicar tais valores. Escolha um valor diferente do atual se quiser comprovar a diferença semântica. Depois:

```bash
python3 app/pt_asset.py etervale native-content-build --spec '/CAMINHO/recipe_xxx.json'
python3 app/pt_asset.py etervale native-content-verify --manifest '/CAMINHO/manifest.json'
python3 app/pt_asset.py etervale native-content-verify --manifest '/CAMINHO/manifest.json' --execute --build
python3 app/pt_asset.py etervale ui-board
```

A última etapa executa o **WorldImport real duas vezes** sobre cópias independentes do GameServer, usando bancos **SQLite descartáveis** no `pt_build`. Verifica novas referências não resolvidas, reconhecimento dos arquivos e diferenças nas tabelas de gameplay. Só a execução no seu computador prova a compatibilidade com o checkout C# atual.

Leia o manual instalado em `docs/etervale/P0_02_NATIVE_IMPORT_GATE_V2.md` para novos itens/monstros/NPCs, identidade estável e limites de certificação.

## Validação da entrega

- 61 testes Python passaram em conjunto com os 51 testes dos P0/P1 anteriores.
- Instalador verifica hashes e backup e foi ensaiado em cópia do pacote anterior.
- **Dotnet/WorldImport real não estava instalado neste ambiente:** a validação do leitor C# continua aguardando sua execução.
- Os demais domínios do antigo `Content` exigem mapeamentos específicos; o patch não declara compatibilidade automática com todos os 11 packs.
