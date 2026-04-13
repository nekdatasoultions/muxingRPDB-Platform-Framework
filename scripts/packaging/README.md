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
python scripts\packaging\assemble_customer_bundle.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle `
  --customer-module build\customer-module.json `
  --customer-ddb-item build\customer-item.json
python scripts\packaging\build_customer_bundle_manifest.py build\customer-bundle
python scripts\packaging\validate_customer_bundle.py build\customer-bundle
```

Planned next helpers:

- publish reviewed artifacts to the chosen release location
