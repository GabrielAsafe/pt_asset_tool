# Etervale V21.1 — Correção de registo das propriedades Blender 5.2

## Evidência do defeito

O comando `python3 app/pt_stage072_semantic_paint.py --map Field/forest/fore-1.smd` abre o proxy V19 com `PT_STAGE072_VIEW=PASS`, mas o timer de inicialização falha em `bpy.utils.register_class(PT_SemanticRegion)`:

```
typing.get_type_hints failed with: PT_SemanticRegion
PT_SEMANTIC=FAIL reason=NameError:name 'StringProperty' is not defined
```

## Causa e correção

`stage072_semantic_paint.py` usava `from __future__ import annotations`, adiando a avaliação de declarações como `region_id: StringProperty()`. A avaliação tardia feita pelo Blender 5.2 não encontra `StringProperty` no namespace Python apropriado e o add-on não é registado. A V21.1 remove **somente** essa instrução do script Blender. Assim as fábricas `bpy.props` são chamadas quando `PT_SemanticRegion` é definida, gerando as anotações RNA efetivas antes de o timer chamar `register_class`.

Não se altera a V21 `stage072_semantic_core.py`, launcher, source-SHA, as anotações JSON existentes, proxy V19, arquivos SMD, texturas nem código cliente Etervale.

## Validação

Três testes novos verificam que não há anotações adiadas, que as oito propriedades são objetos efetivos em vez de strings (incluindo os callbacks) e que o contrato de salvaguarda da V21 permanece intacto. Os 10 testes V21 originais devem continuar a passar.

**Limite:** testes offline com stubs Blender; a execução gráfica final depende do Blender 5.2 do utilizador. O resultado esperado ao abrir o mapa é `PT_SEMANTIC=READY asset=Field/forest/fore-1.smd ...`, com o painel `N → Etervale → Classificação V21` disponível.

## Segurança de instalação

Patch só aplica a versão V21 original se o SHA corresponder, guarda backup, recusa conflito e é idempotente. Não usar `--force`. Não é necessário reindexar, refazer os 58 previews ou reiniciar jobs.
