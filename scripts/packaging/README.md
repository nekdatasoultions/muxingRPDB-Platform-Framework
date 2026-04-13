# Packaging Scripts

This directory holds bundle creation helpers.

Current helper:

- `assemble_customer_bundle.py`
  - assembles a customer-scoped bundle from generated artifacts
  - copies the merged customer module and DynamoDB item into the bundle
  - optionally copies source, muxer, and head-end artifacts
  - writes bundle metadata plus manifest/checksum files
- `build_customer_bundle_manifest.py`
  - walks a customer bundle directory
  - writes `manifest.txt`
  - writes `sha256sums.txt`
- `validate_customer_bundle.py`
  - checks for the expected top-level bundle files
  - checks for the expected bundle directories
  - warns when recommended bundle files are missing

Example:

```powershell
# First, on the framework branch, export the customer handoff directory.
# Then, on this deployment branch, assemble the bundle from that export.
python scripts\packaging\assemble_customer_bundle.py `
  --bundle-dir build\customer-bundle `
  --export-dir build\handoff-example-nat-0001
python scripts\packaging\build_customer_bundle_manifest.py build\customer-bundle
python scripts\packaging\validate_customer_bundle.py build\customer-bundle
```

Planned next helpers:

- publish reviewed artifacts to the chosen release location
