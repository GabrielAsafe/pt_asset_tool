# Assets em falta — Etervale (evidência confirmada)

Este documento **não** é um inventário completo dos 39.956 arquivos indexados na UI. É o registro da única dependência ausente comprovada pelos comandos enviados no diálogo.

| Arquivo necessário | Referência | Material | Faces associadas | Situação |
|---|---|---:|---:|---|
| `assets/Field/Ricarten/tem_wall04.bmp` | `assets/Field/Ricarten/village-2.smd` | 173 | 1 | **Ausente** |

**Evidências:** leitor `PristonTale.AssetDump --materials` mostrou a referência; `--matbounds` confirmou 1 face; `PristonTale.GltfExport` emitiu fallback `file not found`; a exportação estrita retornou `FAILED_TEXTURE_FALLBACKS` e preservou o SMD original.

As buscas em `~/Transferências`, `~/armazem/priston`, `Etervale-git/assets` e no histórico Git consultado não localizaram `tem_wall04.*`. Os arquivos `lost_temple_wall04.bmp` encontrados pertencem a outro nome e não são substituições equivalentes.

**Próxima auditoria:** após instalar P1_03, execute `etervale asset-gaps --asset Field/Ricarten/village-2.smd --execute --strict` para documentar novas dependências primárias por material. Ainda será necessário auditar texturas secundárias, sons, referências de INX e efeitos.
