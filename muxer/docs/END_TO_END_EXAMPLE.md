# End-to-End Example

## Goal

This example shows the full RPDB customer flow for one customer:

1. author the source file
2. merge defaults and class overrides into the resolved customer module
3. build the DynamoDB item that stores the canonical runtime record
4. export the framework-side handoff directory used by deployment tooling

The example below uses:

- [example-nat-0001/customer.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/customer-sources/examples/example-nat-0001/customer.yaml)

## 1. Source File

This is the small authoring record that lives in Git.

```yaml
schema_version: 1

customer:
  id: 101
  name: example-nat-0001
  customer_class: nat

  peer:
    public_ip: 198.51.100.10
    remote_id: 198.51.100.10
    psk_secret_ref: /muxingrpdb/example/example-nat-0001/psk

  transport:
    mark: 0x41001
    table: 41001
    tunnel_key: 41001
    interface: gre-example-0001
    overlay:
      mux_ip: 169.254.101.1/30
      router_ip: 169.254.101.2/30

  selectors:
    local_subnets:
      - 172.30.10.0/27
    remote_subnets:
      - 10.200.1.0/24

  backend:
    role: nat-active

  post_ipsec_nat:
    enabled: true
    mode: netmap
    translated_subnets:
      - 172.30.10.0/27
```

## 2. Validate And Build

Validate the source:

```powershell
python muxer\scripts\validate_customer_source.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml `
  --show-merged
```

Build the merged module and DynamoDB item:

```powershell
python muxer\scripts\build_customer_item.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml
```

Render customer-scoped muxer and head-end artifacts:

```powershell
python muxer\scripts\render_customer_artifacts.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml `
  --out-dir build\render-example-nat-0001
python muxer\scripts\validate_rendered_artifacts.py `
  build\render-example-nat-0001
python muxer\scripts\validate_environment_bindings.py `
  muxer\config\environment-defaults\example-environment.yaml
python muxer\scripts\bind_rendered_artifacts.py `
  build\render-example-nat-0001 `
  --environment-file muxer\config\environment-defaults\example-environment.yaml `
  --out-dir build\bound-render-example-nat-0001
python muxer\scripts\validate_bound_artifacts.py `
  build\bound-render-example-nat-0001
```

Export the deployment handoff directory:

```powershell
python muxer\scripts\export_customer_handoff.py `
  muxer\config\customer-sources\examples\example-nat-0001\customer.yaml `
  --export-dir build\example-nat-0001
```

## 3. Merged Customer Module

After layering:

1. `customer-defaults/defaults.yaml`
2. `customer-defaults/classes/nat.yaml`
3. the customer source file

the resolved module looks like this:

```json
{
  "backend": {
    "role": "nat-active"
  },
  "customer": {
    "customer_class": "nat",
    "id": 101,
    "name": "example-nat-0001"
  },
  "ipsec": {
    "auto": "start",
    "dpdaction": "restart",
    "dpddelay": "10s",
    "dpdtimeout": "120s"
  },
  "metadata": {
    "class_name": "nat",
    "source_ref": "E:/Code1/muxingRPDB Platform Framework/muxer/config/customer-sources/examples/example-nat-0001/customer.yaml"
  },
  "natd_rewrite": {
    "enabled": false,
    "initiator_inner_ip": ""
  },
  "peer": {
    "psk_secret_ref": "/muxingrpdb/example/example-nat-0001/psk",
    "public_ip": "198.51.100.10",
    "remote_id": "198.51.100.10"
  },
  "post_ipsec_nat": {
    "enabled": true,
    "mode": "netmap",
    "translated_subnets": [
      "172.30.10.0/27"
    ]
  },
  "protocols": {
    "esp50": true,
    "force_rewrite_4500_to_500": false,
    "udp4500": true,
    "udp500": true
  },
  "schema_version": 1,
  "selectors": {
    "local_subnets": [
      "172.30.10.0/27"
    ],
    "remote_subnets": [
      "10.200.1.0/24"
    ]
  },
  "transport": {
    "interface": "gre-example-0001",
    "mark": "0x41001",
    "overlay": {
      "mux_ip": "169.254.101.1/30",
      "router_ip": "169.254.101.2/30"
    },
    "rpdb_priority": 1101,
    "table": 41001,
    "tunnel_key": 41001,
    "tunnel_ttl": 64,
    "tunnel_type": "gre"
  }
}
```

Important details:

- `transport.rpdb_priority` was resolved automatically to `1101`
- the source file kept only a secret reference, not an inline PSK
- shared defaults contributed protocol and IPsec fields that were not repeated
  in the source file

## 4. DynamoDB Item

The DynamoDB item stores a few routing fields at the top level for quick
inspection and keeps the full merged module in `customer_json`.

```json
{
  "backend_role": "nat-active",
  "backend_underlay_ip": null,
  "customer_class": "nat",
  "customer_id": 101,
  "customer_name": "example-nat-0001",
  "fwmark": "0x41001",
  "peer_ip": "198.51.100.10",
  "route_table": 41001,
  "rpdb_priority": 1101,
  "schema_version": 1,
  "source_ref": "E:/Code1/muxingRPDB Platform Framework/muxer/config/customer-sources/examples/example-nat-0001/customer.yaml",
  "updated_at": "2026-04-13T21:32:26Z",
  "customer_json": "{...merged customer module...}"
}
```

Important details:

- `fwmark`, `route_table`, and `rpdb_priority` stay queryable without parsing
  `customer_json`
- `customer_json` remains the canonical merged customer record
- secret values are still not stored in the source file; only the secret
  reference path is carried through

## 5. Handoff Export

The framework-side handoff export should look like:

```text
build/example-nat-0001/
  export-metadata.json
  customer-module.json
  customer-ddb-item.json
  customer-source.yaml
  muxer/
    customer/
      customer-summary.json
    routing/
      rpdb-routing.json
      ip-rule.command.txt
      ip-route-default.command.txt
    tunnel/
      tunnel-intent.json
      ip-link.command.txt
    firewall/
      firewall-intent.json
      iptables-snippet.txt
  headend/
    ipsec/
      ipsec-intent.json
      swanctl-connection.conf
    routing/
      routing-intent.json
      ip-route.commands.txt
    post-ipsec-nat/
      post-ipsec-nat-intent.json
      iptables-snippet.txt
```

The deployment branch should consume this handoff directory instead of trying
to rebuild the merged module from the source YAML itself.

## 6. Why This Matters

This example shows the target operator flow:

1. edit one customer file
2. validate one customer
3. build one merged module
4. sync one DynamoDB item
5. export one customer handoff directory
6. package and apply one customer

That keeps the control plane customer-scoped by default instead of rebuilding
the whole fleet for ordinary work.
