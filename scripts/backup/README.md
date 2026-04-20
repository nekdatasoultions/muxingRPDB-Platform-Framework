# Backup Scripts

This directory holds backup verification and restore helper scaffolding.

Current helper:

- `verify_backup_baseline.py`
  - verifies the shared backup baseline directory exists
  - verifies each required snapshot exists
  - verifies the expected manifest, checksum, and runtime snapshot files exist
- `create_prechange_backup_note.py`
  - creates a rollout-specific pre-change backup note
  - references the shared baseline snapshots
  - records target nodes and expected restore scope

Example:

```powershell
python scripts\backup\verify_backup_baseline.py
python scripts\backup\create_prechange_backup_note.py `
  --customer-name example-nat-0001 `
  --out notes\prechange.md
```

Planned next helpers:

- assist rollback inventory generation
