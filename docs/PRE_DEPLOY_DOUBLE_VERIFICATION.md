# Pre-Deploy Double Verification

## Goal

Before any first deploy rehearsal or live-node change, run the same repo-only
verification path across both branches:

- framework branch proves the customer model, render, export, and environment
  binding
- deployment branch proves packaging, notes, backup-gate checks, and readiness

## Wrapper

- [run_double_verification.py](/scripts/deployment/run_double_verification.py)

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
10. apply the bundle to a staged head-end root
11. validate the staged head-end install
12. remove the staged head-end install
13. verify the backup baseline
14. generate pre-change backup notes
15. generate rollout and rollback notes
16. run deployment readiness

## Example

Strict non-NAT example:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo "<framework-repo-root>" `
  --deployment-repo "<deployment-repo-root>" `
  --customer-source "muxer\config\customer-sources\migrated\legacy-cust0003\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\current-dev-nonnat-active-a.yaml" `
  --baseline-dir "<repo-root>\build\verification-fixtures\pre-rpdb-baseline"
```

NAT example:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo "<framework-repo-root>" `
  --deployment-repo "<deployment-repo-root>" `
  --customer-source "muxer\config\customer-sources\migrated\vpn-customer-stage1-15-cust-0003\customer.yaml" `
  --environment-file "muxer\config\environment-defaults\current-dev-nat-active-a.yaml" `
  --baseline-dir "<repo-root>\build\verification-fixtures\pre-rpdb-baseline"
```

## Output

The wrapper writes a JSON summary plus the intermediate rendered, bound, and
packaged outputs under `build\double-verification\<customer-name>\...`.

The new staged head-end root also lives there during the verification run:

- `build\double-verification\<customer-name>\headend-root`

## Gate

No live-node work should begin until this wrapper succeeds for the target
customer and the resulting summary has been reviewed.

The review must include bidirectional initiation evidence:

- customer/right initiated traffic brings up or uses the tunnel
- core/left initiated traffic brings up or uses the tunnel
- packet captures prove the encrypted public-edge path for both directions
- strict non-NAT UDP/500 and ESP/50 customers prove return-path ESP SNAT from
  the head-end public identity to the muxer public ENI private IP
- the deployment is blocked if only one side can initiate successfully

One honest boundary remains:

- the wrapper still expects a valid backup baseline fixture or shared baseline
  path
- if that input is missing, the earlier framework, bundle, and staged head-end
  orchestration steps can still pass while the backup-gate portion fails
