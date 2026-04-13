# Backup Scripts

This directory holds backup verification and restore helper scaffolding.

Current helper:

- `verify_backup_baseline.py`
  - verifies the shared backup baseline directory exists
  - verifies each required snapshot exists
  - verifies the expected manifest, checksum, and runtime snapshot files exist

Example:

```powershell
python scripts\backup\verify_backup_baseline.py
```

Planned next helpers:

- create purpose-built pre-change backup metadata
- assist rollback inventory generation
