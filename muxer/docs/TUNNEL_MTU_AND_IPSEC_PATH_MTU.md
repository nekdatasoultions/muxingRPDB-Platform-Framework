# Tunnel MTU And IPsec Path MTU

## Purpose

This document explains the Cisco-like per-VPN/per-tunnel sizing knobs that the
RPDB platform now supports for each customer:

- `customer.transport.tunnel_mtu`
- `customer.ipsec.path_mtu`
- `customer.outside_nat.tcp_mss_clamp`
- `customer.post_ipsec_nat.tcp_mss_clamp`

These knobs solve related but different problems. The most important
distinction is that `transport.tunnel_mtu` changes the real Linux tunnel
interface MTU, while `ipsec.path_mtu` drives customer-facing TCP MSS behavior
for the encrypted path.

## Quick Comparison

| Field | Layer | What it changes | Typical use |
| --- | --- | --- | --- |
| `customer.transport.tunnel_mtu` | Transport tunnel device | Actual Linux interface MTU on the per-customer GRE/VTI tunnel | Match encapsulation overhead or customer packet-size requirements |
| `customer.ipsec.path_mtu` | Customer-facing IPsec path intent | Default TCP MSS derivation as `path_mtu - 40` | Set the intended end-to-end encrypted path size |
| `customer.outside_nat.tcp_mss_clamp` | Clear-side outside NAT presentation | Explicit MSS clamp for `outside_nat` traffic | Override the default MSS for the outside NAT path |
| `customer.post_ipsec_nat.tcp_mss_clamp` | Post-IPsec translated return/customer path | Explicit MSS clamp for `post_ipsec_nat` traffic | Override the default MSS for the post-IPsec NAT path |

## Mental Model

If you think about this the Cisco way:

- `transport.tunnel_mtu` is closest to setting MTU on the tunnel interface
- `ipsec.path_mtu` is closer to a customer-facing IPsec path-size policy
- `outside_nat.tcp_mss_clamp` and `post_ipsec_nat.tcp_mss_clamp` are the exact
  TCP MSS override knobs when you need a specific value on one path

`ipsec.path_mtu` does not call `ip link set ... mtu ...` by itself. That is the
job of `transport.tunnel_mtu`.

## Example Customer Request

```yaml
schema_version: 1
customer:
  name: example-customer

  transport:
    tunnel_mtu: 1436

  ipsec:
    ike_version: ikev2
    fragmentation: true
    clear_df_bit: true
    path_mtu: 1400

  outside_nat:
    enabled: true
    mode: netmap
    mapping_strategy: one_to_one
    real_subnets:
      - 198.51.100.80/28
    translated_subnets:
      - 10.0.2.0/28
    tcp_mss_clamp: 1360
```

This means:

- the per-customer tunnel device is set to MTU `1436`
- the customer-facing IPsec path intent is `1400`
- the outside NAT path still uses an explicit TCP MSS clamp of `1360`

## Precedence Rules

### Tunnel Interface MTU

`customer.transport.tunnel_mtu` is the only tunnel MTU knob. If it is set, it
becomes the tunnel interface MTU on the rendered head-end and muxer transport
artifacts and in the compatibility runtime.

If it is not set, the platform does not invent a customer-specific MTU value.

### Customer-Facing TCP MSS

For both `outside_nat` and `post_ipsec_nat`, the effective TCP MSS clamp is:

1. the explicit path override if present
2. otherwise `customer.ipsec.path_mtu - 40` if `path_mtu` is set
3. otherwise no rendered MSS clamp

That means:

- `outside_nat.tcp_mss_clamp` wins for the `outside_nat` path
- `post_ipsec_nat.tcp_mss_clamp` wins for the `post_ipsec_nat` path
- `ipsec.path_mtu` is the default, not the override

## What Gets Rendered

The standard customer pipeline carries these fields through the normal
allocation, render, bind, and apply flow. No special deployment mode is needed.

### Transport MTU Artifacts

When `customer.transport.tunnel_mtu` is set, the rendered artifacts include it
in both the intent and the executable commands.

Head-end transport artifacts:

- `package/rendered/headend/transport/transport-intent.json`
- `package/rendered/headend/transport/apply-transport.sh`

Muxer transport artifacts:

- `package/rendered/muxer/tunnel/tunnel-intent.json`
- `package/rendered/muxer/tunnel/ip-link.command.txt`

The compatibility runtime also carries `tunnel_mtu` in the runtime customer
module and applies it to the live tunnel interface during customer-scoped
runtime tunnel setup.

### IPsec Path MTU And MSS Artifacts

When `customer.ipsec.path_mtu` is set, the rendered head-end manifests record:

- `ipsec_path_mtu`
- `configured_tcp_mss_clamp`
- `effective_tcp_mss_clamp`
- `tcp_mss_clamp_source`

These show whether the effective clamp came from:

- an explicit per-path clamp, or
- the derived `ipsec.path_mtu - 40` value

Relevant artifacts:

- `package/rendered/headend/outside-nat/activation-manifest.json`
- `package/rendered/headend/outside-nat/nftables.apply.nft`
- `package/rendered/headend/post-ipsec-nat/activation-manifest.json`
- `package/rendered/headend/post-ipsec-nat/nftables.apply.nft`

## NAT-T Promotion Behavior

For dynamically promoted customers, request-owned transport overrides such as
`customer.transport.tunnel_mtu` are preserved when the promoted NAT request is
built. The same is true for the IPsec path MTU and MSS behavior because those
remain part of the customer request/source model that promotion carries
forward.

That means the NAT-T promotion path keeps:

- the real per-customer tunnel MTU
- the default IPsec path MTU intent
- any explicit per-path MSS override

## Verification

The safest way to verify the feature is to check both the rendered artifacts and
the live system.

### 1. Verify The Rendered Tunnel MTU

```bash
jq .tunnel_mtu build/customer-deploy/<customer>-live/package/rendered/headend/transport/transport-intent.json
jq .tunnel_mtu build/customer-deploy/<customer>-live/package/rendered/muxer/tunnel/tunnel-intent.json
grep -n "mtu" build/customer-deploy/<customer>-live/package/rendered/headend/transport/apply-transport.sh
grep -n "mtu" build/customer-deploy/<customer>-live/package/rendered/muxer/tunnel/ip-link.command.txt
```

Expected result:

- the intent files show the configured `tunnel_mtu`
- the rendered commands contain `ip link set <ifname> mtu <value>`

### 2. Verify The Rendered IPsec Path MTU And MSS Result

```bash
jq '.ipsec_path_mtu, .configured_tcp_mss_clamp, .effective_tcp_mss_clamp, .tcp_mss_clamp_source' \
  build/customer-deploy/<customer>-live/package/rendered/headend/outside-nat/activation-manifest.json

jq '.ipsec_path_mtu, .configured_tcp_mss_clamp, .effective_tcp_mss_clamp, .tcp_mss_clamp_source' \
  build/customer-deploy/<customer>-live/package/rendered/headend/post-ipsec-nat/activation-manifest.json

grep -n "maxseg size set" \
  build/customer-deploy/<customer>-live/package/rendered/headend/outside-nat/nftables.apply.nft

grep -n "maxseg size set" \
  build/customer-deploy/<customer>-live/package/rendered/headend/post-ipsec-nat/nftables.apply.nft
```

Expected result:

- `ipsec_path_mtu` shows the configured path MTU
- `effective_tcp_mss_clamp` shows the final TCP MSS value that will be applied
- `tcp_mss_clamp_source` shows whether the value came from a path override or
  from `ipsec.path_mtu`

### 3. Verify The Live Tunnel Interface MTU

On the active muxer or active head end, inspect the customer transport
interface:

```bash
sudo ip link show <tunnel-ifname>
```

Expected result:

- the interface exists
- the reported MTU matches `customer.transport.tunnel_mtu`

### 4. Verify The Live MSS Clamp

```bash
sudo nft list ruleset | grep -A2 -B2 "maxseg size set"
```

Expected result:

- the customer-scoped nftables rules include the expected MSS value

### 5. Verify With Real Traffic

For TCP traffic, start a fresh connection and inspect the SYN packet:

```bash
sudo tcpdump -ni any 'tcp[tcpflags] & tcp-syn != 0'
```

Expected result:

- the SYN packet shows the expected MSS value after clamp

For example:

- `ipsec.path_mtu: 1400` with no explicit override should produce MSS `1360`
- `ipsec.path_mtu: 1400` plus `outside_nat.tcp_mss_clamp: 1320` should keep
  `outside_nat` at MSS `1320`

## Recommended Usage

Use `customer.transport.tunnel_mtu` when you need to control the real tunnel
device packet ceiling.

Use `customer.ipsec.path_mtu` when you want a default customer-facing TCP path
policy without hard-coding the exact clamp on every NAT path.

Use `outside_nat.tcp_mss_clamp` or `post_ipsec_nat.tcp_mss_clamp` only when a
specific path needs a different TCP MSS than the default derived from
`ipsec.path_mtu`.

## Important Limitation

`customer.ipsec.path_mtu` currently controls the customer-facing IPsec path by
driving TCP MSS clamp behavior. It does not directly change a Linux device MTU.
Non-TCP traffic still relies on the normal PMTU discovery and fragmentation
behavior of the underlying transport and IPsec path.
