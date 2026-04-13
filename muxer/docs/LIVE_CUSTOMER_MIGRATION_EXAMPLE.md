# Live Customer Migration Example

## Goal

Show how one real production-shaped customer can be represented in the RPDB
 framework without copying inline secrets into the repo.

## Example Customer

- migrated source:
  [legacy-cust0003/customer.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/customer-sources/migrated/legacy-cust0003/customer.yaml)
- current legacy source reference:
  [customer.yaml](/E:/Code1/MUXER3/config/customers/legacy-cust0003/customer.yaml)

## What This Example Proves

- a real strict non-NAT customer can fit the new per-customer source model
- the source file can keep the customer shape without storing the PSK inline
- environment binding can supply deployment-specific values later
- deployment packaging can consume the migrated customer exactly like the
  earlier examples

## Notable Mappings

- customer name: `legacy-cust0003`
- peer/public ID: `166.213.153.41`
- local subnets:
  - `172.31.54.39/32`
  - `194.138.36.80/28`
  - `172.30.0.90/32`
- remote subnet:
  - `10.129.4.12/32`
- transport:
  - fwmark `0x2003`
  - route table `2003`
  - tunnel key `1003`
  - interface `gre-cust-0003`
- post-IPsec NAT metadata:
  - translated block `172.30.2.32/27`
  - currently disabled in the migrated source

## Secret Handling

The migrated source uses:

```yaml
psk_secret_ref: /muxingrpdb/dev/customers/legacy-cust0003/psk
```

That keeps the framework focused on shape and intent while leaving actual
secret resolution to deployment-time binding.

## Scope

This is still a repo-only migration example. It does not change the live muxer
or head-end nodes.
