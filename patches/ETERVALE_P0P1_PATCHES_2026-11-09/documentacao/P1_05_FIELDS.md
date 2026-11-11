# P1/05 — SPM/SPP/SPC versus WorldImport

O Etervale já possui `tools/PristonTale.WorldImport/Parsers/{SpmParser,SppReader,SpcReader}.cs`. O patch compara os contratos binários conhecidos usando os codecs existentes do Asset Tool, sem gravar no GameServer ou em banco de dados.

```bash
cd ~/Transferências/pt_asset_tool
find "$HOME/Transferências/Etervale-git/assets/GameServer" -type f \
  \( -iname '*.spm' -o -iname '*.spp' -o -iname '*.spc' \) | head
python3 app/pt_asset.py etervale field-check --asset 'Field/ARQUIVO.spp'
```

Os caminhos em `--asset` são relativos a `assets/GameServer/`. É possível repetir a flag para verificar vários arquivos. A validação confirma 200×12 bytes para SPP, 100×504 bytes para SPC, e extrai diretivas reconhecidas de SPM.

**Diferença importante:** `SpcReader` C# usa `int32` em +4 para live e lê NPC em +104; o Asset Tool historicamente considera +4 um opcode. O relatório mostra ambos os pontos de vista, mas **não** modifica leitor nem considera a interpretação idêntica sem validação. A conversão/importação real dos Fields em banco descartável continua pendente.
