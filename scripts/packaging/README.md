# Packaging Scripts

This directory holds bundle creation helpers.

Current helper:

- `build_customer_bundle_manifest.py`
  - walks a customer bundle directory
  - writes `manifest.txt`
  - writes `sha256sums.txt`

Example:

```powershell
python scripts\packaging\build_customer_bundle_manifest.py build\customer-bundle
```

Planned next helpers:

- build customer-scoped bundles
- publish reviewed artifacts to the chosen release location
