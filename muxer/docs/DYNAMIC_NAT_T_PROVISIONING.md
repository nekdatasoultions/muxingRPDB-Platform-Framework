# Dynamic NAT-T Provisioning

## Purpose

Dynamic NAT-T provisioning handles customers whose first safe onboarding shape
is strict non-NAT, but whose live IKE behavior later proves they need NAT-T.

The important distinction:

- detection produces a repo-only promotion package
- detection does not apply live changes
- detection does not mutate the old customer package in place

## Default Starting Point

When the customer NAT behavior is unknown, start with strict non-NAT:

- `customer_class: strict-non-nat`
- `backend.cluster: non-nat`
- `protocols.udp500: true`
- `protocols.udp4500: false`
- `protocols.esp50: true`

This means the initial package is allocated from non-NAT pools and binds to
the non-NAT stack.

## Promotion Trigger

If the muxer observes UDP/4500 from the same customer peer, the customer should
be planned for NAT-T promotion.

The repo-only trigger facts are:

- peer IP matches the customer request
- observed protocol is UDP
- observed destination port is `4500`
- UDP/500 was observed first when the request requires that guardrail

## Customer Request Shape

Dynamic customers carry this section:

```yaml
dynamic_provisioning:
  enabled: true
  mode: nat_t_auto_promote
  initial_customer_class: strict-non-nat
  initial_backend_cluster: non-nat
  trigger:
    protocol: udp
    destination_port: 4500
    require_initial_udp500_observation: true
    observation_window_seconds: 300
    confirmation_packets: 1
  promotion:
    customer_class: nat
    backend_cluster: nat
    protocols:
      udp500: true
      udp4500: true
      esp50: false
```

See the committed example:

- `muxer/config/customer-requests/examples/example-dynamic-default-nonnat.yaml`

## Repo-Only Promotion Command

Generate a NAT-T promotion request:

```powershell
$CustomerName = "example-dynamic-default-nonnat"
$WorkRoot = "build\onboarding\$CustomerName"
$InitialRequest = "muxer\config\customer-requests\examples\example-dynamic-default-nonnat.yaml"
$PromotedRequest = "$WorkRoot\promoted-nat-request.yaml"
$PromotionSummary = "$WorkRoot\promotion-summary.json"

python muxer\scripts\plan_nat_t_promotion.py $InitialRequest `
  --observed-peer 203.0.113.55 `
  --observed-protocol udp `
  --observed-dport 4500 `
  --initial-udp500-observed `
  --request-out $PromotedRequest `
  --summary-out $PromotionSummary `
  --json
```

Then validate and provision the promoted request repo-only:

```powershell
python muxer\scripts\validate_customer_request.py $PromotedRequest

python muxer\scripts\provision_customer_request.py $PromotedRequest `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --replace-customer $CustomerName `
  --source-out "$WorkRoot\promoted-customer-source.yaml" `
  --module-out "$WorkRoot\promoted-customer-module.json" `
  --item-out "$WorkRoot\promoted-customer-ddb-item.json" `
  --allocation-out "$WorkRoot\promoted-allocation-summary.json"
```

`--replace-customer` is repo-only planning behavior. It tells the allocator to
ignore the old same-name non-NAT package while creating the proposed NAT
replacement package. It does not release live reservations by itself.

## Review Points

Before any live deployment, review:

- initial package allocated from non-NAT pools
- promoted package allocated from NAT pools
- promoted package enables UDP/4500
- peer IP in the observed event matches the customer peer
- no live database writes happened
- no live muxer or head-end apply happened
- rollback owner decides whether old non-NAT reservations are retained or
  released after cutover

## Live Gate

Live promotion is a separate approved deployment.

Do not convert the repo-only promotion package into a live change until backups,
change window, validation owner, rollback owner, and exact apply commands are
approved.
