# Deploy Muxer, VPN Head Ends, And Customer Runbook

## Scope

This runbook covers the current platform model:

- single active muxer
- NAT VPN head-end HA pair
- non-NAT VPN head-end HA pair
- customer source of truth authored privately and synchronized into DynamoDB

This file is preserved as an imported current-state reference.

For the RPDB-native empty-platform flow that now packages the muxer runtime
from this repo instead of `MUXER3`, start with:

- [FRESH_EMPTY_PLATFORM_RUNBOOK.md](/docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md)

This runbook assumes you are working from WSL:

- framework repo: `/home/master/code1/Muxingplus-Platform-Framework`
- deployment repo: `/home/master/code1/Muxingplus-Platform-Deployments/dev`
- live customer repo: `/home/master/code1/MUXER3`

## 0. Prerequisites

1. Verify AWS credentials:

```bash
aws sts get-caller-identity
```

2. Verify the working repos exist in WSL:

```bash
ls ~/code1
```

3. Confirm the current key artifacts are available:
- muxer bundle S3 path
- muxer recovery Lambda S3 path
- deployment artifact S3 path

4. Confirm the head-end EFS IDs for the current environment:
- file system ID
- access point ID

## 1. Deploy the muxer

### 1.1 Package the muxer application bundle

From the live muxer repo:

```bash
cd ~/code1/MUXER3
bash scripts/package_project_to_s3.sh s3://baines-networking/Code/MUXER3/muxer3-bundle.zip
```

### 1.2 Package the muxer recovery Lambda

```bash
cd ~/code1/Muxingplus-Platform-Framework/infra/scripts
bash package_muxer_recovery_lambda_to_s3.sh \
  s3://baines-networking/Code/MUXER3/muxer-recovery-lambda.zip
```

### 1.3 Validate the single-muxer template

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/cfn_validate_single_muxer.sh
```

### 1.4 Review the live muxer parameter file

File:
- `cfn/parameters.single-muxer.us-east-1.json`

At minimum verify:
- `ClusterName`
- VPC and subnet IDs
- transport ENI IPs
- `ProjectPackageS3Uri`
- `CustomerSotTableName`
- `EipAllocationId`
- recovery Lambda bucket/key

### 1.5 Deploy the muxer

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/cfn_deploy_single_muxer.sh \
  muxer-single-prod \
  cfn/parameters.single-muxer.us-east-1.json \
  us-east-1
```

### 1.6 Validate the muxer after deploy

Confirm in AWS:
- stack completed successfully
- ASG launched the muxer
- transport ENI attached for the correct AZ
- public EIP is attached if intended for this cutover

Confirm on the muxer:

```bash
sudo systemctl status muxer.service --no-pager
sudo ip addr
sudo ip rule
sudo ip route show table all
sudo iptables-save
```

If customer state is expected:

```bash
sudo /etc/muxer/src/muxctl.py show
```

## 2. Deploy the VPN head ends

### 2.1 Package the deployment artifact

From the deployment repo:

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/package_project_to_s3.sh \
  s3://baines-networking/Code/Muxingplus-Platform-Deployments/dev/muxingplus-platform-deployments-dev.zip
```

### 2.2 Validate the VPN head-end template

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/cfn_validate_vpn_headend.sh
```

### 2.3 Review the NAT head-end parameter file

File:
- `cfn/parameters.vpn-headend.nat.graviton-efs.us-east-1.json`

Verify:
- cluster name
- primary, HA/sync, and core IPs
- `ProjectPackageS3Uri`
- `EnableSharedEfs=true`
- EFS file system ID and access point ID
- temporary management EIP allocation if used

### 2.4 Deploy the NAT pair

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/cfn_deploy_vpn_headend.sh \
  vpn-headend-nat-graviton-dev-us-east-1 \
  cfn/parameters.vpn-headend.nat.graviton-efs.us-east-1.json \
  us-east-1
```

### 2.5 Review the non-NAT head-end parameter file

File:
- `cfn/parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json`

Verify the same fields as NAT, but for the non-NAT pair.

### 2.6 Deploy the non-NAT pair

```bash
cd ~/code1/Muxingplus-Platform-Deployments/dev
bash scripts/cfn_deploy_vpn_headend.sh \
  vpn-headend-non-nat-graviton-dev-us-east-1 \
  cfn/parameters.vpn-headend.non-nat.graviton-efs.us-east-1.json \
  us-east-1
```

### 2.7 Validate each head-end node

On each node verify:

```bash
ip addr
findmnt /LOG
findmnt /Application
findmnt /Shared
sudo systemctl status muxingplus-ha --no-pager
sudo systemctl status conntrackd --no-pager
sudo systemctl status ipsec --no-pager
```

Design checks:
- `/LOG` and `/Application` are local disks
- `/Shared` is EFS
- customer-facing VPN runtime is local, not on EFS

## 3. Create and render a customer

Important boundary:
- the framework repo is examples only
- real customer creation happens in the private/live muxer repo

### 3.1 Decide the customer class

Choose one:
- NAT customer
- strict non-NAT customer

That choice decides:
- which head-end pair receives the customer
- whether `UDP/4500` is enabled
- whether post-IPsec NAT is used

Current AWS strict non-NAT note:

- do not assume strict non-NAT means `force_rewrite_4500_to_500=true`
- the currently proven strict AWS path uses:
  - `udp500=true`
  - `udp4500=false`
  - `esp50=true`
  - `force_rewrite_4500_to_500=false`
  - `natd_rewrite.enabled=true`
- the current validated `legacy-cust0002` path is direct `/32 <-> /32`, not the `/27` overlap path

### 3.2 Author the customer in the private variables file

In the live repo:

```bash
cd ~/code1/MUXER3
vi config/customers.variables.yaml
```

Define:
- customer name and ID
- peer IP
- backend head-end underlay IP
- GRE key/interface intent
- protocol flags
- IPsec fields
- post-IPsec NAT fields if overlap translation is needed

Source-of-truth guardrail:

- if `config/muxer.yaml` sets `customer_sot.backend=dynamodb` and `sync_from_variables_on_render=false`, the live muxer follows DynamoDB
- update the repo variables and the DynamoDB item together, or re-render/sync immediately after changing variables

### 3.3 Sync the customer into DynamoDB

```bash
cd ~/code1/MUXER3
python3 scripts/sync_customers_to_dynamodb.py --create-table
```

If the table already exists:

```bash
python3 scripts/sync_customers_to_dynamodb.py
```

### 3.4 Render the customer artifacts

```bash
cd ~/code1/MUXER3
python3 scripts/render_customer_variables.py --source dynamodb --prune
```

This produces:
- muxer customer folder
- routing metadata
- iptables metadata
- VPN/IPsec metadata
- post-IPsec NAT metadata where applicable

## 4. Apply the customer on the muxer

### 4.1 Install the updated customer files on the muxer

If the repo is already installed locally on the muxer, sync/update that working tree and re-run the renderer there if needed.

### 4.2 Apply muxer state

```bash
sudo /etc/muxer/src/muxctl.py apply
```

### 4.3 Validate muxer state

```bash
sudo /etc/muxer/src/muxctl.py show
sudo ip rule
sudo ip route show table all
sudo iptables-save
```

Confirm:
- customer GRE exists
- customer fwmark and route table exist
- customer NAT/steering rules exist

For strict non-NAT customers also confirm:

- `muxctl show` reflects the expected strict mode
- if using the current AWS strict path, the customer shows:
  - `force_rewrite_4500_to_500=false`
  - `natd_rewrite.enabled=true`
- `journalctl -u ike-nat-bridge` shows `natd-in` / `natd-out` counters if NAT-D rewrite is active

## 5. Render and install the customer bundle on the correct head-end pair

### 5.1 Render a NAT customer bundle

```bash
cd ~/code1/MUXER3
python3 scripts/render_headend_customer_bundle.py \
  --source dynamodb \
  --cluster nat \
  --local-underlay-ip <nat-headend-a-primary-ip> \
  --remote-underlay-ip <muxer-transport-ip> \
  --public-ip 54.204.221.89 \
  --output-dir build/nat-bundle
```

### 5.2 Render a non-NAT customer bundle

```bash
cd ~/code1/MUXER3
python3 scripts/render_headend_customer_bundle.py \
  --source dynamodb \
  --cluster non-nat \
  --local-underlay-ip <nonnat-headend-a-primary-ip> \
  --remote-underlay-ip <muxer-transport-ip> \
  --public-ip 54.204.221.89 \
  --output-dir build/nonnat-bundle
```

### 5.3 Stage the bundle onto EFS

Copy the rendered bundle to the shared EFS path under `/Shared/<cluster>/customer-bundles/...`

### 5.4 Install the bundle on the active and standby head ends

On the target pair:

```bash
cd /Shared/<cluster>/customer-bundles/<bundle-name>
sudo bash ./install-on-headend.sh
sudo bash ./validate-on-headend.sh
```

Do not cut over until validation passes.

### 5.5 Special checks

For NAT customers:
- confirm post-IPsec NAT service exists when expected
- confirm translated identity and `OUTPUT` mark rules are present

For strict non-NAT customers:
- confirm the muxer is preserving the shared public identity on backend delivery
- confirm the active strict mode is the one you intended:
  - `natd_rewrite.enabled=true` for the current AWS legacy path
  - not `force_rewrite_4500_to_500=true`
- confirm the head end is using the intended backend
- do not assume the `/27` overlap model is active just because the customer file contains translated subnets

Current proven `legacy-cust0002` note:

- active non-NAT head end backend: strongSwan
- validated selectors:
  - `172.31.54.39/32`
  - `10.129.3.154/32`
- `/27` overlap NAT is not the working path today

## 6. Bring the customer up and validate

### 6.1 Bring up the customer conn

```bash
sudo ipsec auto --rereadsecrets || sudo ipsec whack --rereadsecrets
sudo ipsec auto --add <customer-conn-name>
sudo ipsec auto --up <customer-conn-name>
```

### 6.2 Validate on the head end

```bash
sudo ipsec auto --status
sudo ip xfrm state
sudo ip xfrm policy
```

### 6.3 Validate traffic

Use the translated or real protected IPs appropriate for that customer and confirm traffic both directions.

### 6.4 Strict non-NAT return-route check

For direct `/32 <-> /32` strict non-NAT validation, confirm the cleartext-side host has a route back to the remote protected `/32` via the non-NAT core ENI.

Example from the current `legacy-cust0002` validation:

```bash
sudo ip route replace 10.129.3.154/32 via 172.31.59.220 dev ens5
```

If this route is missing, the tunnel can still show:

- IKE established
- CHILD installed
- inbound decap working

while outbound payload bytes stay at zero.

## 7. If this is a migration from an old head end

1. Stage and validate on the new head end first.
2. Move muxer backend target and GRE remote endpoint to the new head end.
3. Flush peer-specific muxer conntrack state.
4. Re-initiate from the appropriate side.
5. Validate traffic both directions.
6. Only then drain the old head end.

This is the migration rule learned from the customer retro:
- configuration move alone is not enough
- muxer live state must be cleared as part of cutover

## 8. Final checks

Before considering the customer complete, confirm:
- customer exists in DynamoDB
- muxer has the correct GRE, mark, table, and iptables rules
- correct head-end pair has the installed bundle
- `validate-on-headend.sh` passes
- tunnel establishes
- traffic passes both directions
- if migrated, old head-end ownership is drained
