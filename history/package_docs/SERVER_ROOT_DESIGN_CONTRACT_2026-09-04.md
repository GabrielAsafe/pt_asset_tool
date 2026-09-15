# PT Asset Tool — Server-root design contract

Estado: R14 server-aware, read-only discovery.

## Motivo

O Summit Server contém conteúdo estático de gameplay e também cópias/variantes das famílias 3D usadas pelo client. Portanto o Design Tool não deve modelar o projeto como uma única árvore `client_root`; a unidade futura de autoria é o bundle funcional com papéis client/server.

## Roots

- `client_root`: recursos consumidos pelo client e inventário canónico atual.
- `server_root`: conteúdo e metadata consumidos pelo server.
- `pt_build`: único root autorizado para outputs temporários/candidates.

## Lifecycles server-side

- asset estático: INF/NPC/ZHOON/OpenItem/SPM;
- metadata de field: SPP e SPC, com SPC em REVIEW;
- 3D compartilhado: INI lógico, INX, SMD, SMB, ASE;
- visual compartilhado: BMP/TGA/DDS/JPG/PNG apenas quando houver referência provada;
- config: `Configs/*`, revisão deliberada;
- persistência/estado/segurança/log: nunca asset (`DataServer`, `PostBox`, `WAR`, `LogItemData/*.itm`, `cpItem.dat`, `BlessCastle.dat`, `BlackUser`, `FuncBox`, logs);
- binários/tooling: excluídos.

## Política atual

Todo acesso ao server é read-only. O novo `validate server-environment-auto` só lê samples e grava o relatório em `pt_build`. `audit server-inventory` faz censo de metadata de filesystem, classifica cada path e também escreve somente em `pt_build`. Não existe writer server autorizado nesta revisão.

## Próximo estágio

Depois de um server environment PASS e de um inventory físico, construir o graph de bundles:

- Monster: INF → ZHOON → model logical → INX → SMD/SMB/texturas + drops + SPM/evento.
- NPC: NPC → ZHOON → model package + SPC/event/quest/shop quando aplicável.
- Field: stage SMD/ASE → SPP/SPC/SPM → entidades referenciadas.
- Item: OpenItem/ZHOON → code map server → catalog/model/icon client.

Persistência nunca entra nesse graph de autoria.
