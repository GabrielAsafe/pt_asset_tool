# Gaps e candidatos a bugfix antes de expandir conteúdo

Estes pontos **não são corrigidos automaticamente** pelo migrador porque são mudanças de código/formato, não reconciliação de arquivos.

## 1. Tabela de armaduras divergente entre Client e Server

Na tabela `szArmorNumFile_New_2`, o `SrcServer` usa corretamente a sequência `032, 033, 034`, enquanto o `SrcGame` repete `032` no slot em que o servidor usa `033` (o padrão se repete em famílias como A/mA etc.).

Impacto possível:

- um asset `*033` pode existir/migrar e continuar sem ser selecionado pelo cliente;
- adicionar armaduras/classes usando a tabela como verdade pode herdar o erro.

Ação recomendada:

1. produzir diff completo das duas tabelas;
2. corrigir o cliente para a tabela esperada;
3. recompilar;
4. testar troca/equip de 032/033/034 em pelo menos duas classes.

## 2. Stage SMD 0.72: reader/writer divergentes

A fonte Summit atual trata `StageArea` de forma divergente: a leitura atual usa representação DWORD, enquanto o writer legado ainda grava WORD sob o mesmo header `SMD Stage data Ver 0.72`.

Impacto:

- um writer aparentemente “válido” pode gerar arquivo que o próprio runtime interpreta com stride/layout diferente;
- copiar stage de outra linhagem apenas por header não é suficiente.

Ação recomendada: escolher uma representação canônica, versionar o header ou implementar compat loader explícito antes de liberar autoria automática de Stage SMD.

## 3. Jobs 9/10 parcialmente presentes, mas runtime habilita 8

`MAX_JOBNUM` está em 8 e a capacidade declarada é 10. Assassin/Shaman possuem IDs e alguns handlers/dados, mas não formam um pipeline completo de criação/runtime. `HoLogin` ainda trabalha com quatro jobs por raça e há código de Assassin comentado.

Ação recomendada: tratar restauração de job 9/10 como feature/bugfix integrado, com checklist em `CREATING_NEW_CONTENT.md`, e não como simples asset migration.

## 4. Catálogo de items recuperado

O source atual inclui o catálogo recuperado e o mapeamento server-side. Isso corrige a antiga suposição de que item code e filename visual são equivalentes. Porém, se o `Game.exe` distribuído não for produzido desse source, faça smoke/runtime de um conjunto de itens antes de considerar o catálogo prova absoluta do binário em produção.

## 5. 69 ícones pendentes

Eles continuam como gap de conteúdo real após o FIX 058. Não há base auditada para sintetizar “substitutos semânticos”. Resolver isso exige descobrir outra origem, extrair de um container/patch ainda não auditado ou recriar arte nova conscientemente — este último caminho é criação de conteúdo, não reconciliação histórica.
