# Muxer End-to-End Demo Runbook

This runbook combines:

- a narrated stage-by-stage packet-path demo
- a command-driven demo shell script
- an optional end-to-end file-transfer proof

The scripts are:

- `<legacy-muxer3-repo>\scripts\demo_muxer_end_to_end.sh`
- `<legacy-muxer3-repo>\scripts\demo_file_transfer.sh`

## Purpose

Use this when we want to show:

1. how the muxer classifies and routes encrypted traffic
2. how the muxer hands traffic to the correct VPN head end
3. how return traffic is rewritten back to the shared public identity
4. that a real payload can move through the VPN path into the backend

## Demo modes

### NAT-T demo

Uses live example customer:

- `vpn-customer-stage1-15-cust-0001`

Run:

```bash
bash /etc/muxer/scripts/demo_muxer_end_to_end.sh --mode nat_t
```

Live inspection mode:

```bash
sudo bash /etc/muxer/scripts/demo_muxer_end_to_end.sh --mode nat_t --inspect
```

### NAT-T pair demo for customers 3 and 4

Uses live NAT-T customers:

- `vpn-customer-stage1-15-cust-0003`
- `vpn-customer-stage1-15-cust-0004`

Run:

```bash
sudo bash /etc/muxer/scripts/demo_muxer_end_to_end.sh \
  --customer-name vpn-customer-stage1-15-cust-0003 \
  --customer-name vpn-customer-stage1-15-cust-0004 \
  --inspect
```

This is useful when we want to show that two separate customer peers:

- get different marks
- get different route tables
- get different GRE interfaces
- but still land on the same NAT VPN head end

### Strict non-NAT demo

Uses live example customer:

- `legacy-cust0002`

Run:

```bash
bash /etc/muxer/scripts/demo_muxer_end_to_end.sh --mode strict_nonnat
```

Live inspection mode:

```bash
sudo bash /etc/muxer/scripts/demo_muxer_end_to_end.sh --mode strict_nonnat --inspect
```

## Optional file-transfer proof

If we want the demo to end with a real payload transfer to a backend host
reachable through the VPN, run the muxer demo with `--transfer-cmd`.

Example upload-only proof:

```bash
bash /etc/muxer/scripts/demo_muxer_end_to_end.sh \
  --mode nat_t \
  --transfer-cmd "/etc/muxer/scripts/demo_file_transfer.sh --remote ec2-user@10.129.3.154:/tmp/mux-demo.bin"
```

Example round-trip proof:

```bash
bash /etc/muxer/scripts/demo_muxer_end_to_end.sh \
  --mode nat_t \
  --transfer-cmd \"/etc/muxer/scripts/demo_file_transfer.sh \
    --remote ec2-user@10.129.3.154:/tmp/mux-demo.bin \
    --roundtrip ec2-user@10.129.3.154:/tmp/mux-demo-return.bin \
    --size-mb 8\"
```

## What the demo script does

For the selected customer class it prints:

1. customer identity and muxer routing values
2. one-time transport setup
3. ingress filtering
4. packet marking
5. muxer NAT rewrite behavior
6. policy-routing lookup
7. GRE forwarding to the correct head end
8. head-end termination note
9. return-path rewrite
10. optional file-transfer proof

When `--customer-name` is used, the script loads the rendered customer module
from:

- `/etc/muxer/config/customers/<name>/customer.yaml`

That means customers 3 and 4 use their real rendered values instead of the old
hardcoded example customer.

With `--inspect`, the demo script also runs read-only live checks including:

- `ip -d tunnel show`
- `ip addr show`
- `ip rule show`
- `ip route show table <id>`
- `iptables -S MUXER_FILTER`
- `iptables -t mangle -S MUXER_MANGLE`
- `iptables -t nat -S MUXER_NAT_PRE`
- `iptables -t nat -S MUXER_NAT_POST`
- `python3 /etc/muxer/scripts/muxer_customer_doctor.py show <customer>` when available

Important:

- the printed statements are the canonical example flow for the chosen customer
  class
- the inspection output shows the live muxer runtime equivalents
- those can differ in interface names or active underlay IPs after migrations or
  node replacement, which is expected and often useful to show during a demo

## What the file-transfer script does

The file-transfer helper:

1. creates a random payload
2. prints its checksum
3. uploads it with `scp`
4. optionally downloads a round-trip copy
5. prints the returned checksum

That gives us a clean “real data moved through the path” proof at the end of
the architectural demo.

## Suggested talk track

### NAT-T

- Packet arrives on the muxer public edge on UDP 4500.
- MUXER_FILTER accepts only the known peer.
- MUXER_MANGLE sets the customer mark.
- MUXER_NAT_PRE rewrites the packet toward the NAT VPN head end.
- Linux policy routing selects the customer route table.
- The route table sends the packet into the customer GRE tunnel.
- The NAT head end terminates IPsec.
- Return traffic comes back over GRE.
- MUXER_NAT_POST rewrites the source back to the muxer edge identity.
- File transfer proves payload delivery through the path.

### Strict non-NAT

- Packet arrives on the muxer public edge on UDP 500 or ESP 50.
- MUXER_FILTER accepts only the known peer.
- MUXER_MANGLE sets the customer mark.
- MUXER_NAT_PRE preserves the shared public identity semantics expected by the
  strict peer.
- Linux policy routing selects the customer route table.
- The route table sends the packet into the customer GRE tunnel.
- The non-NAT head end terminates IPsec with strict settings.
- Return traffic comes back over GRE.
- MUXER_NAT_POST rewrites the source back to the muxer edge identity.
- File transfer proves payload delivery through the path.
