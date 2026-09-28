# Installation Quick Start

## Requirements

- Python 3.11+ recommended.
- A readable Priston Tale client root.
- A readable Summit server root for server-side enrichment and Legacy Management workflows.
- Optional external tools such as Blender or Real-ESRGAN only for the capabilities that require them.

## Verify the package

From the package root:

```bash
./VERIFY_PACKAGE.sh
```

The verifier checks the static snapshot and package integrity. Runtime data under `app/pt_build` is intentionally excluded from the static package snapshot.

## Start the CLI

```bash
cd app
python3 pt_asset.py --help
```

## Start the UI

```bash
cd app
python3 pt_asset_gui.py
```

The UI is read-only by default. Build/staging actions require a temporary workspace/build arm. Client/server publication uses separate transactional authorization and safety gates.

## Configure roots

The UI and CLI share persisted root configuration. You can also provide roots explicitly on a command when appropriate.

Typical client path:

```text
/path/to/Summit/client
```

Typical server path:

```text
/path/to/Summit/Server
```

Do not infer or invent a server root. Use the actual configured Summit server directory.

## Recommended first run

1. Run **Doctor** / dependency diagnostics.
2. Reindex the client catalog.
3. Configure the server root if server-side analysis is needed.
4. Run General Census only when source/reference/donor roots are configured correctly.
5. Use Catalog/Entities for individual assets and relationships.
6. Use Legacy Management for ITEM/MONSTER/NPC/MAP authoring and local persistence workflows.
7. Keep quarantine and publish operations reversible until runtime validation is complete.
