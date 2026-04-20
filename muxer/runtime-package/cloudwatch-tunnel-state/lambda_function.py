import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

import boto3

ssm = boto3.client("ssm")
cw = boto3.client("cloudwatch")
ec2 = boto3.client("ec2")

NAMESPACE = os.getenv("NAMESPACE", "VPN/TunnelState")
TOPOLOGY_PATH = Path(os.getenv("TOPOLOGY_PATH", Path(__file__).with_name("monitoring_topology.json")))

_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def _load_topology() -> dict:
    with TOPOLOGY_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _chunk(items: List[dict], size: int) -> List[List[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _run_ssm(instance_id: str, commands: List[str], timeout_sec: int = 120) -> Tuple[str, str, str]:
    try:
        resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
        )
    except Exception as exc:
        return "Failed", "", str(exc)
    command_id = resp["Command"]["CommandId"]

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(2)
            continue

        status = inv.get("Status", "Unknown")
        if status in {
            "Success",
            "Cancelled",
            "Failed",
            "TimedOut",
            "Undeliverable",
            "Terminated",
            "InvalidPlatform",
            "AccessDenied",
        }:
            return status, inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")
        time.sleep(2)

    return "TimedOut", "", f"Timed out waiting for command on {instance_id}"


def _parse_scalar_kv(stdout: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _to_bytes(value: str) -> int:
    token = value.strip().upper()
    if not token:
        return 0
    match = re.match(r"^([0-9]+(?:\\.[0-9]+)?)([KMGTP]?B)?$", token)
    if not match:
        return 0
    magnitude = float(match.group(1))
    unit = match.group(2) or "B"
    return int(magnitude * _SIZE_UNITS.get(unit, 1))


def _resolve_active_instance(instance_ids: List[str]) -> Tuple[str, dict]:
    if not instance_ids:
        return "", {"status": "Skipped", "stderr": "no instance ids"}

    probe = [
        "ROLE=unknown",
        "[ -f /run/muxingplus-ha/role ] && ROLE=$(cat /run/muxingplus-ha/role 2>/dev/null || echo unknown)",
        'echo "role=$ROLE"',
        'hostname | sed "s/^/hostname=/"',
    ]

    candidates = []
    for instance_id in instance_ids:
        status, stdout, stderr = _run_ssm(instance_id, probe, timeout_sec=60)
        kv = _parse_scalar_kv(stdout)
        role = kv.get("role", "").strip().lower()
        candidate = {
            "instance": instance_id,
            "status": status,
            "role": role,
            "hostname": kv.get("hostname", ""),
            "stderr": stderr[-500:],
        }
        candidates.append(candidate)
        if status == "Success" and role == "active":
            return instance_id, {"status": status, "selected": instance_id, "candidates": candidates}

    for candidate in candidates:
        if candidate["status"] == "Success":
            return candidate["instance"], {"status": "Fallback", "selected": candidate["instance"], "candidates": candidates}

    return instance_ids[0], {"status": "Fallback", "selected": instance_ids[0], "candidates": candidates}


def _get_ssm_managed_instance_ids(instance_ids: List[str]) -> List[str]:
    if not instance_ids:
        return []
    try:
        resp = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": instance_ids}],
        )
    except Exception:
        return instance_ids
    managed = {item["InstanceId"] for item in resp.get("InstanceInformationList", [])}
    return [instance_id for instance_id in instance_ids if instance_id in managed]


def _collect_ipsec(instance_id: str, conn_names: List[str]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], dict]:
    if not conn_names:
        return {}, {}, {}, {"instance": instance_id, "status": "Skipped", "stderr": "no conn names"}

    script = f"""STATUS_FILE="$(mktemp)"
BACKEND="unknown"
if command -v swanctl >/dev/null 2>&1 && systemctl is-active --quiet strongswan; then
  BACKEND="strongswan"
  swanctl --list-sas --raw > "$STATUS_FILE" 2>/dev/null || true
elif command -v ipsec >/dev/null 2>&1; then
  BACKEND="libreswan"
  ipsec auto --status > "$STATUS_FILE" 2>/dev/null || true
fi
echo "__backend=$BACKEND"
python3 - "$STATUS_FILE" "$BACKEND" <<'PY'
import re
import sys
from pathlib import Path

status_lines = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore").splitlines()
backend = sys.argv[2].strip()
conn_names = {json.dumps(conn_names)}

for conn in conn_names:
    up = 0
    traffic_in = "0"
    traffic_out = "0"

    if backend == "strongswan":
        conn_marker = "{{" + conn + " {{"
        for line in status_lines:
            if conn_marker not in line:
                continue
            state_match = re.search(r"\\bstate=(?P<state>[A-Z_]+)\\b", line)
            if state_match and state_match.group("state") == "ESTABLISHED":
                up = 1
                break
    else:
        conn_re = re.escape(conn)
        line_re = re.compile(rf'^0+\\s+"{{conn_re}}"(?:\\[\\d+\\])?:')
        for line in status_lines:
            if not line_re.search(line):
                continue

            if re.search(r"(?:STATE_[A-Z0-9_]*ESTABLISHED|IPsec SA established|IKE SA established)", line):
                up = 1

            if "+UP+" in line:
                up = 1

            newest_ipsec = re.search(r"newest IPsec SA: #(\\d+)", line)
            if newest_ipsec and int(newest_ipsec.group(1)) > 0:
                up = 1

            if "Traffic:" in line:
                m_in = re.search(r"ESPin=(\\S+)", line)
                m_out = re.search(r"ESPout=(\\S+)", line)
                if m_in:
                    traffic_in = m_in.group(1)
                if m_out:
                    traffic_out = m_out.group(1)

    print(f"{{conn}}.up={{up}}")
    print(f"{{conn}}.in={{traffic_in}}")
    print(f"{{conn}}.out={{traffic_out}}")
PY
rm -f "$STATUS_FILE"
"""
    status, stdout, stderr = _run_ssm(instance_id, [script], timeout_sec=140)
    up_map: Dict[str, int] = {}
    in_map: Dict[str, int] = {}
    out_map: Dict[str, int] = {}
    kv = _parse_scalar_kv(stdout)
    backend = kv.get("__backend", "unknown")

    for conn in conn_names:
        up_map[conn] = 1 if kv.get(f"{conn}.up", "0") == "1" else 0
        in_map[conn] = _to_bytes(kv.get(f"{conn}.in", "0"))
        out_map[conn] = _to_bytes(kv.get(f"{conn}.out", "0"))

    return up_map, in_map, out_map, {"instance": instance_id, "status": status, "backend": backend, "stderr": stderr[-500:]}


def _collect_transport(instance_id: str, interfaces: List[str]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], dict]:
    unique_interfaces = sorted(set(interfaces))
    if not unique_interfaces:
        return {}, {}, {}, {"instance": instance_id, "status": "Skipped", "stderr": "no transport interfaces"}

    iface_blob = " ".join(unique_interfaces)
    script = f"""for i in {iface_blob}; do
  if ip link show "$i" >/dev/null 2>&1; then
    B="$(ip -d link show "$i" 2>/dev/null || true)"
    if echo "$B" | grep -q "LOWER_UP"; then
      echo "$i.up=1"
    else
      echo "$i.up=0"
    fi
    RX="$(cat /sys/class/net/$i/statistics/rx_bytes 2>/dev/null || echo 0)"
    TX="$(cat /sys/class/net/$i/statistics/tx_bytes 2>/dev/null || echo 0)"
    echo "$i.rx=$RX"
    echo "$i.tx=$TX"
  else
    echo "$i.up=0"
    echo "$i.rx=0"
    echo "$i.tx=0"
  fi
done
"""
    status, stdout, stderr = _run_ssm(instance_id, [script], timeout_sec=140)
    kv = _parse_scalar_kv(stdout)
    up_map: Dict[str, int] = {}
    rx_map: Dict[str, int] = {}
    tx_map: Dict[str, int] = {}

    for iface in unique_interfaces:
        up_map[iface] = 1 if kv.get(f"{iface}.up", "0") == "1" else 0
        try:
            rx_map[iface] = int(kv.get(f"{iface}.rx", "0"))
        except (TypeError, ValueError):
            rx_map[iface] = 0
        try:
            tx_map[iface] = int(kv.get(f"{iface}.tx", "0"))
        except (TypeError, ValueError):
            tx_map[iface] = 0

    return up_map, rx_map, tx_map, {"instance": instance_id, "status": status, "stderr": stderr[-500:]}


def _get_customer_public_ips(customers: List[dict]) -> Dict[str, str]:
    customer_names = sorted({str(c.get("customer", "")).strip() for c in customers if str(c.get("customer", "")).strip()})
    if not customer_names:
        return {}

    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": customer_names},
            {"Name": "instance-state-name", "Values": ["running", "pending", "stopping", "stopped"]},
        ]
    )

    ip_map: Dict[str, str] = {}
    for res in resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            name = ""
            for tag in inst.get("Tags", []):
                if tag.get("Key") == "Name":
                    name = tag.get("Value", "")
                    break
            if not name:
                continue
            ip_map[name] = inst.get("PublicIpAddress", "") or ""

    return ip_map


def _get_instance_labels(instance_ids: List[str]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    unique_ids = sorted(set(i for i in instance_ids if i))
    if not unique_ids:
        return labels

    resp = ec2.describe_instances(InstanceIds=unique_ids)
    for res in resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            iid = inst.get("InstanceId", "")
            if not iid:
                continue
            name = ""
            for tag in inst.get("Tags", []):
                if tag.get("Key") == "Name":
                    name = tag.get("Value", "")
                    break
            private_ip = inst.get("PrivateIpAddress", "") or ""
            if name and private_ip:
                labels[iid] = f"{name} ({private_ip})"
            elif name:
                labels[iid] = name
            elif private_ip:
                labels[iid] = f"{iid} ({private_ip})"
            else:
                labels[iid] = iid
    return labels


def lambda_handler(event, context):
    topology = _load_topology()
    customers = topology["customers"]
    hubs = {hub["name"]: hub for hub in topology["hubs"]}
    muxer_name = topology["muxer"]["name"]

    muxer_candidates = _get_ssm_managed_instance_ids(topology["muxer"]["instances"])
    if not muxer_candidates:
        raise RuntimeError("No SSM-managed muxer instances available for monitoring")
    active_muxer_instance, muxer_resolve_dbg = _resolve_active_instance(muxer_candidates)
    muxer_resolve_dbg["requested_instances"] = topology["muxer"]["instances"]
    muxer_resolve_dbg["managed_instances"] = muxer_candidates
    active_hub_instances: Dict[str, str] = {}
    hub_resolve_dbg: Dict[str, dict] = {}
    for hub_name, hub in hubs.items():
        hub_candidates = _get_ssm_managed_instance_ids(hub["instances"])
        if not hub_candidates:
            raise RuntimeError(f"No SSM-managed instances available for hub {hub_name}")
        active_hub_instances[hub_name], hub_resolve_dbg[hub_name] = _resolve_active_instance(hub_candidates)
        hub_resolve_dbg[hub_name]["requested_instances"] = hub["instances"]
        hub_resolve_dbg[hub_name]["managed_instances"] = hub_candidates

    customer_public_ip_map = _get_customer_public_ips(customers)
    instance_labels = _get_instance_labels([active_muxer_instance] + list(active_hub_instances.values()))

    ipsec_results: Dict[str, Tuple[Dict[str, int], Dict[str, int], Dict[str, int], dict]] = {}
    for hub_name, instance_id in active_hub_instances.items():
        hub_conns = [c["conn"] for c in customers if c["hub"] == hub_name]
        ipsec_results[hub_name] = _collect_ipsec(instance_id, hub_conns)

    transport_ifaces = [c["transport_interface"] for c in customers]
    transport_up, transport_rx, transport_tx, transport_dbg = _collect_transport(active_muxer_instance, transport_ifaces)
    transport_probe_ok = transport_dbg.get("status") == "Success"
    if not transport_probe_ok:
        transport_dbg["degraded_mode"] = "ipsec_proxy"

    metrics: List[dict] = []
    summary: Dict[str, dict] = {}
    hub_ipsec_in_total: Dict[str, int] = {}
    hub_ipsec_out_total: Dict[str, int] = {}
    total_ipsec_in = 0
    total_ipsec_out = 0
    total_transport_rx = 0
    total_transport_tx = 0
    transport_seen = set()

    for customer in customers:
        conn = customer["conn"]
        cust = customer["customer"]
        hub_name = customer["hub"]
        transport_if = customer["transport_interface"]
        public_ip = customer.get("public_ip", "") or customer_public_ip_map.get(cust, "")
        transport_both_ends = f'{customer.get("transport_muxer_ip", "")} <-> {customer.get("transport_hub_ip", "")}'.strip()
        transport_type = customer.get("transport_type", "TRANSPORT")
        ipsec_mode = customer.get("ipsec_mode", "IKEv2")
        ipsec_instance = active_hub_instances[hub_name]
        ipsec_node = instance_labels.get(ipsec_instance, ipsec_instance)
        muxer_node = instance_labels.get(active_muxer_instance, active_muxer_instance)

        hub_up, hub_in, hub_out, _ = ipsec_results[hub_name]
        ipsec_up = hub_up.get(conn, 0)
        ipsec_in_bytes = hub_in.get(conn, 0)
        ipsec_out_bytes = hub_out.get(conn, 0)
        if transport_probe_ok:
            transport_link_up = transport_up.get(transport_if, 0)
            transport_rx_bytes = transport_rx.get(transport_if, 0)
            transport_tx_bytes = transport_tx.get(transport_if, 0)
            transport_source = "ssm"
        else:
            transport_link_up = 1 if ipsec_up == 1 else 0
            transport_rx_bytes = 0
            transport_tx_bytes = 0
            transport_source = "ipsec_proxy"
        tunnel_up = 1 if (ipsec_up == 1 and transport_link_up == 1) else 0
        tunnel_status = "UP" if tunnel_up == 1 else "DOWN"

        summary[cust] = {
            "public_ip": public_ip,
            "transport_both_ends": transport_both_ends,
            "transport_type": transport_type,
            "ipsec_mode": ipsec_mode,
            "hub": hub_name,
            "ipsec_up": ipsec_up,
            "transport_up": transport_link_up,
            "tunnel_up": tunnel_up,
            "tunnel_status": tunnel_status,
            "ipsec_in_bytes": ipsec_in_bytes,
            "ipsec_out_bytes": ipsec_out_bytes,
            "transport_rx_bytes": transport_rx_bytes,
            "transport_tx_bytes": transport_tx_bytes,
            "transport_source": transport_source,
            "ipsec_node": ipsec_node,
            "muxer_node": muxer_node,
        }

        hub_ipsec_in_total[hub_name] = hub_ipsec_in_total.get(hub_name, 0) + ipsec_in_bytes
        hub_ipsec_out_total[hub_name] = hub_ipsec_out_total.get(hub_name, 0) + ipsec_out_bytes
        total_ipsec_in += ipsec_in_bytes
        total_ipsec_out += ipsec_out_bytes
        if transport_if not in transport_seen:
            total_transport_rx += transport_rx_bytes
            total_transport_tx += transport_tx_bytes
            transport_seen.add(transport_if)

        base_dims = [{"Name": "Customer", "Value": cust}, {"Name": "Hub", "Value": hub_name}]
        mux_dims = base_dims + [{"Name": "Muxer", "Value": muxer_name}]
        path_dims = [{"Name": "Hub", "Value": hub_name}, {"Name": "Muxer", "Value": muxer_name}, {"Name": "TransportInterface", "Value": transport_if}]

        metrics.append({"MetricName": "IpsecUp", "Dimensions": base_dims, "Value": ipsec_up, "Unit": "Count"})
        metrics.append({"MetricName": "TransportUp", "Dimensions": mux_dims, "Value": transport_link_up, "Unit": "Count"})
        metrics.append({"MetricName": "TunnelUp", "Dimensions": mux_dims, "Value": tunnel_up, "Unit": "Count"})
        metrics.append({"MetricName": "IpsecInBytes", "Dimensions": base_dims, "Value": ipsec_in_bytes, "Unit": "Bytes"})
        metrics.append({"MetricName": "IpsecOutBytes", "Dimensions": base_dims, "Value": ipsec_out_bytes, "Unit": "Bytes"})
        metrics.append({"MetricName": "TransportRxBytes", "Dimensions": path_dims, "Value": transport_rx_bytes, "Unit": "Bytes"})
        metrics.append({"MetricName": "TransportTxBytes", "Dimensions": path_dims, "Value": transport_tx_bytes, "Unit": "Bytes"})
        metrics.append({"MetricName": "GreUp", "Dimensions": mux_dims, "Value": transport_link_up, "Unit": "Count"})
        metrics.append({"MetricName": "GreRxBytes", "Dimensions": mux_dims, "Value": transport_rx_bytes, "Unit": "Bytes"})
        metrics.append({"MetricName": "GreTxBytes", "Dimensions": mux_dims, "Value": transport_tx_bytes, "Unit": "Bytes"})

        print(
            json.dumps(
                {
                    "type": "customer_state",
                    "customer": cust,
                    "public_ip": public_ip,
                    "transport_both_ends": transport_both_ends,
                    "gre_both_ends": transport_both_ends,
                    "transport_type": transport_type,
                    "ipsec_mode": ipsec_mode,
                    "vpn_hub": hub_name,
                    "tunnel_status": tunnel_status,
                    "ipsec_up": ipsec_up,
                    "transport_up": transport_link_up,
                    "gre_up": transport_link_up,
                    "tunnel_up": tunnel_up,
                    "ipsec_in_bytes": ipsec_in_bytes,
                    "ipsec_out_bytes": ipsec_out_bytes,
                    "transport_rx_bytes": transport_rx_bytes,
                    "transport_tx_bytes": transport_tx_bytes,
                    "transport_source": transport_source,
                    "gre_rx_bytes": transport_rx_bytes,
                    "gre_tx_bytes": transport_tx_bytes,
                    "ipsec_node": ipsec_node,
                    "muxer_node": muxer_node,
                }
            )
        )

    up_count = sum(1 for item in summary.values() if item["tunnel_up"] == 1)
    total = len(summary)
    down_count = total - up_count

    metrics.append({"MetricName": "TunnelUpTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": up_count, "Unit": "Count"})
    metrics.append({"MetricName": "TunnelDownTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": down_count, "Unit": "Count"})
    metrics.append({"MetricName": "IpsecInBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_ipsec_in, "Unit": "Bytes"})
    metrics.append({"MetricName": "IpsecOutBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_ipsec_out, "Unit": "Bytes"})
    metrics.append({"MetricName": "TransportRxBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_transport_rx, "Unit": "Bytes"})
    metrics.append({"MetricName": "TransportTxBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_transport_tx, "Unit": "Bytes"})
    metrics.append({"MetricName": "GreRxBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_transport_rx, "Unit": "Bytes"})
    metrics.append({"MetricName": "GreTxBytesTotal", "Dimensions": [{"Name": "Muxer", "Value": muxer_name}], "Value": total_transport_tx, "Unit": "Bytes"})

    for hub_name, hub_in in hub_ipsec_in_total.items():
        metrics.append({"MetricName": "HubIpsecInBytesTotal", "Dimensions": [{"Name": "Hub", "Value": hub_name}], "Value": hub_in, "Unit": "Bytes"})
        metrics.append(
            {
                "MetricName": "HubIpsecOutBytesTotal",
                "Dimensions": [{"Name": "Hub", "Value": hub_name}],
                "Value": hub_ipsec_out_total.get(hub_name, 0),
                "Unit": "Bytes",
            }
        )

    for batch in _chunk(metrics, 20):
        cw.put_metric_data(Namespace=NAMESPACE, MetricData=batch)

    return {
        "namespace": NAMESPACE,
        "up": up_count,
        "total": total,
        "debug": {
            "muxer_resolve": muxer_resolve_dbg,
            "hub_resolve": hub_resolve_dbg,
            "ipsec": {hub_name: dbg for hub_name, (_, _, _, dbg) in ipsec_results.items()},
            "transport": transport_dbg,
        },
        "summary": summary,
    }
