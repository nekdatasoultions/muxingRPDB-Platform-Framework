# Placement and Variables

## Purpose

This document records the placement rules for the initial CGNAT design and the
rule that EC2 address and subnet assignment must be modeled by variables or
configuration rather than hardcoded values.

## Fixed Placement Rules

### CGNAT HEAD END

The CGNAT HEAD END must exist only in:

- `subnet-04a6b7f3a3855d438`

### CGNAT ISP HEAD END

For the single-instance demo model, the CGNAT ISP HEAD END must use:

- an operations-defined transit subnet
- an operations-defined customer-facing subnet
- a same-AZ subnet pair when the node is modeled as one EC2 instance with
  multiple ENIs

### Customer Devices

Customer devices behind the CGNAT ISP HEAD END must:

- use the operations-defined customer-facing subnet selected for the demo

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
      - subnet-0dbd0842618d43ab3
    same_az_required_for_single_instance: true

  customer_devices:
    allowed_subnets:
      - subnet-0dbd0842618d43ab3
```

## Validation Requirements

The CGNAT design must eventually validate that:

- a CGNAT HEAD END is rejected if placed outside
  `subnet-04a6b7f3a3855d438`
- a CGNAT ISP HEAD END is rejected if placed outside the allowed operations
  subnet set
- customer devices are rejected if placed outside the configured
  customer-facing subnet set
- a single-instance ISP demo node is rejected if its transit and
  customer-facing subnets are in different AZs
- configuration missing required subnet variables fails clearly
- no prototype path depends on hardcoded EC2 IP assignments

## Design Intent

The placement model intentionally separates:

- the platform-side CGNAT HEAD END on the transit/interconnect side
- the CGNAT ISP HEAD END as the bridge between transit and customer-side
  placement
- the customer devices on the customer-facing side only

That separation should remain visible in both configuration and validation.
