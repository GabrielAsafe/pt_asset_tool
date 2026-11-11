# P1/06 — Nova superfície de validação na UI

Após aplicar este patch e reiniciar `bash app/pt-asset-gui`, abra `http://127.0.0.1:PORTA/etervale-readiness` ou use o link **Etervale Validation** na barra lateral.

A página mostra cinco áreas: writers, adaptação canônica, dependências em falta, qualidade e Fields. Consulta o endpoint local `/api/etervale/readiness`, que lê **somente** arquivos JSON recentes das pastas permitidas sob `app/pt_build/etervale/`. Nunca executa scripts, nunca aplica alterações e nunca classifica aceitação de reader como certificação no jogo.

Também há `python3 app/pt_asset.py etervale ui-board` para ler os mesmos estados pela CLI. Uma reformulação mais profunda da UI (fluxos de edição, publicação e widgets de comparação) depende dos resultados dos gates reais — este patch é o primeiro painel de evidências, não o redesenho final.
