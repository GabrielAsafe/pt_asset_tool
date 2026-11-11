# Etervale V26 — Modernização de Ambiente (UI unificada)

A V26 é incremental sobre a V25.1 e não altera assets do cliente.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V26_ENVIRONMENT_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v26_environment.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v26_environment.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_environment_v26.py
```

Não aplicar se aparecer SOURCE_FILE_CONFLICT. O instalador faz backup e valida SHA-256.

## Fluxo

```bash
python3 app/pt_environment.py --inventory
python3 app/pt_environment.py --map Field/forest/fore-1.smd
```

No Blender abre `N → Etervale → Modernizar ambiente`. Seleciona uma árvore, clica `1. Isolar árvore`, escolhe um dos modelos `.blend.zip` na lista e clica `2. Comparar modelo novo`. Ajusta escala e opcionalmente clica `3. Aprovar substituição`.

O modelo é lido da pasta `AssetsForAutomaticSubstitution` e descompactado SOMENTE em `app/pt_build/etervale/environment_v26/asset_cache/`, com validação de segurança e hash. Nunca é alterado o arquivo de entrada.

Os JSON V22–V25 são reutilizados; não voltar a detetar. A V26 usa os grupos V24 com tronco e as ligações aprovadas da V25, se existirem. Ficam de fora os grupos apenas de folhas ainda incertos.

## O que foi refatorizado

- Cinco painéis avançados V21–V25 deixam de aparecer no fluxo normal. Os operadores e validadores ficam acessíveis no código para recuperação, sem apagar dados.
- Um painel só, sem criar todas as malhas V23/V24/V25 simultaneamente. Isolamento cria uma só malha temporária; comparação acrescenta uma instância de modelo.
- Novo comando único `pt_environment.py`, sem duplicar o código que escolhe Blender e verifica o SHA do Stage.
- Catálogo local separa modelos 3D de materiais PBR. Pedras e materiais não são oferecidos no seletor de árvore.

## Limites

A pré-visualização de modelos `.blend.zip` ainda não foi validada com os arquivos reais nem com Blender 5.2 deste computador. Ajustes de escala/material podem ser necessários. Não existe exportação/instanciação no renderer C# nesta versão, nem exportação SMD.

Documentação: `docs/etervale/V26_ENVIRONMENT_REFACTORIZACAO_E_MODELOS_LOCAIS.md`.
