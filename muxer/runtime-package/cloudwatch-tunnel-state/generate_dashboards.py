import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

TOPOLOGY_PATH = Path(os.path.dirname(__file__)) / "monitoring_topology.json"


def load_topology(path: Optional[str] = None) -> dict:
    topology_path = Path(path) if path else TOPOLOGY_PATH
    with topology_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def metric_row(namespace: str, metric_name: str, customer: str, hub: str, muxer: Optional[str], stat: str = "Average", period: int = 60) -> list:
    row = [namespace, metric_name, "Customer", customer, "Hub", hub]
    if muxer:
        row.extend(["Muxer", muxer])
    row.append({"stat": stat, "period": period})
    return row


def throughput_rows(namespace: str, metric_name: str, entities: List[dict], dimensions: List[str], label_key: str, id_prefix: str) -> List[list]:
    rows: List[list] = []
    for idx, entity in enumerate(entities, start=1):
        metric_id = f"{id_prefix}{idx}"
        expr_id = f"{id_prefix}e{idx}"
        dims = [namespace, metric_name]
        for dim in dimensions:
            dims.extend([dim, entity[dim]])
        dims.append({"id": metric_id, "visible": False, "stat": "Maximum", "period": 60})
        rows.append(dims)
        rows.append([{"expression": f"RATE({metric_id})*8/1000000", "label": entity[label_key], "id": expr_id}])
    return rows


def unique_transport_entities(customers: List[dict]) -> List[dict]:
    unique = {}
    for customer in customers:
        key = (customer["hub"], customer["muxer"], customer["transport_interface"])
        unique[key] = {
            "Hub": customer["hub"],
            "Muxer": customer["muxer"],
            "TransportInterface": customer["transport_interface"],
            "label": f'{customer["hub"]}:{customer["transport_interface"]}',
        }
    return list(unique.values())


def build_overview_dashboard(namespace: str, region: str, customers: List[dict], dashboard_prefix: str) -> Dict:
    total_expected = len(customers)
    muxer_name = customers[0]["muxer"]
    hub_names = sorted({customer["hub"] for customer in customers})
    tunnel_rows = [metric_row(namespace, "TunnelUp", c["customer"], c["hub"], c["muxer"]) for c in customers]
    ipsec_rows = [metric_row(namespace, "IpsecUp", c["customer"], c["hub"], None) for c in customers]
    transport_rows = [metric_row(namespace, "TransportUp", c["customer"], c["hub"], c["muxer"]) for c in customers]

    return {
        "widgets": [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 2,
                "properties": {
                    "markdown": (
                        "## VPN Monitoring Dashboards\n"
                        f"- `{dashboard_prefix}-Constant-State` (overview)\n"
                        + "\n".join(f"- `{dashboard_prefix}-Hub-{hub_name}`" for hub_name in hub_names)
                        + f"\n- `{dashboard_prefix}-Muxer-{muxer_name}`"
                    )
                },
            },
            {
                "type": "log",
                "x": 0,
                "y": 2,
                "width": 24,
                "height": 8,
                "properties": {
                    "title": "Customer | Public IP | Transport path | Transport type | IPsec mode | VPN Hub | IPsec Node | Muxer Node | Tunnel status",
                    "query": (
                        "SOURCE '/aws/lambda/vpn-tunnel-state-publisher'\n"
                        "| fields @timestamp, @message\n"
                        "| filter @message like /\"type\": \"customer_state\"/\n"
                        "| parse @message /\"customer\": \"(?<Customer>[^\"]+)\"/\n"
                        "| parse @message /\"public_ip\": \"(?<ParsedPublicIP>[^\"]*)\"/\n"
                        "| parse @message /\"transport_both_ends\": \"(?<ParsedTransportPath>[^\"]+)\"/\n"
                        "| parse @message /\"transport_type\": \"(?<ParsedTransportType>[^\"]+)\"/\n"
                        "| parse @message /\"ipsec_mode\": \"(?<ParsedIPsecMode>[^\"]+)\"/\n"
                        "| parse @message /\"vpn_hub\": \"(?<ParsedVPNHub>[^\"]+)\"/\n"
                        "| parse @message /\"ipsec_node\": \"(?<ParsedIPsecNode>[^\"]*)\"/\n"
                        "| parse @message /\"muxer_node\": \"(?<ParsedMuxerNode>[^\"]*)\"/\n"
                        "| parse @message /\"tunnel_status\": \"(?<ParsedTunnelStatus>[^\"]+)\"/\n"
                        "| stats latest(@timestamp) as LastSeen, latest(ParsedPublicIP) as PublicIP, latest(ParsedTransportPath) as TransportPath, latest(ParsedTransportType) as TransportType, latest(ParsedIPsecMode) as IPsecMode, latest(ParsedVPNHub) as VPNHub, latest(ParsedIPsecNode) as IPsecNode, latest(ParsedMuxerNode) as MuxerNode, latest(ParsedTunnelStatus) as TunnelStatus by Customer\n"
                        "| sort Customer asc"
                    ),
                    "region": region,
                    "view": "table",
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 10,
                "width": 8,
                "height": 6,
                "properties": {
                    "title": f"TunnelUpTotal (Expected {total_expected})",
                    "view": "singleValue",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": [[namespace, "TunnelUpTotal", "Muxer", muxer_name]],
                    "sparkline": True,
                    "trend": True,
                    "yAxis": {"left": {"min": 0, "max": total_expected}},
                },
            },
            {
                "type": "metric",
                "x": 8,
                "y": 10,
                "width": 8,
                "height": 6,
                "properties": {
                    "title": "TunnelDownTotal (Expected 0)",
                    "view": "singleValue",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": [[namespace, "TunnelDownTotal", "Muxer", muxer_name]],
                    "sparkline": True,
                    "trend": True,
                },
            },
            {
                "type": "metric",
                "x": 16,
                "y": 10,
                "width": 8,
                "height": 6,
                "properties": {
                    "title": "Aggregate Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": [
                        [namespace, "IpsecInBytesTotal", "Muxer", muxer_name, {"id": "m1", "visible": False, "stat": "Maximum"}],
                        [namespace, "IpsecOutBytesTotal", "Muxer", muxer_name, {"id": "m2", "visible": False, "stat": "Maximum"}],
                        [namespace, "TransportRxBytesTotal", "Muxer", muxer_name, {"id": "m3", "visible": False, "stat": "Maximum"}],
                        [namespace, "TransportTxBytesTotal", "Muxer", muxer_name, {"id": "m4", "visible": False, "stat": "Maximum"}],
                        [{"expression": "RATE(m1)*8/1000000", "label": "IPsec In Mbps", "id": "e1"}],
                        [{"expression": "RATE(m2)*8/1000000", "label": "IPsec Out Mbps", "id": "e2"}],
                        [{"expression": "RATE(m3)*8/1000000", "label": "Transport Rx Mbps", "id": "e3"}],
                        [{"expression": "RATE(m4)*8/1000000", "label": "Transport Tx Mbps", "id": "e4"}],
                    ],
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 16,
                "width": 24,
                "height": 8,
                "properties": {
                    "title": "TunnelUp by Customer",
                    "view": "timeSeries",
                    "stacked": False,
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": tunnel_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 24,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": "IpsecUp by Customer",
                    "view": "timeSeries",
                    "stacked": False,
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": ipsec_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 24,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": "TransportUp by Customer",
                    "view": "timeSeries",
                    "stacked": False,
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": transport_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
        ]
    }


def build_hub_dashboard(namespace: str, region: str, hub_name: str, customers: List[dict]) -> Dict:
    hub_customers = [c for c in customers if c["hub"] == hub_name]
    ipsec_up_rows = [metric_row(namespace, "IpsecUp", c["customer"], c["hub"], None) for c in hub_customers]
    tunnel_rows = [metric_row(namespace, "TunnelUp", c["customer"], c["hub"], c["muxer"]) for c in hub_customers]
    transport_up_rows = [metric_row(namespace, "TransportUp", c["customer"], c["hub"], c["muxer"]) for c in hub_customers]
    ipsec_entities = [{"Customer": c["customer"], "Hub": c["hub"], "label": c["customer"]} for c in hub_customers]
    ipsec_in_rate_rows = throughput_rows(namespace, "IpsecInBytes", ipsec_entities, ["Customer", "Hub"], "label", "hi")
    ipsec_out_rate_rows = throughput_rows(namespace, "IpsecOutBytes", ipsec_entities, ["Customer", "Hub"], "label", "ho")
    transport_entities = unique_transport_entities(hub_customers)
    transport_rx_rate_rows = throughput_rows(namespace, "TransportRxBytes", transport_entities, ["Hub", "Muxer", "TransportInterface"], "label", "hr")
    transport_tx_rate_rows = throughput_rows(namespace, "TransportTxBytes", transport_entities, ["Hub", "Muxer", "TransportInterface"], "label", "ht")

    return {
        "widgets": [
            {
                "type": "log",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 7,
                "properties": {
                    "title": f"{hub_name} | Customer Status + Active Nodes",
                    "query": (
                        "SOURCE '/aws/lambda/vpn-tunnel-state-publisher'\n"
                        "| fields @timestamp, @message\n"
                        "| filter @message like /\"type\": \"customer_state\"/\n"
                        f"| filter @message like /\"vpn_hub\": \"{hub_name}\"/\n"
                        "| parse @message /\"customer\": \"(?<Customer>[^\"]+)\"/\n"
                        "| parse @message /\"public_ip\": \"(?<ParsedPublicIP>[^\"]*)\"/\n"
                        "| parse @message /\"ipsec_node\": \"(?<ParsedIPsecNode>[^\"]*)\"/\n"
                        "| parse @message /\"muxer_node\": \"(?<ParsedMuxerNode>[^\"]*)\"/\n"
                        "| parse @message /\"transport_type\": \"(?<ParsedTransportType>[^\"]+)\"/\n"
                        "| parse @message /\"tunnel_status\": \"(?<ParsedTunnelStatus>[^\"]+)\"/\n"
                        "| stats latest(@timestamp) as LastSeen, latest(ParsedPublicIP) as PublicIP, latest(ParsedIPsecNode) as IPsecNode, latest(ParsedMuxerNode) as MuxerNode, latest(ParsedTransportType) as TransportType, latest(ParsedTunnelStatus) as TunnelStatus by Customer\n"
                        "| sort Customer asc"
                    ),
                    "region": region,
                    "view": "table",
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 7,
                "width": 12,
                "height": 6,
                "properties": {
                    "title": f"{hub_name} | IPsecUp",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": ipsec_up_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 7,
                "width": 12,
                "height": 6,
                "properties": {
                    "title": f"{hub_name} | TunnelUp",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": tunnel_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 13,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{hub_name} | IPsec In Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": ipsec_in_rate_rows,
                    "legend": {"position": "right"},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 13,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{hub_name} | IPsec Out Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": ipsec_out_rate_rows,
                    "legend": {"position": "right"},
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 21,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{hub_name} | TransportUp",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": transport_up_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 21,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{hub_name} | Transport Rx Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": transport_rx_rate_rows,
                    "legend": {"position": "right"},
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 29,
                "width": 24,
                "height": 8,
                "properties": {
                    "title": f"{hub_name} | Transport Tx Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": transport_tx_rate_rows,
                    "legend": {"position": "right"},
                },
            },
        ]
    }


def build_muxer_dashboard(namespace: str, region: str, muxer_name: str, customers: List[dict]) -> Dict:
    mux_customers = [c for c in customers if c["muxer"] == muxer_name]
    transport_up_rows = [metric_row(namespace, "TransportUp", c["customer"], c["hub"], c["muxer"]) for c in mux_customers]
    tunnel_rows = [metric_row(namespace, "TunnelUp", c["customer"], c["hub"], c["muxer"]) for c in mux_customers]
    transport_entities = unique_transport_entities(mux_customers)
    transport_rx_rate_rows = throughput_rows(namespace, "TransportRxBytes", transport_entities, ["Hub", "Muxer", "TransportInterface"], "label", "mr")
    transport_tx_rate_rows = throughput_rows(namespace, "TransportTxBytes", transport_entities, ["Hub", "Muxer", "TransportInterface"], "label", "mt")

    return {
        "widgets": [
            {
                "type": "log",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 7,
                "properties": {
                    "title": f"{muxer_name} | Customer Tunnel Status + Active Nodes",
                    "query": (
                        "SOURCE '/aws/lambda/vpn-tunnel-state-publisher'\n"
                        "| fields @timestamp, @message\n"
                        "| filter @message like /\"type\": \"customer_state\"/\n"
                        "| parse @message /\"customer\": \"(?<Customer>[^\"]+)\"/\n"
                        "| parse @message /\"vpn_hub\": \"(?<ParsedVPNHub>[^\"]+)\"/\n"
                        "| parse @message /\"ipsec_node\": \"(?<ParsedIPsecNode>[^\"]*)\"/\n"
                        "| parse @message /\"muxer_node\": \"(?<ParsedMuxerNode>[^\"]*)\"/\n"
                        "| parse @message /\"tunnel_status\": \"(?<ParsedTunnelStatus>[^\"]+)\"/\n"
                        f"| filter ParsedMuxerNode like /{muxer_name}/\n"
                        "| stats latest(@timestamp) as LastSeen, latest(ParsedVPNHub) as VPNHub, latest(ParsedIPsecNode) as IPsecNode, latest(ParsedMuxerNode) as MuxerNode, latest(ParsedTunnelStatus) as TunnelStatus by Customer\n"
                        "| sort Customer asc"
                    ),
                    "region": region,
                    "view": "table",
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 7,
                "width": 12,
                "height": 6,
                "properties": {
                    "title": f"{muxer_name} | Transport Up",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": transport_up_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 7,
                "width": 12,
                "height": 6,
                "properties": {
                    "title": f"{muxer_name} | Tunnel Up",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "stat": "Average",
                    "metrics": tunnel_rows,
                    "legend": {"position": "right"},
                    "yAxis": {"left": {"min": 0, "max": 1}},
                },
            },
            {
                "type": "metric",
                "x": 0,
                "y": 13,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{muxer_name} | Transport Rx Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": transport_rx_rate_rows,
                    "legend": {"position": "right"},
                },
            },
            {
                "type": "metric",
                "x": 12,
                "y": 13,
                "width": 12,
                "height": 8,
                "properties": {
                    "title": f"{muxer_name} | Transport Tx Throughput (Mbps)",
                    "view": "timeSeries",
                    "region": region,
                    "period": 60,
                    "metrics": transport_tx_rate_rows,
                    "legend": {"position": "right"},
                },
            },
        ]
    }


def main():
    ap = argparse.ArgumentParser(description="Generate VPN tunnel CloudWatch dashboards.")
    ap.add_argument("--namespace", default="VPN/TunnelState")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--topology", default=str(TOPOLOGY_PATH))
    ap.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), "build"))
    ap.add_argument("--dashboard-prefix", default="VPN-Tunnel")
    args = ap.parse_args()

    topology = load_topology(args.topology)
    muxer_name = topology["muxer"]["name"]
    customers = []
    for customer in topology["customers"]:
        item = dict(customer)
        item["muxer"] = muxer_name
        customers.append(item)

    os.makedirs(args.output_dir, exist_ok=True)
    artifacts = {
        "dashboard-vpn-tunnel-overview.json": build_overview_dashboard(args.namespace, args.region, customers, args.dashboard_prefix),
        f"dashboard-vpn-muxer-{muxer_name}.json": build_muxer_dashboard(args.namespace, args.region, muxer_name, customers),
    }
    for hub in topology["hubs"]:
        artifacts[f'dashboard-vpn-hub-{hub["name"]}.json'] = build_hub_dashboard(args.namespace, args.region, hub["name"], customers)

    for name, body in artifacts.items():
        path = os.path.join(args.output_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(body, fh, separators=(",", ":"), ensure_ascii=True)
        print(path)


if __name__ == "__main__":
    main()
