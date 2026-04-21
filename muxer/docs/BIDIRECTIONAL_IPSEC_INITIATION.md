# Bidirectional IPsec Initiation

## Purpose

Every RPDB customer package must support both directions of tunnel bring-up:

- the customer side can initiate IKE/IPsec toward the RPDB head end
- the RPDB head end can initiate IKE/IPsec toward the customer side
- matching protected traffic can trigger tunnel negotiation if the CHILD_SA is
  not already up

This requirement applies to NAT-T and non-NAT customers.

## Default Contract

The platform default is:

```yaml
ipsec:
  auto: trap|start
  initiation:
    mode: bidirectional
    headend_can_initiate: true
    customer_can_initiate: true
    traffic_can_start_tunnel: true
    bring_up_on_apply: true
    swanctl_start_action: trap|start
```

`trap|start` is intentional. `trap` installs traffic-trigger policies. `start`
actively initiates the CHILD_SA when the config is loaded.

The strongSwan swanctl documentation describes `start_action = trap`, `start`,
and the combined `trap|start` form:

- https://docs.strongswan.org/docs/latest/swanctl/swanctlConf.html
- https://docs.strongswan.org/docs/latest/howtos/introduction.html

## Generated Artifacts

Each head-end bundle renders:

- `headend/ipsec/ipsec-intent.json`
- `headend/ipsec/initiation-intent.json`
- `headend/ipsec/initiate-tunnel.sh`
- `headend/ipsec/swanctl-connection.conf`

The swanctl child must include:

```text
start_action = trap|start
```

The initiation helper must include:

```bash
swanctl --initiate --child "<customer-child>"
```

## What This Proves

Customer-initiated bring-up is supported because the head-end config is loaded
with:

- the expected peer public address
- the expected remote ID
- the shared PSK reference
- matching local and remote traffic selectors

Head-end-initiated bring-up is supported because the package renders both:

- `start_action = trap|start` in swanctl
- an explicit `initiate-tunnel.sh` helper that calls `swanctl --initiate`

Traffic-triggered bring-up is supported because `trap` is part of the rendered
start action.

## Validation Gates

Repo-only validation fails if:

- bidirectional mode does not allow both endpoints to initiate
- traffic-triggered initiation is enabled but `start_action` does not include
  `trap`
- head-end bring-up on apply is enabled but `start_action` does not include
  `start`
- the generated swanctl file does not render the expected start action
- the generated initiation helper does not call `swanctl --initiate --child`
- the generated responder config does not bind to the expected customer peer

## Operator Meaning

An operator should not need to pick a direction. The normal customer file
describes service intent and VPN compatibility. RPDB renders a package that can
respond to the customer and can also initiate from the head end when traffic or
apply policy requires it.
