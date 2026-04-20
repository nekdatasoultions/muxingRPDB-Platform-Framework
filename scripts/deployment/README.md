# Deployment Scripts

This directory holds customer-scoped deployment helpers.

Current helper:

- `deployment_readiness_check.py`
  - verifies the customer bundle has manifest/checksum files
  - verifies the required baseline snapshots exist
  - verifies optional rollout-specific pre-change and rollback notes
- `create_rollout_notes.py`
  - creates `rollout.md` and `rollback.md` templates for one customer-scoped
    change
- `run_double_verification.py`
  - runs the full repo-only verification path across the framework and
    deployment branches for one customer
  - stops on the first failure and writes a JSON summary for review
- `apply_headend_customer.py`
  - installs one customer's head-end artifacts into a target head-end root
  - stages `swanctl`, route, and post-IPsec NAT customer files under a stable
    per-customer layout
- `apply_muxer_customer.py`
  - installs one customer's muxer artifacts into a target muxer root
  - stages tunnel, routing, firewall, and customer-module files under a stable
    per-customer layout
- `apply_backend_customer.py`
  - stages one customer's customer SoT and allocation JSON payloads into a
    backend root
  - gives Phase 4 a customer-scoped backend write model without touching AWS
- `validate_headend_customer.py`
  - validates a bundle's head-end installability
  - optionally validates a staged install root after apply
- `validate_muxer_customer.py`
  - validates a bundle's muxer installability
  - optionally validates a staged muxer root after apply
- `validate_backend_customer.py`
  - validates a package's backend installability
  - optionally validates a staged backend root after apply
- `remove_headend_customer.py`
  - removes one previously staged customer from a target head-end root
- `remove_muxer_customer.py`
  - removes one previously staged customer from a target muxer root
- `remove_backend_customer.py`
  - removes one previously staged customer from a target backend root

Example:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle
python scripts\deployment\create_rollout_notes.py `
  --customer-name example-nat-0001 `
  --out-dir notes\example-nat-0001
python scripts\deployment\run_double_verification.py `
  --framework-repo "<framework-repo-root>" `
  --deployment-repo "<deployment-repo-root>" `
  --customer-source "muxer\config\customer-sources\examples\example-nat-0001\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\example-environment.yaml" `
  --baseline-dir "<repo-root>\build\verification-fixtures\pre-rpdb-baseline"
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
python scripts\deployment\apply_muxer_customer.py `
  --bundle-dir build\customer-bundle `
  --muxer-root build\staged-muxer-root
python scripts\deployment\apply_backend_customer.py `
  --package-dir build\customer-package `
  --backend-root build\staged-backend-root
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
python scripts\deployment\validate_muxer_customer.py `
  --bundle-dir build\customer-bundle `
  --muxer-root build\staged-muxer-root
python scripts\deployment\validate_backend_customer.py `
  --package-dir build\customer-package `
  --backend-root build\staged-backend-root
python scripts\deployment\remove_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
python scripts\deployment\remove_muxer_customer.py `
  --bundle-dir build\customer-bundle `
  --muxer-root build\staged-muxer-root
python scripts\deployment\remove_backend_customer.py `
  --package-dir build\customer-package `
  --backend-root build\staged-backend-root
```

Reference:

- [HEADEND_CUSTOMER_ORCHESTRATION.md](/docs/HEADEND_CUSTOMER_ORCHESTRATION.md)
