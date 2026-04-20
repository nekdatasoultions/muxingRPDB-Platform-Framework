# Single-Instance Libreswan Quickstart

Purpose: stand up one Libreswan endpoint on one host now, while MUXER3 multi-customer code continues in parallel.

Current label for this interim deployment: **CUST0003 (`cust-0003`)**.

## 1) Install dependencies (Amazon Linux 2023)

```bash
sudo bash scripts/install_libreswan_single_amzn.sh
```

## 2) Create single-connection env file

```bash
sudo mkdir -p /etc/muxer
sudo cp config/libreswan/single-instance.env.example /etc/muxer/single-instance.env
sudo vi /etc/muxer/single-instance.env
```

Set at minimum:

- `CONNECTION_NAME`
- `REMOTE_PUBLIC_IP`
- `LOCAL_ID`
- `REMOTE_ID`
- `LEFT_SUBNET`
- `RIGHT_SUBNET`
- `PSK`

Policy switch:

- strict non-NAT peer: `ENCAPSULATION=no`
- NAT-capable peer: `ENCAPSULATION=auto`
- strict non-NAT peer: set `LOCAL_PUBLIC_IP` to the shared public VPN `/32`, not `%defaultroute`
- strict non-NAT peer: do not assume a plain AWS EIP edge preserves native `udp/500 + esp/50`; prove the ingress model first

## 3) Render and apply Libreswan config

```bash
sudo bash scripts/render_libreswan_single.sh /etc/muxer/single-instance.env
```

This writes:

- `/etc/ipsec.d/<CONNECTION_NAME>.conf`
- `/etc/ipsec.d/<CONNECTION_NAME>.secrets`

## 4) Verify control plane

```bash
sudo ipsec status
sudo ipsec auto --status
sudo journalctl -u ipsec --since "15 min ago" --no-pager
```

## 5) Verify packet plane

```bash
sudo tcpdump -ni any "host <peer_public_ip> and (udp port 500 or udp port 4500 or proto 50)"
```

Success pattern:

- IKE SA established
- CHILD SA installed
- encaps/decaps counters rise during traffic

## 6) Force rekey/reset if needed

```bash
sudo ipsec auto --down <CONNECTION_NAME> || true
sudo ipsec auto --up <CONNECTION_NAME>
```

## 7) Notes

- This is a temporary single-instance mode.
- Target design remains per-customer isolated Libreswan runtimes (container/netns).
