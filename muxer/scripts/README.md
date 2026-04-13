# Scripts

This directory holds the early customer-scoped workflow commands.

Current scaffold helpers:

- `validate_customer_source.py`
  - validates a single customer source file
  - loads defaults and class overrides
  - assembles a merged customer module
- `build_customer_item.py`
  - builds a merged customer module
  - emits the DynamoDB item shape for one customer

Planned next helpers:

- sync one customer to DynamoDB
- render one customer
- render all customers intentionally
- apply one customer
