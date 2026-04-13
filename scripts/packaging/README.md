# Packaging Scripts

This directory holds bundle creation helpers.

Current helper:

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
python scripts\packaging\build_customer_bundle_manifest.py build\customer-bundle
python scripts\packaging\validate_customer_bundle.py build\customer-bundle
```

Planned next helpers:

- build customer-scoped bundles
- publish reviewed artifacts to the chosen release location
