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
- `validate_headend_customer.py`
  - validates a bundle's head-end installability
  - optionally validates a staged install root after apply
- `remove_headend_customer.py`
  - removes one previously staged customer from a target head-end root

Example:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name example-nat-0001 `
  --bundle-dir build\customer-bundle
python scripts\deployment\create_rollout_notes.py `
  --customer-name example-nat-0001 `
  --out-dir notes\example-nat-0001
python scripts\deployment\run_double_verification.py `
  --framework-repo "E:\Code1\muxingRPDB Platform Framework-fw" `
  --deployment-repo "E:\Code1\muxingRPDB Platform Framework-deploy" `
  --customer-source "muxer\config\customer-sources\examples\example-nat-0001\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\example-environment.yaml" `
  --baseline-dir "E:\Code1\muxingRPDB Platform Framework\build\verification-fixtures\pre-rpdb-baseline"
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
python scripts\deployment\remove_headend_customer.py `
  --bundle-dir build\customer-bundle `
  --headend-root build\staged-headend-root
```

Reference:

- [HEADEND_CUSTOMER_ORCHESTRATION.md](/E:/Code1/muxingRPDB%20Platform%20Framework-main/docs/HEADEND_CUSTOMER_ORCHESTRATION.md)
