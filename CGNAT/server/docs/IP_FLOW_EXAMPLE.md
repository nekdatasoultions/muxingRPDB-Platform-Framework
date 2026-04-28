# IP Flow Example

## Purpose

This document shows an example packet flow for the CGNAT design using made-up
IP addresses.

The goal is to make one key rule easy to review:

- the customer keeps targeting the same public IP used by the current
  muxer-backed service
- CGNAT changes the path, not the customer-facing target

## Example Addressing

These addresses are illustrative only.

| Role | Example |
| --- | --- |
| Customer Device | `10.20.30.10` |
| Customer original inside subnet | `10.20.30.0/24` |
| Customer inner loopback identity | `10.250.1.10` |
| Platform-assigned inside subnet | `10.128.10.0/24` |
| CGNAT ISP HEAD END customer-facing IP | `10.20.30.1` |
| CGNAT ISP HEAD END observed public IP | `203.0.113.77` |
| CGNAT HEAD END public IP | `198.51.100.50` |
| Existing customer-facing VPN public IP | `198.51.100.10` |
| CGNAT HEAD END GRE source IP | `172.31.10.10` |
| NAT-T backend GRE endpoint | `172.31.40.222` |
| NAT-T backend public loopback | `198.51.100.10` |
| Non-NAT backend GRE endpoint | `172.31.41.222` |
| Example platform service IP | `172.16.50.20` |

## High-Level Rule

The customer-facing target stays the same:

- Customer Device targets `198.51.100.10`

The transport path changes underneath:

- `Customer Device -> CGNAT ISP HEAD END -> outer tunnel -> CGNAT HEAD END -> GRE -> backend head end`

## Flow 1: Outer Tunnel Bring-Up

The first tunnel is the transport tunnel between the CGNAT ISP HEAD END and
the CGNAT HEAD END.

```text
CGNAT ISP HEAD END source: 203.0.113.77
CGNAT HEAD END public IP: 198.51.100.50
Auth method: certificate
```

### Step-by-step

1. `203.0.113.77` initiates the outer tunnel to `198.51.100.50`.
2. The CGNAT HEAD END authenticates the connection using certificates.
3. The outer tunnel becomes the trusted transport path into the CGNAT
   framework.

## Flow 2: Inner S2S VPN Bring-Up

The second tunnel is the customer service VPN.

Important:

- it does not use certificates
- it still targets the existing public IP `198.51.100.10`
- its source loopback identity for the tunnel can be `10.250.1.10`

### Step-by-step

1. Customer Device initiates the inner S2S VPN using loopback identity
   `10.250.1.10`.
2. The inner VPN destination is `198.51.100.10`.
3. The packet first reaches the CGNAT ISP HEAD END at `10.20.30.1`.
4. The CGNAT ISP HEAD END carries that traffic through the established outer
   tunnel to the CGNAT HEAD END at `198.51.100.50`.
5. The CGNAT HEAD END inspects the inner VPN destination `198.51.100.10`.
6. The CGNAT HEAD END selects the NAT-T backend path for this example.
7. The CGNAT HEAD END forwards the inner VPN across GRE to backend
   `172.31.40.222`.
8. The backend head end presents public loopback `198.51.100.10` and
   terminates the inner VPN.

## Flow 3: Example Data Packet After Inner VPN Is Up

This example assumes translation is enabled at the backend boundary.

### Original customer packet

```text
Source:      10.20.30.10
Destination: 172.16.50.20
```

### Step-by-step

1. Customer Device sends `10.20.30.10 -> 172.16.50.20`.
2. That traffic rides inside the inner VPN, which is still aimed at
   `198.51.100.10`.
3. The CGNAT ISP HEAD END carries it through the outer tunnel to the CGNAT
   HEAD END.
4. The CGNAT HEAD END forwards it across GRE to backend `172.31.40.222`.
5. The backend head end decapsulates GRE and handles the traffic after inner
   VPN termination.
6. The backend translates source `10.20.30.10` to assigned address
   `10.128.10.10`.

### Packet as seen after backend translation

```text
Source:      10.128.10.10
Destination: 172.16.50.20
```

## Flow 4: Return Traffic

### Return packet seen inside the platform

```text
Source:      172.16.50.20
Destination: 10.128.10.10
```

### Step-by-step

1. Platform service replies to `10.128.10.10`.
2. The backend head end receives that packet and reverse-translates the
   destination from `10.128.10.10` back to `10.20.30.10`.
3. The backend sends the packet back through the inner VPN context.
4. Traffic returns across GRE to the CGNAT HEAD END.
5. The CGNAT HEAD END sends it back through the outer tunnel to the CGNAT ISP
   HEAD END.
6. The CGNAT ISP HEAD END delivers it to Customer Device `10.20.30.10`.

## Path Summary

### Customer view

From the customer point of view:

- the service target is still `198.51.100.10`

### Actual packet path

From the platform point of view, the packet path is:

```text
10.20.30.10
  ->
10.20.30.1 (CGNAT ISP HEAD END)
  ->
outer tunnel to 198.51.100.50 (CGNAT HEAD END)
  ->
GRE to 172.31.40.222 (backend NAT-T head end)
  ->
public loopback / service identity 198.51.100.10
  ->
inner VPN termination
  ->
optional translation to 10.128.10.10
```

## Non-NAT Variant

If the service selects the non-NAT backend instead, the flow is the same up to
the GRE handoff, but the selected backend changes:

- GRE remote becomes `172.31.41.222`
- backend class becomes `non_nat`
- translation behavior may differ or be disabled

The important rule still stays the same:

- customer still points at the same public IP
- only the path and selected backend tier change

## Review Takeaway

The easiest short version is:

1. customer points at the same public IP as today
2. CGNAT forces the traffic through the CGNAT router path
3. CGNAT HEAD END sends it over GRE to the correct backend head end
4. backend preserves the current service termination identity
