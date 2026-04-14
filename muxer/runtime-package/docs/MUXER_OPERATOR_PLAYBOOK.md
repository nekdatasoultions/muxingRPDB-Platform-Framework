# Muxer Operator Playbook

This playbook explains how the muxer works, how to inspect a customer, and how to run safe first-response troubleshooting on the muxer itself.

## What the muxer is doing

In `pass_through` mode the muxer is the public encrypted edge, but it is not the device that terminates customer IPsec. Its job is:

1. Load customer source-of-truth from either:
   - `config/customers.variables.yaml`
   - or DynamoDB, depending on `config/muxer.yaml`
2. Derive a deterministic customer dataplane:
   - `fwmark`
   - route table
   - GRE/IPIP interface
   - overlay `/30`
   - public-side iptables rules
3. Create or repair the customer tunnel interface.
4. Create or repair the customer `ip rule` and route table.
5. Accept only the customer's allowed encrypted protocols:
   - `UDP/500`
   - optional `UDP/4500`
   - optional `ESP/50`
6. Mark the packet in `mangle PREROUTING`.
7. Use `ip rule` to send the packet into the customer's route table.
8. Route the packet into that customer's GRE/IPIP toward the right head end.
9. On the return path, rewrite backend-originated encrypted replies so they leave as the muxer public identity.
10. Preserve separation between customers by never letting one customer's mark/table/tunnel state overlap another's.

The main code paths are:

- command entrypoint: `src/muxctl.py`
- CLI orchestration: `src/muxerlib/cli.py`
- Linux primitives: `src/muxerlib/core.py`
- pass-through apply logic: `src/muxerlib/modes.py`
- derived customer dataplane: `src/muxerlib/dataplane.py`
- customer loading and validation: `src/muxerlib/variables.py`

## Customer artifacts to read first

For one customer, the quickest way to understand intent is to read the rendered customer folder:

- `config/customers/<customer>/customer.yaml`
- `config/customers/<customer>/muxer/tunnel.yaml`
- `config/customers/<customer>/muxer/iptables.yaml`
- `config/customers/<customer>/muxer/nat.yaml`
- `config/customers/<customer>/muxer/routing.yaml`
- `config/customers/<customer>/vpn/ipsec.meta.yaml`
- `config/customers/<customer>/vpn/return-path.yaml`
- `config/customers/<customer>/vpn/post-ipsec-nat.yaml`

That shows:

- customer identity and peer IP
- protocol class
- expected tunnel mode and key
- expected `fwmark` and route table
- expected muxer NAT behavior
- expected head-end return controls
- expected post-IPsec overlap NAT model

## Source Of Truth Guardrail

Before changing a customer, confirm which backend is actually driving the live muxer:

- `config/muxer.yaml`
- `customer_sot.backend`
- `customer_sot.sync_from_variables_on_render`

Current operational rule:

- if `customer_sot.backend=dynamodb` and `sync_from_variables_on_render=false`, the live muxer follows DynamoDB, not the repo copy of `config/tunnels.d/*`
- treat `config/customers/<customer>/customer.yaml` as authoritative only after it has been rendered from the active source backend

Read these first for one customer:

```bash
sudo python3 /etc/muxer/src/muxctl.py show
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show <customer>
```

If the backend is DynamoDB, inspect the active item before changing the repo copy.

## Command playbook

### 1. List all customers known to the muxer

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py list
```

Repo-local example:

```bash
python3 scripts/muxer_customer_doctor.py list --config-root "$(pwd)"
```

### 2. Show the high-level derived state for all customers

```bash
sudo python3 /etc/muxer/src/muxctl.py show
```

This is the fastest built-in summary from the muxer itself.

### 3. Show one customer's expected and observed state

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show <customer-name>
```

Examples:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show example-nat-snat-0001
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show 1
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show 198.51.100.10
```

What this gives you:

- customer class and protocol set
- expected mark/table/tunnel/backend
- expected muxer delivery destination
- expected head-end cluster type
- whether rendered customer artifacts exist
- live tunnel, policy, and iptables checks
- concrete repair hints

### 4. Check one customer for drift

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py check <customer-name>
```

Use this when you suspect:

- tunnel missing
- route table missing
- `ip rule` missing
- iptables rules missing or stale

### 5. Run the safe repair path

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer-name>
```

What `repair` does:

- re-runs muxer `apply` if repairable muxer drift is detected
- rebuilds tunnel/policy/iptables state via the normal muxer control path
- re-checks the customer afterward

This is intentionally conservative. It does not try to hand-edit random individual rules before it proves the normal muxer control path cannot fix the issue.

### 6. Use targeted conntrack cleanup after a head-end move

If a customer was moved from one head end to another and negotiation still appears pinned to the old path, flush the peer-specific muxer conntrack state:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer-name> --flush-peer-conntrack
```

This is the safe scripted version of the migration lesson we saw repeatedly:

- config was correct
- but stale peer-specific conntrack on the muxer kept steering replies like the old path still existed

### 7. Update the active customer SoT after a clean migration

If the doctor says the live runtime is internally consistent but the expected backend config is stale, update the active customer SoT instead of forcing the muxer back to the old head end.

Preview the change first:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer-name> --dry-run
```

Then write it:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer-name>
```

Current guardrails:

- only writes when the customer is classified as clean migration drift
- refuses if the customer still has real repairable failures
- currently supports DynamoDB-backed customer SoT

### 8. Inspect rendered customer inputs manually

```bash
CUSTOMER=example-nat-snat-0001
sed -n '1,200p' /etc/muxer/config/customers/${CUSTOMER}/customer.yaml
sed -n '1,200p' /etc/muxer/config/customers/${CUSTOMER}/muxer/tunnel.yaml
sed -n '1,200p' /etc/muxer/config/customers/${CUSTOMER}/muxer/iptables.yaml
sed -n '1,200p' /etc/muxer/config/customers/${CUSTOMER}/muxer/nat.yaml
sed -n '1,200p' /etc/muxer/config/customers/${CUSTOMER}/muxer/routing.yaml
```

### 9. Inspect live Linux runtime manually

```bash
CUSTOMER=example-nat-snat-0001
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show "${CUSTOMER}"
sudo ip -d tunnel show <customer-tunnel-if>
sudo ip -o -4 addr show dev <customer-tunnel-if>
sudo ip rule show
sudo ip route show table <customer-table>
sudo iptables-save | grep -E '<peer-ip>|<mark>|<tunnel-if>'
```

## How to read customer state

### Strict non-NAT customer

Traits:

- `UDP/500=true`
- `UDP/4500=false`
- `ESP/50=true`
- head-end return path should show:
  - `encapsulation=no`
  - explicit `left_public`
  - VTI/mark controls when required

These customers are sensitive to identity drift. If they flip to `4500`, the root cause is often edge identity behavior, not just GRE or policy routing.

Current proven AWS pattern for legacy strict peers:

- keep the muxer backend delivery destination on the shared public identity
- keep `protocols.force_rewrite_4500_to_500=false`
- set `natd_rewrite.enabled=true`
- keep the head end on strict non-NAT (`encapsulation=no`)

Why this matters:

- the peer may still arrive at the muxer on clean `UDP/500` and `ESP/50`
- AWS/public-edge translation can still make the head end believe NAT is present unless the muxer rewrites NAT-D payloads
- if strict mode is healthy, you should see clean `500/ESP` on the head end and not a forced `4500` control path

Current operator warning:

- do not mix `natd_rewrite.enabled=true` and `force_rewrite_4500_to_500=true`
- choose one mode deliberately
- for the current strict AWS path, NAT-D rewrite is the working mode

### NAT-T customer

Traits:

- `UDP/500=true`
- `UDP/4500=true`
- head-end return path typically shows `encapsulation=yes`
- post-IPsec NAT may be active to solve overlap after decrypt

These customers are more likely to survive AWS/public-edge NAT behavior, but still depend on correct mark/table/tunnel steering.

## Troubleshooting workflow

### Symptom: customer is missing from `muxctl show`

Check:

- `config/muxer.yaml`
- source backend in `customer_sot.backend`
- `config/customers.variables.yaml` or DynamoDB contents
- render step

Commands:

```bash
sudo python3 /etc/muxer/src/muxctl.py show
python3 /etc/muxer/scripts/render_customer_variables.py --source variables --prune
python3 /etc/muxer/scripts/sync_customers_to_dynamodb.py --create-table
```

### Symptom: tunnel interface missing

Likely cause:

- muxer apply never ran
- underlay identities drifted
- interface was deleted manually

Commands:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py check <customer>
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer>
```

### Symptom: mark/table rules missing

Likely cause:

- policy routing drift
- partial flush

Commands:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py check <customer>
sudo python3 /etc/muxer/src/muxctl.py apply
```

### Symptom: customer was moved to a new head end but traffic still behaves like the old path

Likely cause:

- stale peer conntrack on the muxer

Command:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer> --flush-peer-conntrack
```

### Symptom: customer is healthy on the new head end but the doctor still shows migration drift

Likely cause:

- the live migrated path is correct
- the active customer SoT still points at the old backend underlay

Commands:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show <customer>
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer> --dry-run
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer>
```

### Symptom: strict customer unexpectedly starts behaving like NAT-T

Likely cause:

- public-edge identity drift
- backend/local identity mismatch
- incompatible public edge for strict non-NAT

The muxer doctor can confirm the transport and rule state, but if those are correct the next place to inspect is the head-end `left_public` / `leftid` / loopback identity model.

### Symptom: strict customer decaps inbound traffic but shows no outbound payload bytes

Likely cause:

- the tunnel is healthy, but return traffic from the demo/core side is not routed back to the non-NAT head end
- or the muxer customer still has the wrong strict-mode setting (`force_rewrite_4500_to_500` vs `natd_rewrite`)

Checks:

```bash
sudo journalctl -u ike-nat-bridge -n 50 --no-pager
sudo swanctl --list-sas --raw | sed -n '/<customer>/,/^$/p'
ip -s link show <strict-vti-if>
```

On the demo or core host, confirm the return route for the remote protected IP:

```bash
ip route get <remote-protected-ip>
```

Example from the current `legacy-cust0002` validation:

```bash
sudo ip route replace 10.129.3.154/32 via 172.31.59.220 dev ens5
```

If that route is missing, the tunnel can look healthy while only inbound bytes increase.

## Recommended day-of commands

List customers:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py list
```

Inspect one customer:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py show <customer>
```

Check and repair one customer:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer>
```

Check and repair one migrated customer with targeted conntrack cleanup:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py repair <customer> --flush-peer-conntrack
```

Update active SoT after a clean head-end migration:

```bash
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer> --dry-run
sudo python3 /etc/muxer/scripts/muxer_customer_doctor.py update-sot <customer>
```

Rebuild full muxer state manually:

```bash
sudo python3 /etc/muxer/src/muxctl.py apply
```
