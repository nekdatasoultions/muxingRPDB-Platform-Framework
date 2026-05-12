# Demo CA Server

## Purpose

The demo CA server is a lab-only certificate issuer used to mimic a third-party
certificate authority during RPDB certificate-auth testing. It gives us a
repeatable way to prove that the customer provisioning flow can consume
provided certificate material instead of PSKs.

This is not a production CA. It writes private keys, certificates, CSRs, and
passphrase files into a local artifact directory so the provisioning code can
exercise the same material-reference path used by live certificate customers.

## What It Proves

The helper can issue both supported regular VPN certificate-auth scenarios:

- `third_party_provided`: a third-party source gives RPDB the head-end cert,
  head-end private key, remote/customer trust, and optional customer handoff
  material.
- `customer_supplied`: the customer gives RPDB the per-customer head-end cert,
  head-end private key, and trust bundle that RPDB must install on the selected
  VPN head end.
- Optional encrypted head-end private keys are supported by generating a
  passphrase reference and rendering the strongSwan `secrets.private-*` block.
- CGNAT outer-tunnel certificate-auth can be tested with `pki.mode: provided`
  for both `per_customer_outer` and `shared_isp_gateway` topologies.

The generated customer request runs through `scripts/customers/deploy_customer.py`
and renders `swanctl` with `auth = pubkey`, no PSK secret block, and cert/key
material paths under `/etc/swanctl`.

For CGNAT, the generated request runs through the CGNAT review/provisioning
path and stages provided cert/key/trust material into the CGNAT head-end install
manifest plus the customer-router or ISP-gateway outer handoff package.

## Initialize A Lab CA

```powershell
python scripts/certificates/demo_ca_server.py init `
  --ca-root build/demo-ca
```

This creates the demo CA under:

```text
build/demo-ca/rpdb-demo-third-party-ca/ca/
```

The CA manifest is written beside the CA material and includes the CA cert ref
used by generated customer requests.

## Issue A Third-Party Provided Bundle

```powershell
python scripts/certificates/demo_ca_server.py issue-vpn-customer `
  --ca-root build/demo-ca `
  --customer-name demo-ca-third-party-cert `
  --profile third_party_provided `
  --encrypt-headend-key `
  --headend-key-passphrase demo-pass `
  --request-out build/demo-ca/demo-ca-third-party-cert.yaml
```

This produces:

- a head-end certificate and private key for RPDB to install on the VPN head end
- a CA trust bundle for validating the customer side
- a customer certificate and key for the handoff package
- a customer request YAML that selects `ipsec.auth.method: certificate`
- a passphrase file ref when the head-end key is encrypted

## Issue A Customer-Supplied Style Bundle

```powershell
python scripts/certificates/demo_ca_server.py issue-vpn-customer `
  --ca-root build/demo-ca `
  --customer-name demo-ca-customer-supplied-cert `
  --profile customer_supplied `
  --request-out build/demo-ca/demo-ca-customer-supplied-cert.yaml
```

In this mode, the generated request omits `customer_handoff` by default because
the customer owns the customer-side certificate material. RPDB only installs
the provided head-end cert/key and trust bundle.

## Dry-Run The Generated Request

```powershell
python scripts/customers/deploy_customer.py `
  --customer-file build/demo-ca/demo-ca-third-party-cert.yaml `
  --environment example-rpdb `
  --out-dir build/customer-deploy/demo-ca-third-party-cert `
  --json
```

Expected dry-run result:

```text
status: dry_run_ready
package.status: ready_for_review
dry_run_gate.status: dry_run_ready
```

The rendered package should include:

```text
build/customer-deploy/demo-ca-third-party-cert/package/rendered/headend/ipsec/swanctl-connection.conf
build/customer-deploy/demo-ca-third-party-cert/package/rendered/customer/certificate-auth/certificate-handoff.json
```

The `swanctl` file should show `auth = pubkey`. If the head-end key is
encrypted, it should also include a `private-<customer>-headend-key` secret
block with `secret = ${PRIVATE_KEY_PASSPHRASE}` in dry-run output.

## Issue A CGNAT Per-Customer Outer Bundle

```powershell
python scripts/certificates/demo_ca_server.py issue-cgnat-customer `
  --ca-root build/demo-ca `
  --customer-name demo-ca-cgnat-customer-router `
  --outer-topology per_customer_outer `
  --request-out build/demo-ca/demo-ca-cgnat-customer-router.yaml
```

Run the CGNAT review path:

```powershell
python CGNAT/framework/scripts/prepare_cgnat_customer_pilot.py `
  build/demo-ca/demo-ca-cgnat-customer-router.yaml `
  --environment rpdb-empty-live `
  --out-dir CGNAT/build/customer-provisioning/demo-ca-cgnat-customer-router `
  --json
```

Expected PKI review:

```text
mode: provided
ready_for_review: true
outer_handoff.recipient_type: customer_device
artifacts.provided_material: true
```

## Issue A CGNAT Shared-ISP Gateway Bundle

```powershell
python scripts/certificates/demo_ca_server.py issue-cgnat-customer `
  --ca-root build/demo-ca `
  --customer-name demo-ca-cgnat-shared-gateway `
  --outer-topology shared_isp_gateway `
  --outer-gateway-ref isp-cgnat-router-2 `
  --request-out build/demo-ca/demo-ca-cgnat-shared-gateway.yaml
```

Run the CGNAT review path:

```powershell
python CGNAT/framework/scripts/prepare_cgnat_customer_pilot.py `
  build/demo-ca/demo-ca-cgnat-shared-gateway.yaml `
  --environment rpdb-empty-live `
  --out-dir CGNAT/build/customer-provisioning/demo-ca-cgnat-shared-gateway `
  --json
```

Expected PKI review:

```text
mode: provided
ready_for_review: true
outer_handoff.recipient_type: isp_gateway
customer_handoff.outer_material_required: false
gateway_handoff.outer_material_required: true
```

## Run As A Local HTTP Issuer

```powershell
python scripts/certificates/demo_ca_server.py serve `
  --ca-root build/demo-ca `
  --host 127.0.0.1 `
  --port 8765
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Issue a bundle:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/v1/issue/vpn-customer `
  -ContentType application/json `
  -Body '{
    "customer_name": "demo-ca-http-cert",
    "profile": "third_party_provided",
    "encrypt_headend_key": true,
    "headend_key_passphrase": "demo-pass"
  }'
```

The HTTP API returns the same manifest shape as the CLI. This lets us mimic
calling an external certificate service without needing the real external
issuer in the lab.

CGNAT HTTP example:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/v1/issue/cgnat-customer `
  -ContentType application/json `
  -Body '{
    "customer_name": "demo-ca-cgnat-http",
    "outer_topology": "shared_isp_gateway",
    "outer_gateway_ref": "isp-cgnat-router-2"
  }'
```

## Live Apply Boundary

Generated `file://` references are intentionally local. For a live apply, the
referenced files must be readable from the provisioning host that runs
`deploy_customer.py --approve`.

For the jump-host/MoM model, use one of these approaches:

- Run the demo CA on the jump host so the generated `file://` refs are local to
  the jump host.
- Upload certs, keys, trust bundles, and optional passphrases into Secrets
  Manager, then replace the generated `file://` refs with the approved secret
  IDs.

For CGNAT customer requests, `scripts/customers/deploy_customer.py` now creates
the CGNAT deployment review under `CGNAT/build/customer-deploy/<customer>/` and
passes the generated `pki/` review into the CGNAT head-end apply/validate
scripts. That keeps CGNAT on the same dry-run, approved apply, and rollback path
as regular VPN customers.

Do not copy the demo CA private key into a production path. The helper is only
for proving provisioning behavior and demoing third-party certificate flows.

## Test Coverage

Focused validation:

```powershell
python -m unittest CGNAT.tests.test_demo_ca_server
```

Broader certificate-auth regression:

```powershell
python -m unittest `
  CGNAT.tests.test_customer_provisioning_integration `
  CGNAT.tests.test_customer_cgnat_artifacts `
  CGNAT.tests.test_live_apply_secret_seed `
  CGNAT.tests.test_cgnat_pki_materializer `
  CGNAT.tests.test_demo_ca_server
```
