# Customer DynamoDB SoT

Historical note:

- the current RPDB repo now prefers customer authoring under `muxer/config/customer-sources/`
- the deployable runtime prefers `customer_sot.backend=dynamodb`
- for isolated staging, the runtime can also load RPDB-native `customer-module.json`
  files from `config/customer-modules/`
- references below to `customers.variables.yaml` describe the older MUXER3-era flow
  that remains only as explicit legacy compatibility

This repo now supports a two-step customer source-of-truth model:

1. Author or update customers in [`config/customers.variables.yaml`](../config/customers.variables.yaml)
2. Sync those customers into DynamoDB as the canonical rendered customer module set

After sync, the renderers and runtime can load customer data from DynamoDB instead of reading only the variables file.

## Why this exists

We need one place to store the canonical customer record so that:

- customer creation is repeatable
- customer metadata is available to every node
- renderers can build muxer, GRE, iptables, routing, and IPsec files from one shared record
- every customer has a modular folder layout on disk

## DynamoDB table shape

Configured in [`config/muxer.yaml`](../config/muxer.yaml):

```yaml
customer_sot:
  backend: dynamodb
  sync_from_variables_on_render: true
  dynamodb:
    region: us-east-1
    table_name: muxingplus-customer-sot
```

Each item stores:

- `customer_name`: partition key
- `customer_id`
- `customer_class`
- `peer_ip`
- `fwmark`
- `route_table`
- `backend_underlay_ip`
- `source_ref`
- `updated_at`
- `customer_json`

`customer_json` is the full merged customer module. That is the record the renderers read back when `customer_sot.backend=dynamodb`.

## Authoring workflow

### 1. Bootstrap the table

```bash
python3 scripts/bootstrap_customer_sot_table.py
```

### 2. Author or update the variables file

Edit:

- [`config/customers.variables.yaml`](../config/customers.variables.yaml)

### 3. Sync customers into DynamoDB

```bash
python3 scripts/sync_customers_to_dynamodb.py --create-table
```

### 4. Render artifacts from the configured SoT

```bash
python3 scripts/render_customer_variables.py --prune
```

Because `customer_sot.backend=dynamodb` and `sync_from_variables_on_render=true`, the renderer will:

1. rebuild the merged customer modules from `customers.variables.yaml`
2. sync them into DynamoDB
3. reload the canonical modules from DynamoDB
4. render the flat and per-customer outputs

## Explicit render modes

Render from variables only:

```bash
python3 scripts/render_customer_variables.py --source variables --prune
```

Render from variables and also sync DynamoDB:

```bash
python3 scripts/render_customer_variables.py --source variables --sync-dynamodb --create-table --prune
```

Render from DynamoDB only:

```bash
python3 scripts/render_customer_variables.py --source dynamodb --prune
```

Render head-end bundle from DynamoDB:

```bash
python3 scripts/render_headend_customer_bundle.py --source dynamodb --cluster nat --local-underlay-ip 172.31.40.211 --remote-underlay-ip 172.31.42.35 --output-dir build/nat-bundle
```

## Per-customer folders

The renderer now writes a modular folder per customer under:

- [`config/customers`](../config/customers)

Each customer gets:

- `customer.yaml`
- `muxer/tunnel.yaml`
- `muxer/iptables.yaml`
- `muxer/routing.yaml`
- `vpn/ipsec.env`
- `vpn/ipsec.meta.yaml`

This gives each customer its own files for:

- IPsec
- iptables/protocol policy
- GRE/tunnel metadata
- routing/fwmark metadata

## Operational notes

- Strict non-NAT customers are still validated against the public-edge compatibility rules before sync or render.
- DynamoDB is the canonical rendered SoT, but `customers.variables.yaml` remains the authoring input.
- If render behavior deviates from this flow, document it immediately in the deployment/deviation logs before treating the new behavior as valid.

## Validation checkpoint - 2026-03-12

The implementation was verified against the live AWS account in `us-east-1`:

- DynamoDB table created: `muxingplus-customer-sot`
- Current customer count synced: `17`
- `render_customer_variables.py` verified from:
  - `--source variables`
  - `--source dynamodb`
- `render_headend_customer_bundle.py` verified from:
  - `--source dynamodb`

The verified customer-folder outputs include:

- `config/customers/<customer>/customer.yaml`
- `config/customers/<customer>/muxer/tunnel.yaml`
- `config/customers/<customer>/muxer/iptables.yaml`
- `config/customers/<customer>/muxer/routing.yaml`
- `config/customers/<customer>/vpn/ipsec.env`
- `config/customers/<customer>/vpn/ipsec.meta.yaml`
