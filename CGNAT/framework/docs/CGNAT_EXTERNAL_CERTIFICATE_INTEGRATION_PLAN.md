# CGNAT External Certificate Integration Plan

## Status

Paused. This is a working plan only. No implementation has been started from
this document yet.

## Goal

Move CGNAT outer-tunnel certificate handling from demo/local PKI generation to
a production-ready model where RPDB can consume externally provided certificate
material and install it on the CGNAT head ends.

The platform should not care who issued the certificate. It should care that
the certificate material is valid, trusted, matches the modeled CGNAT identity,
and can be loaded by the CGNAT head-end IPsec runtime.

## Current State

Current CGNAT PKI handling lives mainly in:

| Area | Path |
| --- | --- |
| PKI materializer | `CGNAT/framework/src/cgnat/pki_materializer.py` |
| CGNAT customer package installer | `scripts/deployment/cgnat_customer_lib.py` |
| CGNAT customer examples | `muxer/config/customer-requests/examples/*cgnat*local-pki*.yaml` |
| CGNAT security model | `CGNAT/framework/docs/SECURITY_MODEL.md` |
| CGNAT identity model | `CGNAT/framework/docs/IDENTITY_MODEL.md` |

Current modes:

| Mode | Current behavior |
| --- | --- |
| `local_generate` | Generates local CA, head-end cert/key, and customer or gateway cert/key. Good for lab/demo. |
| `reference` | Emits manifests with references only. Material must be resolved outside the flow. |
| `provider_api` | Mode is modeled but not implemented. |

Current gap:

```text
We can generate demo material or reference external material, but we do not yet
have a production resolver that validates, stages, installs, and reloads
externally issued certificates on CGNAT head ends.
```

## Target Model

CGNAT should support a production certificate mode that consumes provided
material from one or more sources:

| Source | Example |
| --- | --- |
| Certificate server | Internal CA / Venafi / Step CA / custom PKI API. |
| AWS Secrets Manager | Cert, private key, and CA chain stored as secret values or JSON. |
| S3 artifact | Encrypted object containing cert bundle. |
| Local staged files | Operator-provided files in a controlled package path. |
| Future provider adapter | `provider_api` implementation. |

The resolver should normalize all sources into the same internal material set:

| Material | Required |
| --- | --- |
| Head-end certificate | Yes. |
| Head-end private key | Yes. |
| CA chain / trust anchor | Yes. |
| Certificate metadata | Yes. |
| Optional peer/customer/gateway handoff material | Topology dependent. |

## Proposed Request Shape

Keep `local_generate` for demo, but add a production mode such as
`provided_material`.

Example:

```yaml
customer:
  transport:
    mode: cgnat
    cgnat:
      outer_topology: shared_isp_gateway
      outer_gateway_ref: isp-cgnat-router-2
      outer_identity_ref: isp-cgnat-router-2/customer-1234
      outer_auth_ref: pki/cgnat/gateway/isp-cgnat-router-2/customer-1234
      pki:
        mode: provided_material
        material_source:
          type: secrets_manager
          region: us-east-1
          cert_secret_ref: /rpdb/cgnat/customer-1234/headend/cert
          key_secret_ref: /rpdb/cgnat/customer-1234/headend/key
          ca_chain_secret_ref: /rpdb/cgnat/customer-1234/trust/ca-chain
        headend:
          identity_ref: cgnat-head-end/customer-1234
          auth_ref: pki/cgnat/headend/customer-1234
        trust:
          ca_ref: pki/cgnat/ca/customer-1234
```

Alternative local staged-file shape:

```yaml
pki:
  mode: provided_material
  material_source:
    type: local_files
    cert_path: certs/cgnat/customer-1234/headend.crt
    key_path: certs/cgnat/customer-1234/headend.key
    ca_chain_path: certs/cgnat/customer-1234/ca-chain.crt
```

Do not put raw private key material directly in the customer request.

## Certificate Validation Requirements

Before install, the resolver must prove:

| Check | Requirement |
| --- | --- |
| Private key matches certificate | Required. |
| Certificate chain validates against trust anchor | Required. |
| Certificate is not expired | Required. |
| Certificate is not before its valid start time | Required. |
| SAN or CN matches modeled `identity_ref` | Required unless explicitly allowed by policy. |
| Key usage supports IPsec certificate auth | Required. |
| Extended key usage is acceptable for the role | Required by policy. |
| Material can be parsed by OpenSSL/strongSwan | Required. |
| File permissions are safe after staging | Required. |

Validation should fail closed. If a provided certificate cannot be proven valid,
the customer should not be applied to the CGNAT head end.

## Install Model

The CGNAT live apply should stage certificate material under a CGNAT-owned path,
for example:

```text
/etc/rpdb-cgnat/pki/<customer>/
  headend.crt
  headend.key
  ca-chain.crt
  install-manifest.json
```

Recommended ownership and permissions:

| File | Mode |
| --- | --- |
| Private key | `0600` |
| Certificates / CA chain | `0644` |
| Directory | `0700` or `0750` depending on strongSwan access model |

The CGNAT head-end apply path should then:

1. Copy resolved material to the CGNAT node.
2. Verify files exist and permissions are correct.
3. Render or update strongSwan credential references.
4. Run a load/reload command for IPsec credentials/config.
5. Record installed material metadata in the customer install state.
6. Add certificate cleanup to removal and rollback where safe.

## Code Work Plan

### Phase 1: Model And Schema

Files likely touched:

| File | Change |
| --- | --- |
| `muxer/config/schema/customer-request.schema.json` | Add `provided_material` material source shape. |
| `muxer/config/schema/customer-source.schema.json` | Mirror source model. |
| `muxer/src/muxerlib/customer_model.py` | Normalize new CGNAT PKI fields if needed. |
| `muxer/config/customer-requests/examples/` | Add one external-certificate CGNAT example. |

Acceptance:

```text
Customer requests can declare local_generate, reference, or provided_material
without breaking existing CGNAT demos.
```

### Phase 2: Material Resolver

Files likely touched:

| File | Change |
| --- | --- |
| `CGNAT/framework/src/cgnat/pki_materializer.py` | Add resolver for `provided_material`. |
| `CGNAT/framework/src/cgnat/certificate_resolver.py` | New helper module if the resolver grows large. |
| `CGNAT/tests/` | Add unit tests for material modes and validation failures. |

Resolver outputs should include:

| Output | Meaning |
| --- | --- |
| `headend_certificate_path` | Resolved/staged certificate. |
| `headend_private_key_path` | Resolved/staged key. |
| `ca_certificate_path` or `ca_chain_path` | Trust anchor/chain. |
| `material_mode` | `provided_material`. |
| `material_source_type` | `secrets_manager`, `local_files`, `s3`, or provider type. |
| `validation_report` | Explicit pass/fail checks. |

Acceptance:

```text
The materializer can consume external material and produce the same review
surface as local_generate, but without generating a new CA or keypair.
```

### Phase 3: Certificate Validation

Implement validation around OpenSSL first because it is already used by
`pki_materializer.py`.

Minimum command concepts:

```bash
openssl x509 -in headend.crt -noout -subject -issuer -dates -ext subjectAltName
openssl rsa -in headend.key -check -noout
openssl x509 -noout -modulus -in headend.crt | openssl md5
openssl rsa -noout -modulus -in headend.key | openssl md5
openssl verify -CAfile ca-chain.crt headend.crt
```

Acceptance:

```text
Bad key, expired cert, wrong CA, wrong identity, and malformed cert all block
the package before live apply.
```

### Phase 4: CGNAT Head-End Installer

Files likely touched:

| File | Change |
| --- | --- |
| `scripts/deployment/cgnat_customer_lib.py` | Install resolved PKI material and include it in validation. |
| `scripts/customers/live_apply_lib.py` | Ensure CGNAT PKI material is copied/applied with the CGNAT component. |
| `CGNAT/server/docs/` | Document host layout and strongSwan credential expectations. |

Acceptance:

```text
Approved customer apply places provided cert/key/CA chain on the CGNAT head end
and records the installed material in install-state.json.
```

### Phase 5: Certificate Server Adapter

Start with a pluggable interface rather than hardcoding one vendor:

```text
resolve_certificate_material(material_source) -> resolved material set
```

Initial source types:

| Type | Priority |
| --- | --- |
| `local_files` | First, easiest to test offline. |
| `secrets_manager` | Second, useful for AWS/live. |
| `s3` | Optional if bundle workflow needs object handoff. |
| `provider_api` | Later, after certificate server requirements are firm. |

Acceptance:

```text
The same CGNAT customer request can switch material source without changing the
rest of the CGNAT provisioning flow.
```

### Phase 6: Tests And Regression

Add tests for:

| Test | Expected result |
| --- | --- |
| `local_generate` unchanged | Existing CGNAT tests still pass. |
| `reference` unchanged | Reference-only handoff still works. |
| Valid provided material | Review is ready and material paths are emitted. |
| Cert/key mismatch | Blocked. |
| Wrong CA | Blocked. |
| Expired cert | Blocked. |
| Wrong identity | Blocked. |
| Missing private key | Blocked. |
| Missing CA chain | Blocked. |

Likely commands:

```bash
python -m unittest CGNAT.tests.test_cgnat_pki_materializer
python -m unittest CGNAT.tests.test_customer_provisioning_apply
python CGNAT/tests/run_regression.py
```

## Demo Plan After Implementation

1. Create a CGNAT customer request using `pki.mode: provided_material`.
2. Point it at a known-good cert/key/CA source.
3. Run dry-run provisioning and show the PKI validation report.
4. Approve apply and show the material installed on the CGNAT head end.
5. Show strongSwan loaded certs with `swanctl --list-certs`.
6. Start the outer tunnel and grep logs for certificate authentication.
7. Remove the customer and show cleanup behavior.

Useful validation commands on the CGNAT head end:

```bash
sudo swanctl --list-certs
sudo journalctl --since "-30 min" --no-pager \
  | grep -Ei "IKE_SA|CHILD_SA|certificate|cert|AUTH|issuer|subject|trusted|CN="
sudo find /etc/rpdb-cgnat/pki -maxdepth 3 -type f -ls
```

## Open Decisions

| Decision | Options |
| --- | --- |
| Primary certificate server | Internal CA, Venafi, Step CA, ACM PCA, or custom API. |
| Runtime cert format | PEM files first, optional PKCS#12 later. |
| Secret storage | Secrets Manager, S3, local secure staging, or provider pull. |
| Identity matching policy | SAN required, CN fallback allowed, or configurable. |
| Rotation behavior | Reapply customer, separate rotate command, or watcher-driven rotation. |
| Removal behavior | Delete per-customer certs always, retain shared gateway certs, or policy-based. |

## Restart Point

When this work resumes, start with Phase 1 and Phase 2:

```text
Add a provided_material request shape, implement a local_files resolver, and
add validation tests for good and bad cert/key/CA combinations.
```

Do not start with the certificate server adapter. Prove the resolver and
installer contract with local staged files first, then plug in the real
certificate server.

