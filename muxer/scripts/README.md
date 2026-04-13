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
- `render_customer_artifacts.py`
  - renders customer-scoped muxer and head-end artifact trees
  - writes structured files under `muxer/` and `headend/`
- `export_customer_handoff.py`
  - exports one standard framework-side handoff directory
  - writes `customer-module.json` and `customer-ddb-item.json`
  - copies the source YAML
  - generates muxer and head-end intent artifacts by default
  - optionally copies muxer and head-end customer artifact directories

Planned next helpers:

- sync one customer to DynamoDB
- render one customer
- render all customers intentionally
