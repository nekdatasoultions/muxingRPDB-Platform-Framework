# Certificate Auth Model

## Purpose

Some customers cannot or should not use IKE PSKs. For those customers, the
customer request can select certificate authentication and provide references
to already-approved PEM material. The framework does not mint these certs in
this path. It consumes what has been provided, stages it onto the selected VPN
head end, and renders strongSwan `swanctl` for public-key authentication.

## Supported Profiles

`third_party_provided`

The certificate source gives us the head-end certificate, head-end private key,
and the remote/customer trust bundle. We install those on the head end. If we
also need to hand material to the customer, the request can include
`customer_handoff` references for the customer certificate, customer private
key, and head-end trust bundle.

`customer_supplied`

The customer owns the trust model and tells us which certificate/key/trust
material we must use. We install the customer-approved head-end cert/key and
their remote trust bundle. The customer side remains their responsibility
unless `customer_handoff` is explicitly enabled.

## Request Shape

```yaml
customer:
  peer:
    public_ip: 203.0.113.70
  ipsec:
    auth:
      method: certificate
      certificate:
        profile: third_party_provided
        headend:
          id: rpdb-headend.example
          cert_ref: /muxingrpdb/customers/example/headend-cert
          private_key_secret_ref: /muxingrpdb/customers/example/headend-key
          private_key_passphrase_secret_ref: /muxingrpdb/customers/example/headend-key-passphrase
        remote:
          id: customer-cert.example
          trust_ref: /muxingrpdb/customers/example/customer-trust
```

Do not include `peer.psk_secret_ref`, `peer.psk_source`, or `peer.psk` for a
certificate-authenticated customer. The parser rejects mixed PSK and
certificate auth because that ambiguity is dangerous during live apply.

## Material References

Material references resolve during approved live apply.

- Secrets Manager references are treated as secret IDs and read with
  `aws secretsmanager get-secret-value`.
- `file://` references are supported for controlled lab/demo work and must
  point to an existing local PEM file.
- Plain existing local paths are also accepted for lab workflows.
- Missing `file://` material fails immediately instead of falling back to a
  secret lookup.
- Passphrase-protected head-end private keys are supported by setting
  `headend.private_key_passphrase_secret_ref`.

Private keys should use `private_key_secret_ref`. Public certs and trust
bundles can be stored as secrets or mounted files depending on the environment.

For lab work, [DEMO_CA_SERVER.md](DEMO_CA_SERVER.md) describes the local demo
issuer that mimics a third-party CA and emits certificate-auth customer request
YAML for dry-run provisioning.

## Head-End Install Paths

For customer `<customer>`, live apply stages:

- `/etc/swanctl/x509/rpdb-customers/<customer>-headend-cert.pem`
- `/etc/swanctl/private/<customer>-headend-key.pem`
- `/etc/swanctl/x509ca/rpdb-customers/<customer>-remote-trust.pem`
- `/etc/swanctl/x509/rpdb-customers/<customer>-remote-cert.pem` when a remote
  certificate reference is provided

The generated `swanctl` connection uses `auth = pubkey`, points at those files,
and omits the PSK `secrets {}` block entirely. If
`private_key_passphrase_secret_ref` is present, the generated config includes a
native swanctl private-key secret block:

```text
secrets {
  private-<customer>-headend-key {
    file = <customer>-headend-key.pem
    secret = resolved-via-secret-store
  }
}
```

During approved live apply, `resolved-via-secret-store` is replaced with the
real passphrase from the configured reference before the config is copied to
the head end.

## Deprovisioning

Customer removal now cleans up both the swanctl connection and any
customer-scoped certificate material. That applies to the generated head-end
remove script and the standalone `remove_customer.py` workflow.

## Current Boundary

This feature covers regular VPN head-end customer auth. CGNAT outer
certificate-server integration remains a separate plan because that path has
gateway and customer-package ownership concerns beyond this head-end swanctl
auth switch.
