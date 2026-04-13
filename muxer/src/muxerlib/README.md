# muxerlib

This package will hold the RPDB muxer control-plane logic.

Expected future areas:

- customer source loading
- defaults and class merge logic
- DynamoDB SoT client
- RPDB priority allocation
- customer-scoped render helpers
- customer-scoped apply helpers

Initial modules now included:

- `customer_model.py`
  - typed customer source parsing
  - RPDB priority helper
  - DynamoDB item construction
- `customer_merge.py`
  - defaults/class/source merge
  - merged customer module assembly
  - YAML loading helpers for the early workflow scripts
