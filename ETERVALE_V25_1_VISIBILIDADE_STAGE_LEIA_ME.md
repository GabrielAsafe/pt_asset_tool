# ETERVALE V25.1 — Stage oculto e cópias temporárias

Atualização incremental **sobre V25**. Fecha o Blender antes de instalar. O script verifica hashes, faz backup e bloqueia conflitos de código.

## Instalação

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V25_1_VISIBILIDADE_STAGE_2026-11-11.zip" -d .
python3 patches/aplicar_etervale_v25_1_visibilidade.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v25_1_visibilidade.py --project-root "$PWD"
python3 -m pytest -q app/dev_tests/test_etervale_stage072_v25_1_visibility.py
```

Se aparecer `SOURCE_FILE_CONFLICT`, não uses force: preserva as mudanças locais e apresenta o conflito para analisarmos.

## Reabrir e continuar

```bash
python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd
```

No Blender, painel **N → Etervale → V25 · Rever associações copa/tronco**:

1. **Ocultar Stage original duplicado** se ainda aparecer `PT_STAGE072_STAGE` afastado do proxy. O próprio painel já o oculta automaticamente ao iniciar.
2. **Analisar sugestões V24**: reutiliza as 41 associações do JSON V25 existente. Não clicar V22 Detetar.
3. **Isolar par (copa + tronco)**, avaliar as peças, e **Restaurar mapa e remover par**.
4. **Criar grupos V25 no Outliner** apenas quando quiseres inspecionar os grupos; esses objetos são cópias de faces, não outro Stage completo.
5. **Limpar cópias temporárias** quando terminares a inspeção: remove apenas os objetos V23–V25 de inspeção; os JSON e as malhas originais são mantidos.

Não substitui GLB, não altera o SMD original, o cliente Etervale nem os 58 relatórios de auditoria. A fonte certificada continua guardada no `.blend`, mas escondida. Guardar o `.blend` de sessão não publica alterações no jogo.

## Verificação

`PT_V25_NATIVE_SOURCE=HIDDEN_ON_START` e, ao premir limpeza, `PT_V25_CLEANUP=PASS`.

**Testes:** validações offline; as ações de visibilidade devem ainda ser confirmadas no teu Blender 5.2.
