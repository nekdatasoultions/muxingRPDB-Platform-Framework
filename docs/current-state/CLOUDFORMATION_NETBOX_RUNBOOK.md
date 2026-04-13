# CloudFormation + NetBox SoT Runbook

This project uses:
- NetBox as source-of-truth (SoT) for VPN head-end unit parameters
- AWS CloudFormation as deployment mechanism
- Split stacks:
  - one-time Muxer cluster stack
  - repeatable VPN head-end unit stack
- Regional deployment orchestration for both stacks
- No AWS IPAM dependency
- NetBox is not deployed by CloudFormation in regional rollout

## 1. NetBox SoT model

Tag two objects (devices or VMs) with your cluster tag (example: `vpn-headend-prod`).

Required fields on each object:
1. `primary_ip4` set (used as node private IP)
2. custom field `ha_node` with value `a` or `b`
3. custom field `aws_subnet_id` with target subnet-id
4. custom field `aws_vpc_id` with target vpc-id (at least one node must have this)

Current gap:
- NetBox does not yet carry the HA/sync or core ENI IPs/subnets
- use the generator CLI overrides for those values until dedicated custom fields are added

## 2. Build VPN head-end params from NetBox

```bash
python3 scripts/netbox_to_cfn_params.py \
  --netbox-url "https://netbox.example.com" \
  --netbox-token "$NETBOX_TOKEN" \
  --cluster-tag "vpn-headend-prod" \
  --cluster-name "vpn-headend-unit-0001" \
  --ami-id "ami-xxxxxxxxxxxxxxxxx" \
  --instance-type "t3.small" \
  --key-name "muxer" \
  --project-package-s3-uri "s3://baines-networking/Code/Muxingplus-HA/muxingplus-ha.zip" \
  --allow-gre-ingress "true" \
  --gre-ingress-cidr "172.31.0.0/16" \
  --core-ingress-cidr "172.31.0.0/16" \
  --ha-sync-subnet-a-id "subnet-ccccccccccccccccc" \
  --ha-sync-subnet-b-id "subnet-ddddddddddddddddd" \
  --node-a-ha-sync-ip "172.31.69.210" \
  --node-b-ha-sync-ip "172.31.127.210" \
  --core-subnet-a-id "subnet-eeeeeeeeeeeeeeeee" \
  --core-subnet-b-id "subnet-fffffffffffffffff" \
  --node-a-core-ip "172.31.55.210" \
  --node-b-core-ip "172.31.88.210" \
  --eip-allocation-id "" \
  --output cfn/parameters.netbox.json
```

## 3. Package project to S3

```bash
bash scripts/package_project_to_s3.sh \
  s3://baines-networking/Code/Muxingplus-HA/muxingplus-ha.zip
```

## 4. Validate templates

```bash
bash scripts/cfn_validate_muxer.sh us-east-1
bash scripts/cfn_validate_vpn_headend.sh us-east-1
```

## 5. Deploy one-time Muxer stack

```bash
bash scripts/cfn_deploy_muxer.sh \
  muxer-cluster-prod \
  cfn/parameters.muxer.example.json \
  us-east-1
```

## 6. Deploy VPN head-end unit stack

```bash
bash scripts/cfn_deploy_vpn_headend.sh \
  vpn-headend-unit-0001 \
  cfn/parameters.netbox.json \
  us-east-1
```

Repeat step 6 with a new `cluster-name` and stack name for each additional head-end unit shard.

## 7. Verify

1. Check stack events and outputs.
2. Verify both instances are running.
3. Verify the expected ENI count is correct:
   - muxer: `2`
   - VPN head end: `3`
4. Confirm only one node is ACTIVE:
   - `sudo /usr/local/sbin/ha-status.sh`
5. Stop active controller and confirm standby promotes.

## 8. Notes

- Muxer template is intended to be deployed once per environment.
- VPN head-end unit template is intentionally repeatable for horizontal scale.
- EIP association is handled by the HA runtime promote logic (not by a template-time initial association), which avoids multi-ENI attach failures.
- Runtime failover still uses the HA controller to re-associate EIP as role changes.
- `conntrackd` sync is enabled via `FlowSyncMode=conntrackd`.
- The templates now discover the HA/sync interface from EC2 metadata and render conntrackd against that interface automatically.
- For region-wide execution, use `docs/REGIONAL_DEPLOYMENT_RUNBOOK.md`.
