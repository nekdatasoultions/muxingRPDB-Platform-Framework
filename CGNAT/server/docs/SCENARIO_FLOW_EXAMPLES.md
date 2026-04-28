# Scenario Flow Examples

## Purpose

This document captures the two current CGNAT scenario patterns in the same
review style as the IP flow document.

The goal is to show:

- what we are fixing for Scenario 1
- what we are planning for Scenario 2
- how the outer and inner tunnels relate in each case
- how the customer-facing public IP stays the same while the path changes

All IPs below are illustrative only.

## Shared Architecture Rule

In both scenarios:

- the customer-facing inner VPN target remains the same public IP already used
  by the current backend service
- the CGNAT path changes the transport route underneath that target
- the backend remains the termination and optional translation boundary

That means the customer still points at the same public IP, but the packet path
becomes:

```text
customer side
  ->
CGNAT router / ISP-side function
  ->
outer tunnel
  ->
CGNAT HEAD END
  ->
GRE
  ->
backend head end
  ->
existing public loopback / service identity
```

---

## Scenario 1

## Summary

One customer device is behind an ISP using CGN.

There is a 1:1 relationship between:

- the outer tunnel
- and the inner customer service tunnel

The customer-side device is effectively both:

- the customer device
- and the logical CGNAT ISP-side endpoint

## Example Addressing

| Role | Example |
| --- | --- |
| Customer device WAN-side observed public IP | `203.0.113.77` |
| Customer device inside service IP | `10.20.30.10` |
| Customer device inner loopback | `10.250.1.10` |
| CGNAT HEAD END public IP | `198.51.100.50` |
| Existing service public IP | `198.51.100.10` |
| Backend NAT-T GRE endpoint | `172.31.40.222` |
| Backend public loopback | `198.51.100.10` |

## Outer Tunnel

### Characteristics

- between the customer device and the CGNAT HEAD END
- always initiated by the customer device
- certificate-authenticated
- IKEv2 in the current Scenario 1 assumption
- expected to run in NAT-T mode because the customer is behind CGN
- demo PKI uses a local CA on the CGNAT HEAD END

### Example

```text
Outer tunnel:
  source public IP:      203.0.113.77
  destination public IP: 198.51.100.50
  auth:                  certificate
  mode:                  NAT-T
```

## Inner Tunnel

### Characteristics

- between customer loopback `10.250.1.10`
- and existing service public IP `198.51.100.10`
- uses keys, not certificates
- for Scenario 1, initiated by the customer device
- for Scenario 1, backend head end responds to that initiation
- may stay non-NAT-T even though the outer tunnel is NAT-T

### Example

```text
Inner tunnel:
  source identity:      10.250.1.10
  destination public IP: 198.51.100.10
  auth:                  key_based
  expected mode:         non-NAT-T
```

## Scenario 1 Flow

1. Customer device behind CGN brings up the outer tunnel to `198.51.100.50`.
2. CGNAT HEAD END authenticates the customer device using certificates.
3. Customer device then initiates the inner S2S VPN toward `198.51.100.10`.
4. That inner VPN traffic traverses the already-established outer tunnel.
5. CGNAT HEAD END receives the inner tunnel traffic and selects the backend.
6. CGNAT HEAD END forwards the inner tunnel across GRE to `172.31.40.222`.
7. Backend head end presents public loopback `198.51.100.10` and terminates
   the inner VPN.

## Scenario 1 Design Fix

This scenario requires one explicit scope correction:

- the customer-side device and the CGNAT ISP-side function may be collapsed
  into one endpoint

So the framework must support:

- a collapsed 1:1 model
- outer NAT-T with inner non-NAT-T
- customer-initiated inner establishment with backend responder behavior
- local CA issuance on the CGNAT HEAD END for demo

That is now the intended first implementation target.

---

## Scenario 2

## Summary

Multiple customer devices sit behind a private APN or private network directly
interconnected with the provider side.

There is an n:1 relationship between:

- one outer tunnel
- and many inner customer service tunnels

In this case the CGNAT ISP-side function is a true shared gateway.

## Example Addressing

| Role | Example |
| --- | --- |
| ISP interconnect gateway public/transit IP | `203.0.113.88` |
| Customer device A private WAN IP | `100.64.10.10` |
| Customer device B private WAN IP | `100.64.10.11` |
| Existing service public IP | `198.51.100.10` |
| CGNAT HEAD END public IP | `198.51.100.50` |
| NAT-T backend GRE endpoint | `172.31.40.222` |
| Non-NAT backend GRE endpoint | `172.31.41.222` |

## Outer Tunnel

### Characteristics

- one provider/interconnect-owned tunnel
- between the ISP gateway and the CGNAT HEAD END
- may be NAT-T or non-NAT-T
- may be IKEv1 or IKEv2
- may allow either side to initiate depending on provider design

### Example

```text
Outer tunnel:
  source public or interconnect IP: 203.0.113.88
  destination public IP:            198.51.100.50
  auth:                             certificate or provider-agreed auth model
  mode:                             NAT-T or non-NAT-T
```

## Inner Tunnels

### Characteristics

- many inner tunnels ride inside the one outer tunnel
- each inner tunnel still targets `198.51.100.10`
- each inner tunnel still has its own service identity
- inner NAT behavior may vary by case, so the framework should not hardcode an
  assumption

### Example

```text
Inner tunnel A:
  source identity:      100.64.10.10
  destination public IP: 198.51.100.10

Inner tunnel B:
  source identity:      100.64.10.11
  destination public IP: 198.51.100.10
```

## Scenario 2 Flow

1. ISP/interconnect gateway brings up the shared outer tunnel to `198.51.100.50`.
2. CGNAT HEAD END accepts that tunnel as transport for a provider-owned access
   path.
3. Customer device A initiates its inner tunnel toward `198.51.100.10`.
4. Customer device B initiates its inner tunnel toward `198.51.100.10`.
5. Both inner tunnels are carried inside the shared outer tunnel.
6. CGNAT HEAD END separates those inner service tunnels and applies backend
   selection per tunnel.
7. Each inner tunnel is carried across GRE to the selected backend tier.
8. Backend head ends preserve the current public-facing termination identity.

## Scenario 2 Planning Implications

Scenario 2 is in scope as a planned design target, but it adds complexity in
three areas:

1. one outer access context carries multiple inner service tunnels
2. outer tunnel capabilities may vary more widely than Scenario 1
3. per-customer steering must happen inside a shared provider transport path

So Scenario 2 should be planned now, but implemented after Scenario 1 is
proven.

---

## Key Review Points

### What is fixed for Scenario 1

- collapsed customer-device / ISP-endpoint model is supported
- outer NAT-T does not force inner NAT-T
- inner target remains the existing service public IP

### What is planned for Scenario 2

- shared outer tunnel carrying many inner tunnels
- per-inner-tunnel backend selection
- support for a broader outer-tunnel capability matrix

### Common rule for both

- customer-facing destination stays the same
- CGNAT changes the path underneath
- backend remains the service termination boundary
