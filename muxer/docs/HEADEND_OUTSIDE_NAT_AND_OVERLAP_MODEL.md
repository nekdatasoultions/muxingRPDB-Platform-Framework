# Head-End Outside NAT And Overlapping Customer Domains

## Purpose

This document defines two head-end service-intent features:

- outside NAT for local/core networks that a customer cannot route directly
- customer remote host tracking inside overlapping customer encryption domains

Both are modeled in the customer request. The platform still owns automatic
customer ID, marks, route tables, RPDB priority, tunnel keys, interface names,
overlay addressing, and head-end placement.

## Requirement 1: Outside NAT

Outside NAT is used when the real local/core network behind the VPN head end is
not something the customer can or should route.

Instead of asking the customer to route the real local/core subnet, we present a
customer-selected translated subnet as the VPN far-end selector.

Example:

```text
real local/core network:       198.51.100.80/28
customer-visible VPN network:  10.0.2.0/28
```

The customer uses `10.0.2.0/28` as interesting traffic. The head end translates:

- customer to core: `10.0.2.x` DNATs to `198.51.100.x`
- core to customer: `198.51.100.x` SNATs to `10.0.2.x`

This is intentionally separate from `post_ipsec_nat`.

## Requirement 2: Overlapping Customer Remote Domains

Many customers can use the same remote encryption domain, for example:

```yaml
remote_subnets:
  - 10.200.60.0/24
```

That overlap is acceptable because the selector is scoped to one IPsec tunnel.

The platform also needs to know which exact customer-side ranges are actually
used inside that overlapping subnet. That is modeled with `remote_host_cidrs`.
The field name is kept for compatibility, but the values may be either `/32`
hosts or smaller CIDR blocks contained by `remote_subnets`:

```yaml
remote_host_cidrs:
  - 10.200.60.88/32
  - 10.200.60.2/32
  - 10.200.60.3/32
  - 10.200.60.65/32
  - 10.200.60.128/28
```

The `/24` remains the master customer encryption domain. The scoped values
become the tracked selector inventory for IPsec policy, NAT scoping,
validation, troubleshooting, and growth accounting.

## Customer Request Shape

```yaml
schema_version: 1
customer:
  name: example-outside-nat-overlap
  peer:
    public_ip: 203.0.113.55
    remote_id: 203.0.113.55
    psk_secret_ref: aws-secretsmanager:/example/rpdb/customer/psk

  selectors:
    local_subnets:
      - 10.0.2.0/28
    remote_subnets:
      - 10.200.60.0/24
    remote_host_cidrs:
      - 10.200.60.88/32
      - 10.200.60.2/32
      - 10.200.60.3/32
      - 10.200.60.65/32
      - 10.200.60.128/28

  outside_nat:
    enabled: true
    mode: netmap
    mapping_strategy: one_to_one
    real_subnets:
      - 198.51.100.80/28
    translated_subnets:
      - 10.0.2.0/28
```

## Selector Meaning

`selectors.local_subnets`

The local/far-end traffic selector the customer sees in the VPN. When outside
NAT is enabled, this should be the translated customer-visible subnet.

`outside_nat.real_subnets`

The real local/core subnet behind the head end.

`outside_nat.translated_subnets`

The customer-visible replacement subnet. This should match the far-end
selector the customer is configured to route.

`selectors.remote_subnets`

The customer-side encryption domain. This can overlap between customers because
each tunnel has its own peer, selectors, SA state, marks, routes, and artifacts.

`selectors.remote_host_cidrs`

The scoped customer-side ranges expected to use the tunnel. These may be `/32`
hosts or smaller CIDR blocks, but every value must be contained by one of the
declared `remote_subnets`. Generated IPsec artifacts still use
`remote_subnets` as the effective remote traffic selectors. Generated outside
NAT, routing, and accounting artifacts use `remote_host_cidrs` to scope the
actual customer-side CIDRs that belong to this customer inside the broader
encryption domain.

## Generated Head-End Behavior

The head-end package renders:

- `headend/outside-nat/outside-nat-intent.json`
- `headend/outside-nat/nftables.apply.nft`
- `headend/outside-nat/nftables.remove.nft`
- `headend/outside-nat/nftables-state.json`
- `headend/outside-nat/activation-manifest.json`

The generated nftables table performs both directions:

```text
customer host -> translated local IP -> DNAT to real local/core IP
real local/core IP -> customer host -> SNAT to translated local IP
```

When `remote_host_cidrs` is present, the generated strongSwan connection still
uses `remote_subnets` as `remote_ts`. The scoped host/range list is carried as
customer-specific routing/NAT intent so the platform can account for the actual
CIDRs used inside an overlapping encryption domain without changing the
customer-visible selectors.

The staged head-end apply wrapper installs outside NAT before post-IPsec NAT:

```text
apply routes
apply outside NAT
apply post-IPsec NAT
load swanctl
initiate tunnel when policy allows
```

## Important Split

Use `outside_nat` when our/local side needs to be presented to the customer as
a different subnet.

Use `post_ipsec_nat` when the customer/remote side needs to be translated after
IPsec decapsulation.

They solve different directions of the same larger problem and can be validated
independently.

## Validation

The repo validates that:

- `remote_host_cidrs` are valid CIDRs contained by `remote_subnets`
- generated `swanctl remote_ts` uses `remote_subnets`, even when
  `remote_host_cidrs` is present
- outside NAT one-to-one mappings have matching subnet sizes
- outside NAT explicit host mappings stay inside declared translated subnets
- generated outside NAT artifacts use nftables
- generated outside NAT artifacts contain DNAT and SNAT statements when enabled
- staged head-end apply includes the outside NAT apply/remove scripts
- staged head-end apply preserves bidirectional tunnel initiation checks from
  [BIDIRECTIONAL_IPSEC_INITIATION.md](BIDIRECTIONAL_IPSEC_INITIATION.md)
