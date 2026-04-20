# Muxer And Head-End Platform Deploy Checklist

## Purpose

This is the short operator-facing checklist for standing up the base RPDB
platform:

- muxer
- NAT VPN head-end pair
- non-NAT VPN head-end pair
- customer SoT and allocation database baseline

Use this when we want the platform up with **zero customers onboarded**.

## Scope

This checklist covers:

1. safe parameter preparation
2. deploy planning
3. deploy execution
4. post-deploy validation
5. stop point before customer onboarding

This checklist does **not** cover:

- customer onboarding
- customer cutover
- EIP swing from legacy
- MUXER3 changes

## Guardrails

- Work from the repository root.
- Prefer the generated safe RPDB-empty parameter set.
- Do not use imported production-shaped parameters directly unless you have
  deliberately reviewed EIP behavior.
- Do not onboard a customer from this checklist.

## Step 1: Open A Shell At Repo Root

```powershell
Set-Location <repo-root>
```

## Step 2: Generate Safe Empty-Platform Parameters

This produces a fresh RPDB-empty parameter set derived from the imported shape
without inheriting production EIP behavior.

```powershell
python scripts\platform\prepare_empty_platform_params.py
```

Expected output root:

- `build\empty-platform\current-prod-shape-rpdb-empty`

Generated files to use:

- `build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json`
- `build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json`
- `build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json`

## Step 3: Review The Deploy Plan

Run the platform wrapper in plan mode first.

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json
```

Optional JSON plan:

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json `
  --json
```

Confirm the plan shows:

- muxer stack deploy
- NAT head-end pair deploy
- non-NAT head-end pair deploy
- customer SoT table ensure
- allocation table ensure

## Step 4: Execute The Base Platform Deploy

Run the same wrapper with `--execute` only after the plan looks correct.

```powershell
python scripts\platform\deploy_empty_platform.py `
  --muxer-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.single-muxer.us-east-1.json `
  --nat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.nat.graviton-efs.us-east-1.json `
  --nonnat-headend-params build\empty-platform\current-prod-shape-rpdb-empty\parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json `
  --execute
```

The wrapper chains these steps:

1. verify AWS credentials
2. package the RPDB muxer runtime
3. package the muxer recovery Lambda
4. validate the muxer template
5. deploy the muxer stack
6. package the repo for head-end deployment
7. validate the VPN head-end template
8. deploy the NAT pair
9. deploy the non-NAT pair
10. ensure the customer SoT table exists
11. ensure the allocation table exists

## Step 5: Validate Database Baseline

Check that the customer SoT and allocation tables exist and are healthy.

```powershell
python scripts\platform\ensure_dynamodb_tables.py --check-aws
```

Expected result:

- customer SoT table exists
- allocation table exists
- tables are active
- no customer onboarding is required yet

## Step 6: Validate Head-End Bootstrap

Run the framework verifier first.

```powershell
python scripts\platform\verify_headend_bootstrap.py --region us-east-1 --json
```

Expected result:

- NAT head-end active node healthy
- NAT head-end standby node healthy
- non-NAT head-end active node healthy
- non-NAT head-end standby node healthy

## Step 7: Validate The Muxer Node

Run these checks on the muxer:

```bash
sudo systemctl status muxer.service --no-pager
sudo ip addr
sudo ip rule
sudo ip route show table all
sudo nft list ruleset
```

Check for:

- `muxer.service` running
- expected interfaces present
- RPDB rules present
- routing tables present
- nftables ruleset rendering cleanly

## Step 8: Validate Each VPN Head-End Node

If the framework verifier reports drift or you want a manual spot check, run:

```bash
ip addr
findmnt /LOG
findmnt /Application
findmnt /Shared
sudo systemctl status muxingplus-ha --no-pager
sudo systemctl status conntrackd --no-pager
sudo systemctl status strongswan --no-pager
```

Check for:

- ENIs present with expected addresses
- `/LOG`, `/Application`, and `/Shared` mounted
- `muxingplus-ha` running
- `conntrackd` running
- `strongswan` running

## Step 9: Stop Here Before Customer Onboarding

Do not continue from this checklist into customer deployment.

The next stage after a clean platform validation is:

1. prepare a customer file
2. run customer dry-run review
3. explicitly approve the first customer apply

## Longer References

Use these when you need the full background or imported current-state context:

- [FRESH_EMPTY_PLATFORM_RUNBOOK.md](./FRESH_EMPTY_PLATFORM_RUNBOOK.md)
- [DATABASE_BOOTSTRAP.md](./DATABASE_BOOTSTRAP.md)
- [CURRENT_PLATFORM_IMPORT.md](./CURRENT_PLATFORM_IMPORT.md)
- [HEADEND_CUSTOMER_ORCHESTRATION.md](./HEADEND_CUSTOMER_ORCHESTRATION.md)
- [DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md](./current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
