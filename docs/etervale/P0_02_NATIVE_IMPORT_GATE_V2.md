# Etervale — P0/02: autoria nativa por JSON e validação sem alterar readers

## Decisão arquitetural

Os packs Summit (`.scfg`, `.smap`, `.sres`, `.sfld` etc.) **não são carregados pelo Etervale**. Este patch não muda os leitores C# e não tenta publicar esses packs. O destino de autoria para as famílias suportadas é o que `PristonTale.WorldImport` já consome: `assets/GameServer/OpenItem/*.txt`, `Monster/*.inf`, `NPC/*.npc` e `Field/*.spm`, em CP949. As estruturas binárias SPP/SPC continuam sob o editor/auditor de Fields existente, não por este fluxo textual.

A fonte de verdade de runtime continua o modelo persistido pelo `WorldImport`. O Asset Tool gera apenas um **overlay revisável** em `app/pt_build/etervale/native_pipeline/`. Nada é escrito em `Etervale-git`.

## Comandos

Trabalhe na raiz do Asset Tool:

```bash
cd "$HOME/Transferências/pt_asset_tool"

# 1. Capturar um arquivo nativo real, com hash que prende a receita à versão atual.
python3 app/pt_asset.py etervale native-content-snapshot \
  --asset 'Field/Dcave.ase.spm'

# 2. Abra o caminho 'recipe' apresentado no JSON e edite 'operations'.
# Por exemplo, uma receita para acrescentar diretiva de spawn válida:
# "operations": [{"op":"append", "key":"*DELAY", "values":[3,2]}]
# Escolha valores diferentes dos efetivos para testar mudanças semânticas.

# 3. Gerar overlay (nunca altera o GameServer).
python3 app/pt_asset.py etervale native-content-build \
  --spec '/CAMINHO/IMPRIMIDO/recipe_....json'

# 4. Planejar a verificação do manifest (sem .NET nem mutações).
python3 app/pt_asset.py etervale native-content-verify \
  --manifest '/CAMINHO/IMPRIMIDO/manifest.json'

# 5. Executar duas importações em SQLite descartável com o WorldImport REAL.
python3 app/pt_asset.py etervale native-content-verify \
  --manifest '/CAMINHO/IMPRIMIDO/manifest.json' --execute --build
```

A primeira execução com `--build` compila o `WorldImport` no checkout Etervale (cria apenas `bin/obj` de desenvolvimento, não altera readers/arquivos de jogo). Pode omitir `--build` nas seguintes se o executável já foi compilado.

O comando de verificação copia `assets/GameServer` integralmente para **dois diretórios isolados**, aplica o overlay só numa das cópias e importa cada uma para seu próprio SQLite novo sob `pt_build`. Compara contagens, referências não resolvidas e os dados das tabelas de gameplay. Ele também exige que o importador tenha efetivamente registrado os bytes das fontes e as entidades parseadas. Não são usados `--postgres` nem a base real. Os assets para motion pass apontam para um diretório vazio na sandbox: animações e materiais ficam fora desta prova.

## Esquema JSON V2

```json
{
  "format": "PT_ASSET_ETERVALE_NATIVE_RECIPE_V2",
  "files": [
    {
      "path": "Field/Dcave.ase.spm",
      "sha256": "PREENCHIDO_PELO_COMANDO_SNAPSHOT",
      "operations": [
        {"op":"append", "key":"*DELAY", "values":[3,2]}
      ]
    }
  ]
}
```

Para editar um token existente, use `{"op":"set", "key":"*레벨", "values":[22]}`. Se o token ocorrer várias vezes, indique `"occurrence": 0` (índice zero). Sem `occurrence`, a operação só é aceita quando existe exatamente uma ocorrência, evitando substituir silenciosamente múltiplos drops/ações. `delete` segue a mesma regra. `append` acrescenta uma diretiva (útil quando o parser aceita a última ocorrência). Os valores com espaço são colocados entre aspas conforme o `Tokenizer` C#.

Para criar uma nova entidade a partir de um template conhecido, use `"path":"Monster/Novo.inf"` e `"template":"Monster/Original.inf"` com o SHA-256 de **Original.inf**. É obrigatório ajustar a identidade (`*이름`) e todos os dados pertinentes; o manifesto marca a criação para revisão. Novos monstros e NPCs também exigem aprovar/adicionar uma entrada estável aos arquivos **`tools/PristonTale.WorldImport/Identities/monsters.json` ou `npcs.json`**. Eles são dados embutidos no assembly e exigem rebuild para persistir IDs estáveis. O patch não aplica essas alterações automaticamente.

## Estados da prova

- `OVERLAY_READY_REQUIRES_NATIVE_IMPORT`: texto CP949 gerado, sem validação C#.
- `PLAN_ONLY`: plano validado, nenhuma importação executada.
- `FAILED_NATIVE_IMPORT`: o `WorldImport` não conseguiu importar a fonte baseline ou candidata.
- `FAILED_NATIVE_SEMANTICS`: novas referências não resolvidas, entidade ignorada/descartada, ou nenhuma alteração nas tabelas de gameplay apesar de alteração nos bytes de entrada.
- `PASS_NATIVE_IMPORT_NOT_RUNTIME_CERTIFIED`: C# importou as duas árvores e a candidata não introduziu as falhas pesquisadas. **Não** comprova funcionamento no jogo, nem valida material, skeleton, etc.

O cartão P0 de conteúdo da UI passará a mostrar a prova nativa mais recente (quando `--execute` é utilizado). Isso **não** significa que os packs Summit se tornaram compatíveis.

## Segurança e limites

- Escrita exclusivamente em `pt_build`; cópias completas de GameServer com teto de 100 mil arquivos e 2 GiB, falhando antes da importação caso ultrapasse.
- Recusa symlinks, caminhos absolutos ou com `..`, caracteres de controle, extensões e pastas inesperadas e mudança no hash da origem.
- Não executa scripts arbitrários de receitas JSON; diretivas encadeadas `*연결파일` não podem ser alteradas pelo editor.
- Recusa sobreposição case-insensitive ambígua e duplicatas; mantém comentários, diretivas desconhecidas e finais de linha.
- Só os tipos textuais acima estão integrados à autoria V2. Packs de comércio, quests, economia, traduções e mapas modernos exigem adaptadores específicos para os contratos efetivamente consumidos pelo jogo — não basta recompilar os formatos Summit.

## Limitação importante da entrega

Os testes Python do patch foram executados com dados sintéticos e um importador simulado para a comparação SQLite. **Não foi possível executar .NET com GameServer real neste ambiente.** A evidência semântica final será o relatório gerado pelo comando `native-content-verify --execute --build` no seu computador.
