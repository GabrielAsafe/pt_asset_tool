# ETERVALE V31.1 — Cliques mais fáceis e estabilidade da pré-visualização

**Requer a V31 instalada.** O instalador confere os hashes antes de escrever, cria backup e recusa alterações inesperadas.

## Instalação (com Blender fechado)

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V31_1_REVISAO_LEVE_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v31_1_revisao_leve.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v31_1_revisao_leve.py --project-root "$PWD"
PYTHONPATH=app python3 -m pytest -q app/dev_tests/test_etervale_environment_v31_1_stability.py
```

Se aparecer `SOURCE_FILE_CONFLICT`, **não forces**. Envia a mensagem de conflito para construirmos um patch sobre o teu ficheiro local.

## Testar

```bash
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

Em **N → Etervale → Modernizar ambiente → V31**:

1. Executa o teste global da V30 com ocultação dos originais se ainda não estiver ativo. A V30 volta a aplicar as 1.781 faces extra guardadas no JSON V31.
2. Deixa **Ocultar 3D novo ao selecionar** ativado (predefinição).
3. Mantém **Tolerância clique 10 px**; experimenta 16 px se as folhas forem pequenas ou 0 se precisar de precisão exata.
4. Clica **Clicar perto da face restante**, seleciona uma folha antiga e observa o destaque leve.
5. Só confirma a ocultação se o destaque corresponder à região certa.
6. Clica em **Mostrar árvores 3D novamente** para comparar as posições das novas árvores LOD0.

As árvores modernas não são apagadas ao entrar no modo leve: apenas a visibilidade em viewport é alternada. Não há nova cópia completa do Stage.

## Conservação de estado e limites

- O patch **não altera** o teu `.v31_residuais.json` nem as decisões V21–V30. SHA de Stage obrigatório.
- As máscaras visuais V31 são incrementadas sem voltar a construir Geometry Nodes a cada confirmação.
- A geometria de destaque é apenas wireframe, sem cópia de texturas/UVs.
- **Não valida nem altera o jogo** (SMD, colisões, UVs e cliente inalterados).
- **Não foi possível executar Blender Flatpak 5.2 neste ambiente**; os testes disponíveis são Python e inspeção estática da integração.
- O modo leve pode reduzir a carga da GPU, mas não descarrega os modelos da memória e não garante que um crash devido ao driver/Blender desapareça.

Se voltar a crashar, guarda o último terminal e qualquer ficheiro `*.crash.txt` criado pelo Blender. Estes ajudam a distinguir crash de GPU, memória ou bug nativo.
