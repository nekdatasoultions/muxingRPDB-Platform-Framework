# Near-Stateful Sync Plan

Goal: reduce failover impact by synchronizing both flow state and VPN state as much as possible.

## 1. Layer A: Flow-state sync (`conntrackd`)

What this solves:
- Keeps NAT/connection tracking state more consistent between active and standby muxers.

What was added in this project:
- `config/conntrackd/conntrackd.conf.ftfw.example`
- `ha-conntrack-promote.sh`
- `ha-conntrack-demote.sh`
- env controls in `config/ha.env.example`

How to enable:
1. Set in `ha.env`:
   - `FLOW_SYNC_MODE=conntrackd`
2. Install and run `conntrackd` on both nodes.
3. Copy and customize:
   - `/etc/muxingplus-ha/examples/conntrackd.conf.ftfw.example`
   - to `/etc/conntrackd/conntrackd.conf`
4. Ensure sync port/interface reachability between nodes.

## 2. Layer B: IPsec SA sync

### Libreswan path

Libreswan supports HA/failover operation in AWS-style deployments, but not ASA-style in-memory SA state replication out of the box.

Operational result:
- Tunnel identity and role fail over.
- Existing active sessions may re-negotiate.

### strongSwan HA path

For SA synchronization, use strongSwan `ha` plugin (state sync between nodes).

What was added:
- `config/strongswan/charon-ha.conf.example`
- `SA_SYNC_MODE` selector in `ha.env`

How to enable:
1. Install strongSwan with HA plugin enabled.
2. Place rendered plugin config at:
   - `/etc/strongswan.d/charon/ha.conf`
3. Set:
   - `SA_SYNC_MODE=strongswan-ha`
   - `HA_IPSEC_SERVICE=strongswan`

Current head-end direction:
- the head-end bundle renderer supports `--ipsec-backend libreswan` and `--ipsec-backend strongswan`
- the muxer remains unchanged
- current baseline can run on either backend, but the present `dev` runtime is:
  - NAT pair on strongSwan with `SA_SYNC_MODE=none`
  - strict non-NAT pair on strongSwan with `SA_SYNC_MODE=none`
- stronger SA sync is a later option, not the current baseline

## 3. Practical recommendation

For the current stack:
1. Keep `conntrackd` enabled for flow-state continuity.
2. Treat backend choice as cluster-specific:
   - NAT pair currently uses strongSwan with `SA_SYNC_MODE=none`
   - strict non-NAT pair currently uses strongSwan with `SA_SYNC_MODE=none`
3. Treat `strongswan-ha` as a follow-on enhancement after explicit failover validation.
4. Treat backend choice as a deployment parameter decision, not a muxer design change.

## 4. References

- conntrack-tools manual and sync modes:  
  <https://conntrack-tools.netfilter.org/manual.html>
- strongSwan HA plugin overview:  
  <https://docs.strongswan.org/docs/latest/plugins/ha.html>
- strongSwan `ha` plugin configuration options:  
  <https://docs.strongswan.org/docs/latest/config/strongswanConf.html#_charon_plugins_ha>
