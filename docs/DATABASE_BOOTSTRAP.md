# Database Bootstrap

## Goal

Make the database layer explicit in the RPDB repo so a fresh platform deploy
has a clear SoT and HA-table story before any customer onboarding starts.

## Current Production-Shaped Database Model

There are two different DynamoDB table types in the current platform:

The completed RPDB control-plane model now needs a third table type for smart
resource reservations.

### 1. Customer SoT Table

Purpose:

- canonical customer source of truth for the muxer/customer control plane

Current imported production shape:

- table name: `muxingplus-customer-sot`
- source:
  [parameters.single-muxer.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.single-muxer.us-east-1.json)
- key schema:
  `customer_name` (HASH, String)

Important note:

- this table is referenced by the imported single-muxer template
- it is not created automatically by the current imported single-muxer stack
- it should be ensured before customer synchronization starts

### 2. HA Lease Tables

Purpose:

- active/standby lease coordination for HA-managed node roles

Key schema:

- `cluster_id` (HASH, String)

Current imported production-shaped head-end parameters:

- NAT:
  [parameters.vpn-headend.nat.graviton-efs.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.vpn-headend.nat.graviton-efs.us-east-1.json)
- non-NAT:
  [parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/infra/cfn/parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json)

Current imported production shape:

- `LeaseTableName` is empty in both head-end parameter files
- that means the CloudFormation template creates stack-managed lease tables for
  those pairs

So for the current production-shaped bootstrap:

- **customer SoT table** should be explicitly ensured
- **resource allocation table** should be explicitly ensured for smart
  provisioning and namespace ownership tracking
- **head-end lease tables** are expected to be stack-managed by CloudFormation

### 3. Resource Allocation Table

Purpose:

- track exclusive namespace reservations such as:
  - `customer_id`
  - `fwmark`
  - `route_table`
  - `rpdb_priority`
  - `tunnel_key`
  - `overlay_block`
  - `transport_interface`
  - `vti_interface`

Current repo bootstrap shape:

- default derived table name: `<customer_sot_table>-allocations`
- example from the current imported production-shaped SoT:
  - `muxingplus-customer-sot-allocations`
- key schema:
  - `resource_key` (HASH, String)

Important note:

- this table is not yet stack-managed by the imported infrastructure
- it is a control-plane requirement for smart provisioning, not a lease/HA
  table
- the helper can inspect or create it explicitly

## Helper

Use:

- [ensure_dynamodb_tables.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/scripts/platform/ensure_dynamodb_tables.py)

## Example

Show the current plan without touching AWS:

```powershell
python scripts\platform\ensure_dynamodb_tables.py --json
```

Check AWS for the current tables:

```powershell
python scripts\platform\ensure_dynamodb_tables.py --check-aws
```

Create the customer SoT table if it does not exist:

```powershell
python scripts\platform\ensure_dynamodb_tables.py --create-customer-sot
```

Create the resource allocation table if it does not exist:

```powershell
python scripts\platform\ensure_dynamodb_tables.py --create-resource-allocation-table
```

Create both smart-provisioning tables with an explicit allocation table name:

```powershell
python scripts\platform\ensure_dynamodb_tables.py `
  --create-customer-sot `
  --create-resource-allocation-table `
  --allocation-table-name muxingplus-customer-sot-rpdb-allocations
```

## Relationship To Customer Onboarding

The customer SoT table belongs in the **base platform bootstrap**.

That means:

1. deploy muxer and head-end nodes
2. ensure the customer SoT table exists
3. ensure the resource allocation table exists
4. validate the empty platform
5. only then begin customer onboarding

## References

- [CURRENT_PLATFORM_IMPORT.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/CURRENT_PLATFORM_IMPORT.md)
- [DEPLOYMENT_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/DEPLOYMENT_RUNBOOK.md)
- [DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/current-state/DEPLOY_MUXER_HEADENDS_AND_CUSTOMER_RUNBOOK.md)
