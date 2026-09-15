# Política de migração

## AUTO

Um candidato pode ser `AUTO` quando:

1. a auditoria liga explicitamente a lacuna ao Summit atual;
2. a origem é conhecida;
3. o destino não existe;
4. a estrutura do formato é compatível com a geração Summit;
5. não há conflito semântico conhecido.

Exemplos de formato estrutural aceito pelo migrador:

- INX Summit: 95.268 bytes;
- SPP Summit: 2.400 bytes;
- SPC Summit: 50.400 bytes;
- SMD/SMB `SMD Model data Ver 0.62` para modelos, sujeito à existência do pacote/dependências;
- INF/NPC/SPM/TXT: bytes preservados; análise de encoding é informativa.

## REVIEW

Não é copiado automaticamente quando há boa evidência, mas ainda falta validação semântica/runtime. Principais casos:

- `dcave.ase.spc`: a ausência no Summit é de alta confiança, mas os doadores auditados divergem binariamente; escolher a linhagem antes de aplicar;
- `AncientW.spc`, `SeaA.spc`, `Slab.spc` e outros componentes de Field não classificados como lacuna inequívoca;
- substituição de SPM placeholder por versão doadora;
- lote antigo de OpenItem ainda sem prova completa de catálogo/uso atual;
- DDS em uma árvore Summit que não possua DDS peer naquela família;
- Stage SMD 0.72, salvo exceção explícita de uma cópia Summit anterior da mesma linhagem.

## BLOCKED

Nunca deve entrar por bulk-copy:

- `BlessCastle.dat` (estado/configuração runtime; tamanhos divergem entre linhagens);
- executáveis, DLLs, PDBs, bancos e outros binários operacionais;
- INX Priston de 67.084 bytes no runtime Summit de 95.268;
- SPP legado de 600 bytes como substituto do SPP Summit canônico;
- Stage SMD 0.72 de linhagem estrutural não comprovada;
- conflitos OpenItem conhecidos `SP149` e `OA136`;
- `KhanDoor` enquanto a dependência `name/KhanDoor.zhoon` continuar órfã;
- `MapleFairy/MapleTree` enquanto o pacote cliente não for encontrado;
- os 69 ícones TimeShop/ItemShop ainda sem origem comprovada pelo FIX 058.

## Por que copiar, não mover

A origem auditada é evidência. Removê-la destrói a capacidade de reproduzir a decisão e piora rollback. Por isso o script implementa cópia missing-only. Se depois for necessário desativar uma árvore doadora, isso deve ser uma etapa administrativa separada, após validação do Summit.

## Overwrite

O modo normal nunca sobrescreve. Mesmo com opção explícita de overwrite, itens `REVIEW/BLOCKED` continuam fora do `apply` automático.
