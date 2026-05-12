# Customer Source Layout

## Goal

Each customer should be authored as its own source file.

This keeps the control plane modular and reduces the blast radius of ordinary
customer work.

## Layout

```text
muxer/config/customer-defaults/
  defaults.yaml
  classes/
    nat.yaml
    strict-non-nat.yaml

muxer/config/customer-sources/
  <customer-name>/
    customer.yaml
  examples/
    <example-customer-name>/
      customer.yaml
  migrated/
    <live-customer-name>/
      customer.yaml
```

## Layering Model

Each rendered customer module should be built from:

1. shared defaults
2. class defaults
3. customer overrides

## Secrets

Customer source files should not store inline PSKs for production workflows.

Use a secret reference, for example:

```yaml
psk_secret_ref: /muxingrpdb/customers/example/psk
```

For lab and demo flows, a customer request can opt into a local inline PSK:

```yaml
psk_source: local
psk: replace-me-demo-only
```

Live apply still rejects that request unless the deployment environment enables:

```yaml
secrets:
  allow_local_psk: true
```

That switch is intentionally environment-scoped. It lets us prove customer
provisioning without pre-seeding AWS Secrets Manager, while keeping the normal
path anchored on secret references.

Customers that use certificate authentication do not set `psk_secret_ref` or
inline PSK fields. Instead, the customer source carries `ipsec.auth` with
references to the provided PEM material:

```yaml
ipsec:
  auth:
    method: certificate
    certificate:
      profile: customer_supplied
      headend:
        id: rpdb-headend.example
        cert_ref: /muxingrpdb/customers/example/headend-cert
        private_key_secret_ref: /muxingrpdb/customers/example/headend-key
        private_key_passphrase_secret_ref: /muxingrpdb/customers/example/headend-key-passphrase
      remote:
        id: customer-cert.example
        trust_ref: /muxingrpdb/customers/example/customer-trust
```

The request stores references only. Live apply resolves those references,
installs the head-end certificate/key/trust into the strongSwan swanctl
directories, and renders the connection as `auth = pubkey` instead of PSK. The
passphrase reference is optional and is only needed when the provided private
key is encrypted.

## Operational Intent

The default workflow should be:

- edit one customer source
- validate one customer source
- sync one customer to DynamoDB
- render one customer
- apply one customer

## Migration Pattern

Use `examples/` for framework-only sample customers and `migrated/` for
production-shaped customers being translated from the current live model into
the new RPDB structure.
