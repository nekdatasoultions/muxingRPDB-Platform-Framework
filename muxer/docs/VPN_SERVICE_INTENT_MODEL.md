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

Already modeled in the current compatibility schema:

- `ipsec.ike`
- `ipsec.esp`
- `ipsec.dpddelay`
- `ipsec.dpdtimeout`
- `ipsec.dpdaction`
- `ipsec.forceencaps`
- `ipsec.mobike`
- `ipsec.fragmentation`
- `ipsec.mark`
- `ipsec.vti_interface`
- `ipsec.vti_routing`
- `ipsec.vti_shared`
- `post_ipsec_nat.*`

Not fully modeled yet:

- explicit `ike_version`
- explicit replay-protection control
- explicit DF-bit policy
- richer multi-policy compatibility structure beyond raw `ike` and `esp`
- explicit `mapping_strategy` for post-IPsec NAT
- explicit host-mapping entries for `/32` to `/32` translations

## Next Repo Work

The next implementation steps should be:

1. extend the schema and typed customer model
2. carry the richer service intent through merge and artifact render
3. update head-end orchestration validation around the richer NAT intent
4. add repo-only examples and verification for both mapping styles
