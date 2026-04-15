# VPN Service Intent Model

## Goal

The customer YAML or minimal request should describe:

- how the VPN must behave
- what affects interoperability with the customer
- what traffic is tunneled
- what traffic is NATed after IPsec

The platform allocator should describe:

- which platform namespace values were reserved
- which physical slot or node currently owns the customer

This keeps the customer authoring model focused on service intent while the
allocator owns collision-prone runtime namespaces.

## Clean Split

### Customer-provided VPN and service intent

These fields belong in the customer VPN config or customer request:

- IKEv1 vs IKEv2
- allowed crypto policy sets
- DPD behavior
- replay protection policy
- PFS flexibility and required-group behavior
- fragmentation and force-encapsulation behavior
- DF-bit handling default
- whether VTI is required
- what remote or customer traffic is considered interesting
- what traffic must be translated to a `/27` or another translated pool

### Platform-assigned runtime namespaces

These fields should remain allocator-owned:

- `customer_id`
- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay block
- GRE or VTI interface names
- backend assignment result

## Traffic Intent Split

The customer model should distinguish three related but different things:

### 1. Interesting VPN traffic

This is the traffic that belongs in the VPN relationship at all.

Current fields:

- `selectors.local_subnets`
- `selectors.remote_subnets`

### 2. Post-IPsec NAT source traffic

This is the subset of customer-side traffic that must be translated after
decryption.

Current field:

- `post_ipsec_nat.real_subnets`

### 3. Presented translated space

This is the translated address block or individual translated IPs that we
present after NAT.

Current fields:

- `post_ipsec_nat.translated_subnets`
- `post_ipsec_nat.translated_source_ip`

Supporting local/core reachability stays in:

- `post_ipsec_nat.core_subnets`

## Required NAT Behaviors

The model should support both of these behaviors.

### Block-preserving one-to-one mapping

Example:

```yaml
post_ipsec_nat:
  enabled: true
  mode: netmap
  mapping_strategy: one_to_one
  real_subnets:
    - 10.129.3.128/27
  translated_subnets:
    - 172.30.0.64/27
  core_subnets:
    - 172.31.54.39/32
    - 194.138.36.80/28
```

Intent:

- first real IP maps to first translated IP
- last real IP maps to last translated IP
- the prefix-sized block is preserved one-to-one

### Explicit host mapping inside a translated pool

Example:

```yaml
post_ipsec_nat:
  enabled: true
  mode: explicit_map
  translated_subnets:
    - 172.30.0.64/27
  host_mappings:
    - real_ip: 10.129.3.154/32
      translated_ip: 172.30.0.70/32
    - real_ip: 10.129.3.155/32
      translated_ip: 172.30.0.71/32
  core_subnets:
    - 172.31.54.39/32
    - 194.138.36.80/28
```

Intent:

- the translated `/27` still defines the allowed presentation pool
- selected `/32` real IPs can map to selected `/32` translated IPs

## Current Repo State

Modeled in the current schema and parser:

- `ipsec.ike`
- `ipsec.esp`
- `ipsec.ike_version`
- `ipsec.ike_policies`
- `ipsec.esp_policies`
- `ipsec.dpddelay`
- `ipsec.dpdtimeout`
- `ipsec.dpdaction`
- `ipsec.replay_protection`
- `ipsec.pfs_required`
- `ipsec.pfs_groups`
- `ipsec.forceencaps`
- `ipsec.mobike`
- `ipsec.fragmentation`
- `ipsec.clear_df_bit`
- `ipsec.mark`
- `ipsec.vti_interface`
- `ipsec.vti_routing`
- `ipsec.vti_shared`
- `post_ipsec_nat.*`
- `post_ipsec_nat.mapping_strategy`
- `post_ipsec_nat.host_mappings`

Carried through render and repo-only orchestration:

- IKE version render behavior on the head-end side
- IKE and ESP policy list rendering into `swanctl`
- DPD render behavior
- replay-protection render behavior through `replay_window`
- DF-bit handling render behavior through `copy_df`
- force-encapsulation, MOBIKE, and fragmentation render behavior
- one-to-one netmap command rendering for block-preserving translation
- explicit host-mapping command rendering with DNAT/SNAT pairs
- staged head-end install, validate, and remove verification

## Next Repo Work

The next implementation steps should be:

1. keep extending repo-only examples as new customer VPN patterns appear
2. run isolated-node validation before any live customer migration
3. keep live-node rollout blocked behind the double-verification gate

## Verified Examples

The repo contains committed examples for both NAT mapping styles:

- [example-service-intent-netmap.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/config/customer-requests/examples/example-service-intent-netmap.yaml)
- [example-service-intent-explicit-host-map.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/config/customer-requests/examples/example-service-intent-explicit-host-map.yaml)

The repo-only verification harness provisions both examples, renders and binds
their customer artifacts, validates their bundles, and exercises staged
head-end install/validate/remove.
