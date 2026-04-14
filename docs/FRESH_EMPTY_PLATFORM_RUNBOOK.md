# Fresh Empty Platform Runbook

## Goal

Stand up a new platform with the same current production shape, but with **zero
customers** onboarded yet.

This runbook is the safe front door for:

- muxer
- NAT VPN head-end pair
- non-NAT VPN head-end pair
- customer SoT database baseline

It does **not** include customer onboarding and it does **not** assume an EIP
cutover should happen immediately.

## Current Production-Shaped Defaults

The imported current-state parameter files keep the same shape we use today:

- muxer:
  - instance type `c8gn.8xlarge`
- NAT head-end pair:
  - instance type `c8gn.2xlarge`
  - three ENIs per node: primary, HA/sync, core
- non-NAT head-end pair:
  - instance type `c8gn.2xlarge`
  - three ENIs per node: primary, HA/sync, core
- customer SoT table:
  - `muxingplus-customer-sot`

Source parameter files:

- [parameters.single-muxer.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.single-muxer.us-east-1.json)
- [parameters.vpn-headend.nat.graviton-efs.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.vpn-headend.nat.graviton-efs.us-east-1.json)
- [parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json)

## Important Pause: EIP Review

The imported production-shaped parameter files still carry `EipAllocationId`
values.

That means:

- planning is safe
- packaging is safe
- validation is safe
- actual deploy should pause until we deliberately decide whether this is:
  - a rehearsal with temporary/neutral EIPs
  - or a real cutover path

The wrapper script enforces this by refusing `--execute` unless you also pass
`--allow-production-eip`.

## Front Door

Use:

- [deploy_empty_platform.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform/deploy_empty_platform.py)

### Show the plan only

```powershell
python scripts\platform\deploy_empty_platform.py
```

### Show the structured JSON plan

```powershell
python scripts\platform\deploy_empty_platform.py --json
```

### Execute the automatic steps after deliberate EIP review

```powershell
python scripts\platform\deploy_empty_platform.py --execute --allow-production-eip
```

## What The Wrapper Chains

1. verify AWS credentials
2. package the current muxer application from the sibling `MUXER3` repo
3. package the muxer recovery Lambda
4. validate the single-muxer template
5. deploy the muxer stack
6. package this RPDB repo as the current deployment artifact for the head ends
7. validate the VPN head-end template
8. deploy the NAT pair
9. deploy the non-NAT pair
10. ensure the customer SoT table exists

## Database Step

The database layer is explicit in:

- [DATABASE_BOOTSTRAP.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/DATABASE_BOOTSTRAP.md)
- [ensure_dynamodb_tables.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform/ensure_dynamodb_tables.py)

For a fresh empty platform, the important current production-shaped behavior is:

- ensure `muxingplus-customer-sot`
- head-end lease tables remain stack-managed because `LeaseTableName` is blank

## Manual Validation After Deploy

### Muxer

```bash
sudo systemctl status muxer.service --no-pager
sudo ip addr
sudo ip rule
sudo ip route show table all
sudo iptables-save
```

### Each VPN head-end node

```bash
ip addr
findmnt /LOG
findmnt /Application
findmnt /Shared
sudo systemctl status muxingplus-ha --no-pager
sudo systemctl status conntrackd --no-pager
sudo systemctl status strongswan --no-pager
```

### Database

```powershell
python scripts\platform\ensure_dynamodb_tables.py --check-aws
```

## What Comes Next

After the empty platform is proven:

1. keep the edge/cutover pause until customer definitions are staged
2. use the RPDB-native customer flow
3. run the double-verification gate before the first customer rehearsal

References:

- [CURRENT_PLATFORM_IMPORT.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/CURRENT_PLATFORM_IMPORT.md)
- [PRE_DEPLOY_DOUBLE_VERIFICATION.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md)
- [DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
