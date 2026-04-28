# Placement and Variables

## Purpose

This document records the fixed subnet placement rules for the initial CGNAT
design and the rule that EC2 address and subnet assignment must be modeled by
variables or configuration rather than hardcoded values.

## Fixed Placement Rules

### CGNAT HEAD END

The CGNAT HEAD END must exist only in:

- `subnet-04a6b7f3a3855d438`

### CGNAT ISP HEAD END

The CGNAT ISP HEAD END must span:

- `subnet-04a6b7f3a3855d438`
- `subnet-0e6ae1d598e08d002`

### Customer Devices

Customer devices behind the CGNAT ISP HEAD END must exist only in:

- `subnet-0e6ae1d598e08d002`

## Modeling Rule

All EC2 placement and addressing assumptions must be modeled through
variables/configuration.

This includes:

- subnet assignment
- interface placement
- instance role placement
- any required inside addressing
- any required public loopback assumptions

No prototype code should hardcode operationally important instance IPs or
subnet choices.

## Example Configuration Shape

```yaml
cgnat_environment:
  cgnat_head_end:
    allowed_subnets:
      - subnet-04a6b7f3a3855d438

  cgnat_isp_head_end:
    allowed_subnets:
      - subnet-04a6b7f3a3855d438
      - subnet-0e6ae1d598e08d002

  customer_devices:
    allowed_subnets:
      - subnet-0e6ae1d598e08d002
```

## Validation Requirements

The CGNAT design must eventually validate that:

- a CGNAT HEAD END is rejected if placed outside
  `subnet-04a6b7f3a3855d438`
- a CGNAT ISP HEAD END is rejected if placed outside the allowed two-subnet
  set
- customer devices are rejected if placed outside
  `subnet-0e6ae1d598e08d002`
- configuration missing required subnet variables fails clearly
- no prototype path depends on hardcoded EC2 IP assignments

## Design Intent

The placement model intentionally separates:

- the platform-side CGNAT HEAD END on the transit/interconnect side
- the CGNAT ISP HEAD END as the bridge between transit and customer-side
  placement
- the customer devices on the customer-facing side only

That separation should remain visible in both configuration and validation.
