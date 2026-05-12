# RPDB Customer Demo Lifecycle

This runbook is the repeatable entrypoint for the current live demo set:

- `customer2-local-psk`
  Customer 2 local-PSK validation plus normal non-NAT-first/NAT-T promotion.
- `customer4-certificate`
  Customer 4 certificate-auth validation using generated demo-CA material.
- `customer5-inside-nat-explicit-map`
  Customer 5 inside-NAT validation using explicit host mappings.
- `cgnat-provided-per-customer-outer`
  CGNAT where the customer owns the outer certificate tunnel.
- `cgnat-provided-shared-isp-gateway`
  CGNAT where `isp-cgnat-router-2` owns the shared outer certificate tunnel.

Run this from the MOM/jump-host checkout:

```bash
cd /home/ec2-user/rpdb
```

## Prepare Demo Inputs

The local-PSK and generated-certificate requests are intentionally not checked
into Git. Generate them on the jump host:

```bash
python3 scripts/customers/prepare_live_validation_requests.py
```

This writes:

```text
build/live-validation/rpdb-empty-live-local-psk.yaml
build/live-validation/requests/live-validation-manifest.json
build/live-validation/requests/vpn-customer-stage1-15-cust-0002-local-psk.yaml
build/live-validation/requests/vpn-customer-stage1-15-cust-0004-certificate.yaml
build/live-validation/requests/vpn-customer-stage1-15-cust-0005-explicit-inside-nat.yaml
build/live-validation/requests/demo-ca-cgnat-customer-router.yaml
build/live-validation/requests/demo-ca-cgnat-shared-gateway.yaml
```

If Customer 2 has a new public IP, pass it when preparing:

```bash
python3 scripts/customers/prepare_live_validation_requests.py \
  --customer2-peer-ip <current-customer2-public-ip>
```

The generated environment copy only changes one thing:

```yaml
secrets:
  allow_local_psk: true
```

Use that generated environment file for local-PSK or CGNAT-provided-cert demo
runs because those generated requests intentionally keep lab secrets local to
the jump host.

## Demo Wrapper

The wrapper lives at:

```text
scripts/customers/demo_customer_lifecycle.py
```

List profiles:

```bash
python3 scripts/customers/demo_customer_lifecycle.py list-profiles
```

Show the exact resolved commands for one profile:

```bash
python3 scripts/customers/demo_customer_lifecycle.py show customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml
```

Show the current live state for one profile:

```bash
python3 scripts/customers/demo_customer_lifecycle.py state customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml
```

Verify the customer is clean after removal:

```bash
python3 scripts/customers/demo_customer_lifecycle.py verify-clean customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml
```

Plan provisioning:

```bash
python3 scripts/customers/demo_customer_lifecycle.py plan-provision customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml \
  --json
```

Approve live provisioning:

```bash
python3 scripts/customers/demo_customer_lifecycle.py provision customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml \
  --json
```

Verify the deployed state:

```bash
python3 scripts/customers/demo_customer_lifecycle.py verify-deployed customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml
```

Re-apply the same customer:

```bash
python3 scripts/customers/demo_customer_lifecycle.py reapply customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml \
  --json
```

Approve live removal:

```bash
python3 scripts/customers/demo_customer_lifecycle.py remove customer2-local-psk \
  --environment build/live-validation/rpdb-empty-live-local-psk.yaml \
  --json
```

## Profile Matrix

Use these profile names directly with the wrapper:

| Profile | Source |
| --- | --- |
| `customer2-local-psk` | `build/live-validation/requests/vpn-customer-stage1-15-cust-0002-local-psk.yaml` |
| `customer4-certificate` | `build/live-validation/requests/vpn-customer-stage1-15-cust-0004-certificate.yaml` |
| `customer5-inside-nat-explicit-map` | `build/live-validation/requests/vpn-customer-stage1-15-cust-0005-explicit-inside-nat.yaml` |
| `cgnat-provided-per-customer-outer` | `build/live-validation/requests/demo-ca-cgnat-customer-router.yaml` |
| `cgnat-provided-shared-isp-gateway` | `build/live-validation/requests/demo-ca-cgnat-shared-gateway.yaml` |

Legacy dry-run examples remain available:

| Profile | Source |
| --- | --- |
| `customer4-non-nat` | `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml` |
| `customer7-nat-t` | `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0007.yaml` plus NAT-T observation |
| `cgnat-per-customer-outer` | `muxer/config/customer-requests/examples/example-minimal-cgnat-local-pki.yaml` |
| `cgnat-shared-isp-gateway` | `muxer/config/customer-requests/examples/example-minimal-cgnat-shared-isp-scenario2-local-pki.yaml` |

## Clean Demo Pattern

For each profile:

1. `remove` first, even if you believe the customer is already clean.
2. Run `verify-clean` to prove the muxer, both VPN head-end families,
   SmartConnectGateway3, and CGNAT surfaces when applicable are clean.
3. `provision` with the wrapper or the underlying `deploy_customer.py`.
4. Run `verify-deployed` to show the muxer, selected VPN head end,
   SmartConnectGateway3 routes, and CGNAT surfaces when applicable.
5. Verify the generated `execution-plan.json` says the live apply completed.
6. Verify the use-case behavior before moving to the next profile.

The state verifier is read-only:

```text
scripts/customers/show_customer_live_state.py
```

It checks:

| Surface | Clean proof | Deployed proof |
| --- | --- | --- |
| SoT | No customer item and no allocation rows. | Customer item and allocation rows exist. |
| Muxer | No customer root, module, or nft table. | Customer root/module, fwmark rule, route table, and nft table are present. |
| VPN head end | No customer root, swanctl file, or NAT nft tables. | Customer root, swanctl file, connection, and NAT nft tables when enabled. |
| SmartConnectGateway3 | No customer root and no expected route CIDRs. | Customer root and expected route CIDRs are installed. |
| CGNAT | No CGNAT root or handoff/config files. | CGNAT root and handoff/config files are present. |

For SmartConnectGateway3, the verifier follows the platform route rule:
`post_ipsec_nat.translated_subnets` when inside NAT is enabled, otherwise
`selectors.remote_host_cidrs`. It does not validate `remote_subnets` as a
SmartConnect route source because those can overlap across customers.

Notes:

- `reapply` intentionally runs the approved deploy path again against the same
  source inputs. That is the demo-safe way to show idempotent re-application.
- `remove_customer.py` now defaults to sweeping stale NAT and non-NAT head-end
  placements when the SoT-resolved family is `nat` or `non_nat`.
- Do not commit files under `build/live-validation`; those can contain local
  PSKs or private-key file references.
