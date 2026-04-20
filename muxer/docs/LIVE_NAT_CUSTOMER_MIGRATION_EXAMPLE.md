# Live NAT Customer Migration Example

## Goal

Show how a current NAT-T production-shaped customer fits into the RPDB
framework using the same one-file-per-customer model as the strict example.

## Example Customer

- migrated source:
  [vpn-customer-stage1-15-cust-0003/customer.yaml](/muxer/config/customer-sources/migrated/vpn-customer-stage1-15-cust-0003/customer.yaml)
- current legacy source reference:
  [customer.yaml](legacy-muxer3:/config/customers/vpn-customer-stage1-15-cust-0003/customer.yaml)

## What This Example Proves

- a real NAT customer can fit the RPDB customer source schema
- the source file can keep tunnel shape, NAT selectors, and overlap metadata
- the PSK can be represented as a secret reference instead of inline repo data
- the same deployment export and bundle flow used for examples also works for a
  production-shaped NAT customer

## Notable Mappings

- customer name: `vpn-customer-stage1-15-cust-0003`
- peer/public ID: `3.215.115.178`
- local subnets:
  - `172.31.54.39/32`
  - `194.138.36.80/28`
- remote subnet:
  - `10.129.3.154/32`
- transport:
  - fwmark `0x41003`
  - route table `41003`
  - tunnel key `41003`
  - interface `gre-s15-0003`
- post-IPsec NAT metadata:
  - translated block `172.30.0.64/27`
  - real subnet `10.129.3.154/32`
  - output mark `0x41003/0xffffffff`

## Secret Handling

The migrated source uses:

```yaml
psk_secret_ref: /muxingrpdb/dev/customers/vpn-customer-stage1-15-cust-0003/psk
```

That keeps the customer shape in repo while leaving the actual PSK outside the
framework.

## Scope

This is still a repo-only migration example. It does not change the live NAT
head-end pair or the muxer.
