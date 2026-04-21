# Backup And Rollback Baseline

## Purpose

This document captures the current rollback anchor for future RPDB live-node
work.

## Shared Backup Baseline

Pre-RPDB backups were captured on April 13, 2026 and stored under:

```text
/Shared/backups/pre-rpdb-baseline/
```

Verified node snapshots:

- `ip-172-31-34-89-20260413T203353Z`
  - muxer `172.31.34.89`
- `ip-172-31-40-221-20260413T203353Z`
  - NAT head-end A `172.31.40.221`
- `ip-172-31-141-221-20260413T203353Z`
  - NAT head-end B `172.31.141.221`
- `ip-172-31-40-220-20260413T203353Z`
  - non-NAT head-end A `172.31.40.220`
- `ip-172-31-141-220-20260413T203353Z`
  - non-NAT head-end B `172.31.141.220`

## Expected Backup Contents

Each snapshot should include:

- node config archive
- `ip addr`
- `ip rule`
- `ip route show table all`
- `ip -d link show`
- `nft list ruleset`
- `conntrack` stats
- `ip xfrm state`
- `ip xfrm policy`
- service inventory
- muxer or strongSwan status snapshots
- `manifest.txt`
- `sha256sums.txt`

## Rollback Expectation

Before any future live RPDB change:

1. confirm the baseline snapshot exists for the affected nodes
2. take an additional purpose-built pre-change backup for that rollout
3. document the exact artifacts and services that may need to be restored
4. do not start a live apply unless the rollback path is already written down

## Initial Rollback Scope

The first RPDB live validations should assume rollback may require restoring:

- muxer config and ruleset state
- NAT head-end customer runtime
- non-NAT head-end customer runtime
- customer-scoped deployment artifacts

## RPDB-Empty Live Pre-Change Backup

Before the first RPDB-empty live-node update, a fresh read-only backup was
captured from the five RPDB-empty nodes on April 21, 2026.

Backup command:

```powershell
python scripts\backup\create_live_node_backups.py `
  --environment rpdb-empty-live `
  --upload-s3 `
  --json
```

Backup run ID:

```text
20260421T194634Z
```

Verified S3 snapshot roots:

- `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/muxer/muxer-i-0c8c34de42777c769-20260421T194634Z/`
- `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/nat-headend/nat-active-i-0a5f8a1e1b0fed116-20260421T194634Z/`
- `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/nat-headend/nat-standby-i-026dcd8f4b658772b-20260421T194634Z/`
- `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/non-nat-headend/non_nat-active-i-05c6a9f56cd531322-20260421T194634Z/`
- `s3://baines-networking/Code/muxingRPDB-Platform-Framework/empty-platform/rpdb-empty/backups/baseline/non-nat-headend/non_nat-standby-i-0eb58b43b6886ea0c-20260421T194634Z/`

Each snapshot was verified to include:

- `manifest.txt`
- `sha256sums.txt`
- `nft-ruleset.txt`

The backup command is read-only against node runtime state. It may capture
`iptables-save.txt` for rollback visibility, but RPDB runtime/apply artifacts
remain nftables-only.
