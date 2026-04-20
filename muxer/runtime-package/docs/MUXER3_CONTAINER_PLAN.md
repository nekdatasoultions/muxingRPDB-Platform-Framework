## MUXER3 Container Plan

### Objective

Remove 8000V from the data plane and terminate customer IPsec on the muxer host using isolated per-customer Libreswan instances.

### High-level topology

- Public edge: muxer host (`public_if`)
- Isolation unit: one container or one netns per customer
- Steering: `iptables` + `ip rule` marks by customer peer/protocol
- Tenant handoff: per-customer transport interface (`ipip` or `gre`) as needed

### Benefits

- Overlapping customer protected IP space is supported.
- Per-customer policy and keys are isolated.
- Removes tunnel-interface crypto map limitations from 8000V.

### Constraints

- NATed peers still require NAT-T behavior per IKEv2 standards.
- Strict `udp/500 + esp/50` only is viable only when no NAT exists in path.

### Implementation phases

1. Add customer namespace/container lifecycle management to `muxctl.py`.
2. Render per-customer Libreswan configs under isolated runtime paths.
3. Bind ingress policy to customer isolation unit.
4. Add health/trace checks per customer.
5. Add rollback path and backup/restore scripts.
