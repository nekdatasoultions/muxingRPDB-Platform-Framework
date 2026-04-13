# Pre-Deploy Double Verification

## Goal

Before any first deploy rehearsal or live-node change, run the same repo-only
verification path across both branches:

- framework branch proves the customer model, render, export, and environment
  binding
- deployment branch proves packaging, notes, backup-gate checks, and readiness

## Wrapper

- [run_double_verification.py](/E:/Code1/muxingRPDB%20Platform%20Framework/scripts/deployment/run_double_verification.py)

## What It Runs

1. validate one customer source
2. render customer artifacts
3. validate rendered artifacts
4. validate environment bindings
5. export the framework handoff
6. bind the handoff to the environment
7. validate the bound handoff
8. assemble the customer bundle
9. validate the customer bundle
10. verify the backup baseline
11. generate pre-change backup notes
12. generate rollout and rollback notes
13. run deployment readiness

## Example

Strict non-NAT example:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo "E:\Code1\muxingRPDB Platform Framework-fw" `
  --deployment-repo "E:\Code1\muxingRPDB Platform Framework-deploy" `
  --customer-source "muxer\config\customer-sources\migrated\legacy-cust0003\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\current-dev-nonnat-active-a.yaml" `
  --baseline-dir "E:\Code1\muxingRPDB Platform Framework\build\verification-fixtures\pre-rpdb-baseline"
```

NAT example:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo "E:\Code1\muxingRPDB Platform Framework-fw" `
  --deployment-repo "E:\Code1\muxingRPDB Platform Framework-deploy" `
  --customer-source "muxer\config\customer-sources\migrated\vpn-customer-stage1-15-cust-0003\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\current-dev-nat-active-a.yaml" `
  --baseline-dir "E:\Code1\muxingRPDB Platform Framework\build\verification-fixtures\pre-rpdb-baseline"
```

## Output

The wrapper writes a JSON summary plus the intermediate rendered, bound, and
packaged outputs under `build\double-verification\<customer-name>\...`.

## Gate

No live-node work should begin until this wrapper succeeds for the target
customer and the resulting summary has been reviewed.
