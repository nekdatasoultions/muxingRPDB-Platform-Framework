# Old Solution Scale Test 50-Customer Onboarding

## Goal

Use the existing MUXER3-based workflow to stage and apply the 50 `scale-*`
customers that are already present in the production customer source-of-truth
table.

## Current DynamoDB State

As verified on April 14, 2026:

- table: `muxingplus-customer-sot`
- region: `us-east-1`
- total records: `68`
- `scale-*` records: `50`

Important note:

- the old MUXER3 workflow is still fleet-oriented
- if you render and apply from DynamoDB, you are operating against the full
  table, not only the 50 new records
- that means the existing `18` non-scale customers remain part of the rendered
  state unless you deliberately isolate the process some other way

## Preconditions

1. AWS credentials are active on the jump host.
2. The old workflow repo is available on the jump host:
   - `~/code1/MUXER3`
3. The active muxer and head-end pairs are healthy.
4. You are comfortable with the fact that the old muxer render/apply path is
   not truly customer-scoped.

## Step 1 - Verify the 50 scale-test customers exist

Run on the jump host:

```bash
aws dynamodb scan \
  --table-name muxingplus-customer-sot \
  --region us-east-1 \
  --projection-expression customer_name,customer_id,updated_at
```

Expected result:

- `68` total rows
- `50` rows named `scale-*`

## Step 2 - Render muxer customer artifacts from DynamoDB

Run on the jump host:

```bash
cd ~/code1/MUXER3
python3 scripts/render_customer_variables.py --source dynamodb --prune
```

What this does:

- renders `config/tunnels.d/*.yaml`
- renders `config/customers/<customer>/...`
- rebuilds muxer routing, iptables, and VPN metadata from the active DynamoDB
  table

Important note:

- this is a full-table render
- today that means `68` customers, not only the 50 scale-test customers

## Step 3 - Apply the rendered state on the muxer

Run on the muxer:

```bash
sudo /etc/muxer/src/muxctl.py apply
```

Then validate:

```bash
sudo /etc/muxer/src/muxctl.py show
sudo ip rule
sudo ip route show table all
sudo iptables-save
```

Confirm:

- customer GRE interfaces exist
- customer `fwmark` rules exist
- customer route tables exist
- customer iptables steering rules exist

## Step 4 - Render the NAT head-end bundle

Run on the jump host:

```bash
cd ~/code1/MUXER3
python3 scripts/render_headend_customer_bundle.py \
  --source dynamodb \
  --cluster nat \
  --local-underlay-ip <nat-headend-a-primary-ip> \
  --remote-underlay-ip <muxer-transport-ip> \
  --public-ip 54.204.221.89 \
  --output-dir build/nat-bundle
```

How this works:

- the script loads customers from DynamoDB
- then filters to customers with `udp4500=true`
- the resulting bundle contains all NAT customers in the table for that cluster

## Step 5 - Render the non-NAT head-end bundle

Run on the jump host:

```bash
cd ~/code1/MUXER3
python3 scripts/render_headend_customer_bundle.py \
  --source dynamodb \
  --cluster non-nat \
  --local-underlay-ip <nonnat-headend-a-primary-ip> \
  --remote-underlay-ip <muxer-transport-ip> \
  --public-ip 54.204.221.89 \
  --output-dir build/nonnat-bundle
```

How this works:

- the script loads customers from DynamoDB
- then filters to customers with `udp4500=false`
- the resulting bundle contains all non-NAT customers in the table for that
  cluster

## Step 6 - Stage the bundles onto the shared EFS paths

Copy the rendered bundles to:

- `/Shared/nat/customer-bundles/<bundle-name>`
- `/Shared/non-nat/customer-bundles/<bundle-name>`

## Step 7 - Install the bundles on the active and standby head ends

On the NAT pair:

```bash
cd /Shared/nat/customer-bundles/<bundle-name>
sudo bash ./install-on-headend.sh
sudo bash ./validate-on-headend.sh
```

On the non-NAT pair:

```bash
cd /Shared/non-nat/customer-bundles/<bundle-name>
sudo bash ./install-on-headend.sh
sudo bash ./validate-on-headend.sh
```

## Step 8 - Validate IPsec and dataplane state

On the active head ends:

```bash
sudo ipsec auto --rereadsecrets || sudo ipsec whack --rereadsecrets
sudo ipsec auto --status
sudo ip xfrm state
sudo ip xfrm policy
```

On the muxer:

```bash
sudo /etc/muxer/src/muxctl.py show
```

## Step 9 - Recommended operational pause

Before treating the 50 as fully onboarded, confirm:

1. The rendered muxer state count matches expectation.
2. The NAT and non-NAT bundle membership matches expectation.
3. No unexpected existing customer drift was introduced by the full-table
   render/apply path.

## Optional inventory command

If you want a quick local list of the current `scale-*` customers:

```bash
aws dynamodb scan \
  --table-name muxingplus-customer-sot \
  --region us-east-1 \
  --projection-expression customer_name,customer_id,updated_at \
  --output json > /tmp/muxingplus-customer-sot.json

python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path('/tmp/muxingplus-customer-sot.json').read_text())
items = []
for item in data.get('Items', []):
    name = item.get('customer_name', {}).get('S', '')
    if not name.startswith('scale-'):
        continue
    items.append((
        int(item.get('customer_id', {}).get('N', '0')),
        name,
        item.get('updated_at', {}).get('S', ''),
    ))

for cid, name, updated_at in sorted(items):
    print(f"{cid}\t{name}\t{updated_at}")
PY
```

## References

- `~/code1/MUXER3/scripts/render_customer_variables.py`
- `~/code1/MUXER3/scripts/render_headend_customer_bundle.py`
- `/etc/muxer/src/muxctl.py`
