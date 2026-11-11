# Etervale V11 — Hotfix imediato das miniaturas achatadas do Catalog

A captura do catálogo mostra as miniaturas comprimidas em linhas de poucos píxeis. A hipótese técnica é uma regressão no cálculo das linhas do CSS Grid depois da V10 ter limitado a altura dos painéis. **O CSS V10 exato da instalação não está disponível nesta análise; a correção é uma sobreposição conservadora, não uma comparação linha a linha com o CSS do utilizador.**

O hotfix fixa a altura de cada miniatura em 118 px (`object-fit: contain`), impede que as linhas do grid partilhem a altura disponível e mantém o scroll interno da galeria. Não altera a altura dos painéis, a tabela, os dados dos assets, os thumbnails nem o worker SMD em execução.

## Instalar sem interromper o SMD

```bash
cd "$HOME/Transferências/pt_asset_tool"
unzip -o "$HOME/Transferências/ETERVALE_V11_GALERIA_HOTFIX_2026-11-10.zip" -d .
python3 patches/aplicar_etervale_v11_galeria.py --project-root "$PWD" --dry-run
python3 patches/aplicar_etervale_v11_galeria.py --project-root "$PWD"
```

No browser, carregar `Ctrl+Shift+R`. **Não é necessário reiniciar o servidor web, parar o job SMD nem reindexar**: apenas `app.css` muda. O instalador grava um backup na pasta `patches/_backups/` e é idempotente.

## Validar

- A galeria deve voltar a apresentar cada miniatura com cerca de 118 px de altura, sem distorção.
- As imagens devem manter a sua proporção original, centradas dentro dos thumbnails.
- O scroll continua dentro da galeria; o painel Detail mantém a altura configurada pela V10.
- O contador SMD deve continuar a avançar; o hotfix não toca no backend nem em `pt_build`.

Se o resultado visual ainda não for correto, envie uma nova captura e a saída de `grep -n -E 'gallery|asset-card|thumb|grid-auto-rows' app/pt_asset_tool/ui_static/app.css | tail -40`; uma regra CSS mais específica ou alteração de HTML poderá precisar de correção adicional.

## Reverter

O backup criado pela instalação contém exatamente o `app.css` original; copie-o de volta **só se precisar reverter**, sem alterar outro ficheiro. O script não remove código nem faz substituição em massa.
