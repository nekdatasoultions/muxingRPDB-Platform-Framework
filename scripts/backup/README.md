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
- `create_live_node_backups.py`
  - creates read-only snapshots from the RPDB live nodes declared in a
    deployment environment
  - uses EC2 Instance Connect plus SSH through the muxer bastion path
  - captures routing, XFRM, nftables, service inventory, and config archives
  - can upload extracted snapshots to the S3 backup prefixes in the
    environment file

Example:

```powershell
python scripts\backup\verify_backup_baseline.py
python scripts\backup\create_live_node_backups.py `
  --environment rpdb-empty-live `
  --upload-s3 `
  --json
python scripts\backup\create_prechange_backup_note.py `
  --customer-name example-nat-0001 `
  --out notes\prechange.md
```

Planned next helpers:

- assist rollback inventory generation
