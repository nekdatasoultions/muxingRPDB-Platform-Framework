# Head-End Customer Orchestration

## Goal

Turn the bundled `headend/` customer artifacts into a customer-scoped install,
validate, and remove flow that can be exercised repo-only against a staged
filesystem root before any live-node use.

## Helpers

- [apply_headend_customer.py](/scripts/deployment/apply_headend_customer.py)
- [validate_headend_customer.py](/scripts/deployment/validate_headend_customer.py)
- [remove_headend_customer.py](/scripts/deployment/remove_headend_customer.py)

## Required Bundle Inputs

The bundle must contain these installable head-end files:

- `headend/ipsec/ipsec-intent.json`
- `headend/ipsec/swanctl-connection.conf`
- `headend/routing/routing-intent.json`
- `headend/routing/ip-route.commands.txt`
- `headend/post-ipsec-nat/post-ipsec-nat-intent.json`
- `headend/post-ipsec-nat/nftables.apply.nft`
- `headend/post-ipsec-nat/nftables.remove.nft`
- `headend/post-ipsec-nat/nftables-state.json`
- `headend/post-ipsec-nat/activation-manifest.json`

Unresolved placeholders are not allowed in the text or JSON payloads at apply
time.

## Canonical Install Layout

When one customer is installed into a head-end root, the orchestration writes:

```text
<headend-root>/
  etc/
    swanctl/
      conf.d/
        rpdb-customers/
          <customer-name>.conf
  var/
    lib/
      rpdb-headend/
        customers/
          <customer-name>/
            artifacts/
              ipsec/
              routing/
              post-ipsec-nat/
            routing/
              ip-route.commands.txt
              apply-routes.sh
              remove-routes.sh
            post-ipsec-nat/
              nftables.apply.nft
              nftables.remove.nft
              nftables-state.json
              activation-manifest.json
              apply-post-ipsec-nat.sh
              remove-post-ipsec-nat.sh
            apply-headend-customer.sh
            remove-headend-customer.sh
            install-state.json
```

## Repo-Only Example

Install into a staged root:

```powershell
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
```

Validate the staged install:

```powershell
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
```

Remove the staged install:

```powershell
python scripts\deployment\remove_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
```

## Current Boundary

- `swanctl` customer material is installable and customer-scoped.
- route programming is installable and customer-scoped.
- post-IPsec NAT is installable and customer-scoped through generated
  `nftables` batch artifacts.
- one-to-one translated subnet intent renders nftables DNAT/SNAT maps.
- explicit host mappings render nftables DNAT/SNAT maps.
- validation checks that the rendered `swanctl` and nftables artifacts match
  the richer intent payloads before install.

That keeps the deployment path honest while integrating the head-end
install/apply/remove flow around the artifacts we can verify repo-only today.

## Verified Service-Intent Examples

The repo-only verification harness includes:

- `example-service-intent-netmap`
- `example-service-intent-explicit-host-map`

Those examples prove:

- request validation
- smart allocation
- handoff export
- environment binding
- bundle validation
- staged head-end install
- staged head-end validation
- staged head-end remove
