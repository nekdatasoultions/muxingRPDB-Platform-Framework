# Customer Schema

## Purpose

This document defines the concrete customer source shape for the RPDB model.

The customer source file is the authoring record. It is not the final rendered
customer module. It is the input that gets merged with shared defaults and
class defaults before it is written to DynamoDB and rendered into customer
artifacts.

Important design direction:

- the customer source should describe the customer and service intent
- the provisioning layer should allocate platform namespaces automatically

That intent split is tracked in:

- [VPN_SERVICE_INTENT_MODEL.md](VPN_SERVICE_INTENT_MODEL.md)

The target operator-facing contract is described in:

- [PROVISIONING_INPUT_MODEL.md](PROVISIONING_INPUT_MODEL.md)

## File Location

Each customer should live at:

```text
muxer/config/customer-sources/<customer-name>/customer.yaml
```

## Top-Level Shape

```yaml
schema_version: 1

customer:
  id: 101
  name: example-nat-0001
  customer_class: nat
  peer: ...
  transport: ...
  selectors: ...
  backend: ...
  protocols: ...
  natd_rewrite: ...
  dynamic_provisioning: ...
  ipsec: ...
  post_ipsec_nat: ...
```

## Required Fields

### `customer.id`

- integer
- unique customer identifier

### `customer.name`

- stable customer name used in generated artifacts and DynamoDB

### `customer.customer_class`

Supported values:

- `nat`
- `strict-non-nat`

### `customer.peer`

Required fields:

- `public_ip`
- `psk_secret_ref` or local demo PSK fields when `customer.ipsec.auth.method`
  is omitted or set to `psk`

Optional:

- `remote_id`
- `psk_source`
- `psk`

Default secret handling uses AWS Secrets Manager:

```yaml
peer:
  public_ip: 203.0.113.41
  psk_secret_ref: /muxingrpdb/customers/example/psk
```

For demo or lab-only workflows, the customer request may carry the PSK inline:

```yaml
peer:
  public_ip: 203.0.113.60
  psk_source: local
  psk: replace-me-demo-only
```

Inline PSKs are disabled by default during live apply. The selected deployment
environment must explicitly set:

```yaml
secrets:
  allow_local_psk: true
```

Do not use local inline PSKs for production customer records. The deploy package
must temporarily carry the value so it can inject `swanctl`, but the DynamoDB
`customer_json` copy is redacted before write.

For certificate-authenticated customers, omit all PSK fields from `peer` and
use `customer.ipsec.auth` instead.

### `customer.transport`

Required fields:

- `mark`
- `table`
- `tunnel_key`
- `interface`
- `overlay`

Optional:

- `tunnel_type`
- `tunnel_ttl`
- `tunnel_mtu`
- `rpdb_priority`

Current state:

- these fields are still accepted and used by the compatibility runtime
- `tunnel_mtu` is the true Linux interface MTU for the per-customer transport
  tunnel and is applied to the GRE/VTI device itself during deployment/runtime
- `tunnel_mtu` is separate from `ipsec.path_mtu`; the former changes the actual
  tunnel interface MTU, while the latter drives customer-facing TCP MSS clamp
  derivation for the encrypted path
- for an operator guide with examples, precedence, and verification commands,
  see [TUNNEL_MTU_AND_IPSEC_PATH_MTU.md](./TUNNEL_MTU_AND_IPSEC_PATH_MTU.md)

Target state:

- these fields should become allocator-owned by default
- the operator should not need to hand-assign them for normal provisioning

### `customer.selectors`

Required:

- `local_subnets`
- `remote_subnets`

Optional:

- `remote_host_cidrs`

`remote_host_cidrs` tracks the scoped customer-side CIDRs that are expected to
use the tunnel when `remote_subnets` is a broader or overlapping customer
encryption domain. The name is kept for compatibility, but entries may be `/32`
hosts or smaller CIDR blocks such as `/28`. Every entry must be contained by
one of the declared `remote_subnets`.

Generated head-end IPsec artifacts keep `remote_subnets` as the effective
remote traffic selector. That means `swanctl remote_ts` continues to represent
the customer encryption domain, while `remote_host_cidrs` is preserved as
platform-owned scoped routing, NAT, and accounting metadata inside that domain.

### `customer.backend`

Optional section.

Useful fields:

- `cluster`
- `assignment`
- `role`
- `underlay_ip`

Recommended shape:

- `cluster` identifies the logical head-end pool, such as `nat` or `non-nat`
- `assignment` identifies the logical slot, such as `active-a`
- `role` remains useful as a stable compatibility label
- `underlay_ip` is transitional compatibility only and should not be the long-term primary input

If omitted, the class defaults should provide the backend role and cluster.

### `customer.protocols`

Optional per-customer protocol overrides:

- `udp500`
- `udp4500`
- `esp50`
- `force_rewrite_4500_to_500`

### `customer.natd_rewrite`

Optional per-customer NAT-D behavior overrides:

- `enabled`
- `initiator_inner_ip`

### `customer.dynamic_provisioning`

Optional repo-only promotion intent for customers that start as strict non-NAT
while NAT-T behavior is still unknown.

Supported mode:

- `nat_t_auto_promote`

The section records:

- initial class: `strict-non-nat`
- initial backend: `non-nat`
- trigger protocol: `udp`
- trigger destination port: `4500`
- promotion class: `nat`
- promotion backend: `nat`

This section does not apply live changes by itself. The promotion helper
generates a reviewed NAT request when UDP/4500 is observed from the same peer.

Detailed model:

- [DYNAMIC_NAT_T_PROVISIONING.md](DYNAMIC_NAT_T_PROVISIONING.md)

### `customer.ipsec`

Optional per-customer IPsec overrides:

- `auto`
- `ike_version`
- `local_id`
- `remote_id`
- `ike`
- `esp`
- `ike_policies`
- `esp_policies`
- `dpddelay`
- `dpdtimeout`
- `dpdaction`
- `ikelifetime`
- `lifetime`
- `replay_protection`
- `pfs_required`
- `pfs_groups`
- `forceencaps`
- `mobike`
- `fragmentation`
- `clear_df_bit`
- `path_mtu`
- `mark`
- `vti_interface`
- `vti_routing`
- `vti_shared`
- `bidirectional_secret`
- `initiation`
- `auth`

`initiation` is the explicit tunnel bring-up contract. The default platform
intent is bidirectional:

```yaml
ipsec:
  initiation:
    mode: bidirectional
    headend_can_initiate: true
    customer_can_initiate: true
    traffic_can_start_tunnel: true
    bring_up_on_apply: true
    swanctl_start_action: trap|start
```

This means the generated head-end config installs traffic-trigger trap
policies and also actively initiates the CHILD_SA when the connection is
loaded. A customer can still initiate from their side because the generated
head-end connection is loaded as a responder with the customer peer address,
remote ID, PSK, and traffic selectors.

`auth` controls IKE authentication. If omitted, the framework uses the existing
PSK behavior. To use certificate authentication, set `method: certificate` and
provide references to the PEM material that live apply must install on the
head end:

```yaml
ipsec:
  auth:
    method: certificate
    certificate:
      profile: third_party_provided
        headend:
          id: rpdb-headend.example
          cert_ref: /muxingrpdb/customers/example/headend-cert
          private_key_secret_ref: /muxingrpdb/customers/example/headend-key
          private_key_passphrase_secret_ref: /muxingrpdb/customers/example/headend-key-passphrase
      remote:
        id: customer-cert.example
        trust_ref: /muxingrpdb/customers/example/customer-trust
```

Supported certificate profiles:

- `third_party_provided`: install a provided head-end cert/key and customer
  trust bundle, and optionally provide a customer handoff cert/key/trust back
  to the customer.
- `customer_supplied`: install the customer-issued cert/key/trust that the
  customer requires us to use.

The renderer changes the generated head-end `swanctl` connection to
`auth = pubkey`, installs material under `/etc/swanctl/x509`,
`/etc/swanctl/private`, and `/etc/swanctl/x509ca`, and does not render a
`secrets {}` PSK block. If the head-end private key is encrypted, set
`private_key_passphrase_secret_ref`; live apply resolves that reference and
injects the passphrase into a swanctl private-key secret block. For the
operational model and examples, see
[CERTIFICATE_AUTH_MODEL.md](./CERTIFICATE_AUTH_MODEL.md).

Current repo note:

- the schema and parser now model the richer compatibility fields above
- the head-end artifact render now carries the key compatibility fields into
  `ipsec-intent.json` and `swanctl-connection.conf`
- repo-only validation checks that rendered fields such as IKE version, policy
  lists, replay protection, DF-bit behavior, DPD, encapsulation, MOBIKE, and
  fragmentation are represented in the staged head-end bundle
- repo-only validation checks that bidirectional initiation renders
  `start_action = trap|start`, an initiation intent, and a head-end
  `swanctl --initiate --child` helper

`path_mtu` is the customer-facing IPsec path-size knob. When it is set, the
renderer derives a TCP MSS clamp of `path_mtu - 40` for customer-facing
nftables chains unless a more specific `post_ipsec_nat.tcp_mss_clamp` or
`outside_nat.tcp_mss_clamp` override is present. Non-TCP traffic still relies
on the normal PMTU/fragmentation behavior of the IPsec path.

For an operator guide that explains how `transport.tunnel_mtu`,
`ipsec.path_mtu`, and the explicit per-path clamp overrides work together, see
[TUNNEL_MTU_AND_IPSEC_PATH_MTU.md](./TUNNEL_MTU_AND_IPSEC_PATH_MTU.md).

### `customer.post_ipsec_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Useful fields include:

- `mapping_strategy`
- `translated_subnets`
- `translated_source_ip`
- `real_subnets`
- `core_subnets`
- `host_mappings`
- `interface`
- `output_mark`
- `tcp_mss_clamp`
- `route_via`
- `route_dev`

Important meaning:

- `selectors.remote_subnets` defines what customer-side traffic is in-scope for
  the VPN
- `post_ipsec_nat.real_subnets` defines which real customer-side subnets are
  translated after IPsec
- `post_ipsec_nat.translated_subnets` defines the translated block, such as a
  `/27`, that we present after NAT
- `post_ipsec_nat.core_subnets` defines our side local/core reachability for
  that translated path
- `post_ipsec_nat.tcp_mss_clamp` overrides the derived clamp from
  `ipsec.path_mtu` when that translated path needs a specific TCP value

Target NAT intent:

- block-preserving one-to-one mapping for subnet-to-subnet netmap behavior
- explicit `/32` to `/32` host mappings inside a translated pool

Current repo note:

- one-to-one netmap intent renders deterministic nftables maps
- explicit host mappings render deterministic nftables `DNAT` and `SNAT` state
- staged head-end validation checks the expected command model before install

### `customer.outside_nat`

Optional for the customer source, but when present it must include:

- `enabled`

Use `outside_nat` when the real local/core network behind the VPN head end must
be presented to the customer as a different customer-selected subnet.

Useful fields include:

- `mapping_strategy`
- `translated_subnets`
- `real_subnets`
- `host_mappings`
- `customer_sources`
- `interface`
- `output_mark`
- `tcp_mss_clamp`
- `route_via`
- `route_dev`

Important meaning:

- `selectors.local_subnets` is the customer-visible far-end selector
- `outside_nat.translated_subnets` should match that customer-visible selector
- `outside_nat.real_subnets` is the real local/core subnet behind the head end
- `outside_nat.route_via` sends those real subnets to an upstream router when
  they are not directly owned on the head-end clear-side interface
- `outside_nat.route_dev` overrides the clear-side interface name for those
  routes; omit it to use the environment's head-end clear interface
- `selectors.remote_host_cidrs` scopes NAT, routing, and accounting to concrete
  customer hosts or smaller customer CIDRs when set
- `selectors.remote_subnets` remains the broader customer encryption domain
- `outside_nat.tcp_mss_clamp` overrides the derived clamp from `ipsec.path_mtu`
  when that clear-side presentation needs a different TCP value

Detailed model:

- [HEADEND_OUTSIDE_NAT_AND_OVERLAP_MODEL.md](HEADEND_OUTSIDE_NAT_AND_OVERLAP_MODEL.md)

## Secret Handling

The customer source file should never hold production inline PSKs or private
certificate keys.

Use:

```yaml
psk_secret_ref: /muxingrpdb/customers/<customer-name>/psk
```

The source file is allowed to reference the secret, but the secret value should
not live in Git.

Certificate material follows the same rule. Public certs and trust bundles can
be referenced by Secrets Manager secret ID or by a controlled local `file://`
path for lab work. Private keys should use `private_key_secret_ref` and should
not be committed to the repo.

## Target Minimal Authoring Shape

The target authoring experience is:

- normal site-to-site VPN inputs
- `customer_name`
- `customer_class`
- logical backend placement
- VPN compatibility and interoperability inputs
- interesting traffic intent
- post-IPsec NAT intent where needed

The platform should then allocate the transport/runtime namespaces
automatically.

That model is tracked in:

- [PROVISIONING_INPUT_MODEL.md](PROVISIONING_INPUT_MODEL.md)

## Validation Target

The machine-readable schema for this file lives at:

- [customer-source.schema.json](../config/schema/customer-source.schema.json)
