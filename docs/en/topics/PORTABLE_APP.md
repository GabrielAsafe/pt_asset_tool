# Portable Application

The portable distribution bundles the PT Asset Tool application code and static resources while keeping runtime/generated data outside the static snapshot.

Verify a portable package with:

```bash
./VERIFY_PACKAGE.sh
```

Do not package user-specific `pt_build`, enhancement runs, quarantine transactions, or local server/client data as static application content.
