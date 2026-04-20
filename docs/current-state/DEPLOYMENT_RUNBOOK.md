# Deployment Runbook

This runbook is for manual host-level setup.

Preferred path is now:
- NetBox SoT
- CloudFormation deploy
- clean ENI-based bootstrap

See:
- `docs/CLOUDFORMATION_NETBOX_RUNBOOK.md`
- `cfn/muxer-cluster.yaml` (one-time stack)
- `cfn/vpn-headend-unit.yaml` (repeatable stack)

## 1. Place project on both headend nodes

Example:

```bash
sudo mkdir -p /opt/muxingplus-ha
sudo rsync -av ./ /opt/muxingplus-ha/
```

## 2. Create DynamoDB lease table

Partition key:
- `cluster_id` (String)

## 3. IAM permissions

Attach instance profile with:
- `dynamodb:GetItem`
- `dynamodb:UpdateItem`
- `ec2:AssociateAddress` (if EIP move enabled)

## 4. Install service on each node

```bash
sudo /opt/muxingplus-ha/ops/headend-ha-active-standby/scripts/install-local.sh /opt/muxingplus-ha
sudo vi /etc/muxingplus-ha/ha.env
```

Node A and Node B must have distinct:
- `HA_NODE_ID`
- `HA_ENI_ID` (if EIP mode)
- `HA_SYNC_INTERFACE`
- `HA_SYNC_LOCAL_IP`

Shared values:
- `HA_CLUSTER_ID`
- `HA_REGION`
- `HA_DDB_TABLE`
- `HA_EIP_ALLOC_ID` (if EIP mode)

For the current `dev` head-end split:
- NAT pair:
  - set `FLOW_SYNC_MODE=conntrackd`
  - set `SA_SYNC_MODE=none`
  - set `IpsecBackend=strongswan`
  - set `IpsecService=strongswan`
- strict non-NAT pair:
  - set `FLOW_SYNC_MODE=conntrackd`
  - set `SA_SYNC_MODE=none`
  - set `IpsecBackend=strongswan`
  - set `IpsecService=strongswan`

Operator warning:
- do not assume both head-end classes share the same backend at a given moment
- check the current cluster parameter files and `HEADEND_RUNTIME_STATUS.md` before bootstrap or cutover

Framework note:
- both `libreswan` and `strongswan` are supported by the renderer and CloudFormation bootstrap
- choose backend with `IpsecBackend`
- choose the service wrapper with `IpsecService`
- the muxer and overall dataplane contract stay the same across both backends

Optional future HA upgrade:
- set `SA_SYNC_MODE=strongswan-ha` only after the strongSwan HA plugin path has been validated in failover testing

Interface model for clean redeploy:
- muxer:
  - primary ENI on device index `0`
  - HA/sync ENI on device index `1`
- VPN head end:
  - primary ENI on device index `0`
  - HA/sync ENI on device index `1`
  - core ENI on device index `2`

The current CloudFormation templates now discover those ENIs via EC2 metadata and write the resolved interface names into `/etc/muxingplus-ha/ha.env`.

Storage model for clean redeploy:
- local root disk: OS and package manager state
- local `/LOG`: hot local logs and transient troubleshooting output
- local `/Application`: installed bundles, active runtime config, and live VPN/IPsec runtime files
- optional `/Shared` EFS mount: shared customer bundles, rendered exports, backups, and archived logs

Important EFS boundary:
- do use EFS for shared artifacts and operator handoff files
- do not place live IPsec runtime state, conntrack state, sockets, or `/run` data on EFS

## 5. Start

```bash
sudo systemctl enable --now muxingplus-ha.service
sudo /usr/local/sbin/ha-status.sh
```

## 5.1 Enable conntrackd flow sync

1. Copy example:
   - `/etc/muxingplus-ha/examples/conntrackd.conf.ftfw.example`
   - to `/etc/conntrackd/conntrackd.conf`
2. Replace placeholders:
   - `<SYNC_LOCAL_IP>`, `<SYNC_PEER_IP>`, `<SYNC_INTERFACE>`
3. Start service:
   - `sudo systemctl enable --now conntrackd`

## 5.2 Optional SA sync (strongSwan HA mode)

1. Set in `/etc/muxingplus-ha/ha.env`:
   - `SA_SYNC_MODE=strongswan-ha`
   - `HA_IPSEC_SERVICE=strongswan`
2. Copy and edit:
   - `/etc/muxingplus-ha/examples/ha-sync.env.example`
   - to `/etc/muxingplus-ha/ha-sync.env`
3. Render plugin config:
   - `sudo /usr/local/sbin/render-strongswan-ha-conf.sh /etc/muxingplus-ha/ha-sync.env /etc/strongswan.d/charon/ha.conf`
4. Restart strongSwan service.

Current deployment note:
- active NAT head ends are running strongSwan with `SA_SYNC_MODE=none`
- active strict non-NAT head ends are running strongSwan with `SA_SYNC_MODE=none`
- strongSwan and Libreswan remain supported backends, but the live `dev` baseline is currently strongSwan on both head-end pairs
- HA plugin mode is not the live default

## 6. Failover test

On ACTIVE node:

```bash
sudo systemctl stop muxingplus-ha.service
```

On STANDBY node, check promotion:

```bash
sudo /usr/local/sbin/ha-status.sh
```

## 7. Rollback

```bash
sudo systemctl disable --now muxingplus-ha.service
```
