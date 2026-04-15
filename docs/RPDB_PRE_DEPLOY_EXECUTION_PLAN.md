# RPDB Pre-Deploy Execution Plan

## Boundary

This plan stays inside the RPDB repository only:

- `E:\Code1\muxingRPDB Platform Framework-main`

This plan does not allow:

- edits to `E:\Code1\MUXER3`
- SSH or SSM to live nodes
- production DynamoDB writes
- live muxer apply
- live VPN head-end apply
- EIP movement
- customer cutover

## Goal

Reach the live-deployment gate with reviewable, reproducible, repo-only
artifacts for the first pilot customers.

The plan stops before deployment. The output is a verified package set,
verification evidence, and a clear deploy/no-deploy decision point.

## Pilot Scope

Included:

- `legacy-cust0002`
  - request: `muxer/config/customer-requests/migrated/legacy-cust0002.yaml`
  - expected starting behavior: dynamic default strict non-NAT
  - expected initial backend: non-NAT

- `vpn-customer-stage1-15-cust-0004`
  - request: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
  - expected starting behavior: dynamic default strict non-NAT
  - expected NAT-T behavior: automated log watcher observes UDP/500 followed by
    UDP/4500 and prepares a NAT-T promotion package

Excluded:

- `legacy-cust0003`
- `vpn-customer-stage1-15-cust-0003`

Customer 3 variants remain excluded because they are live/demo-sensitive
customers.

## Stage 1: Repo Boundary Check

Command:

```powershell
git status --short --branch
```

Validation:

- branch is `main`
- repo is clean before work starts, or only intentional RPDB files are changed
- no files outside this repository are touched

## Stage 2: Validate Pilot Requests

Commands:

```powershell
python muxer\scripts\validate_customer_request.py `
  muxer\config\customer-requests\migrated\legacy-cust0002.yaml

python muxer\scripts\validate_customer_request.py `
  muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml
```

Validation:

- both requests validate
- both requests keep stack selection omitted for normal onboarding
- effective class starts as `strict-non-nat`
- pool class starts as `non-nat`
- dynamic provisioning is `nat_t_auto_promote`

## Stage 3: Build Customer 2 Non-NAT Package

Command:

```powershell
python muxer\scripts\provision_customer_end_to_end.py `
  muxer\config\customer-requests\migrated\legacy-cust0002.yaml `
  --out-dir build\pre-deploy\legacy-cust0002 `
  --json
```

Validation:

- package status is `ready_for_review`
- `live_apply` is `false`
- generated environment file is `rpdb-empty-nonnat-active-a.yaml`
- package includes customer, muxer, head-end, DynamoDB item, allocation, bundle,
  readiness, and double-verification artifacts

## Stage 4: Exercise Automated NAT-T Promotion For Customer 4

Create a repo-local JSONL fixture with UDP/500 followed by UDP/4500 from the
Customer 4 peer, then run the watcher.

Command:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --log-file build\pre-deploy\nat-t-watcher\muxer-events.jsonl `
  --out-dir build\pre-deploy\nat-t-watcher\out `
  --state-file build\pre-deploy\nat-t-watcher\state.json `
  --package-root build\pre-deploy\nat-t-watcher\packages `
  --run-provisioning `
  --json
```

Validation:

- exactly one NAT-T observation is detected
- detected customer is `vpn-customer-stage1-15-cust-0004`
- generated package status is `ready_for_review`
- `live_apply` is `false`
- generated package uses the NAT environment binding
- a second watcher pass detects zero new events
- preserve the first-pass and second-pass watcher summaries separately if an
  operator needs durable evidence for both detection and idempotency

## Stage 5: Full Repo Verification

Command:

```powershell
python muxer\scripts\run_repo_verification.py --json
```

Validation:

- all repo verification steps pass
- automated NAT-T watcher verification passes
- head-end customer orchestration still passes in staged roots
- no live apply occurs

## Stage 6: Artifact Review

Review these generated artifact groups:

- `build/pre-deploy/legacy-cust0002/provisioning-run.json`
- `build/pre-deploy/legacy-cust0002/pilot-readiness.json`
- `build/pre-deploy/legacy-cust0002/bundle/`
- `build/pre-deploy/nat-t-watcher/out/watch-summary-first-pass.json`
- `build/pre-deploy/nat-t-watcher/out/watch-summary-second-pass.json`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004/provisioning-run.json`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004/pilot-readiness.json`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004/bundle/`
- `build/repo-verification/repo-verification-summary.json`

Validation:

- allocated customer ID, fwmark, route table, RPDB priority, tunnel key,
  overlay, interface names, and backend assignment are present
- customer request intent is traceable to customer source, module, DynamoDB
  item, bundle, staged head-end artifacts, and readiness report
- NAT-T promotion is traceable to an observed UDP/4500 event from the same peer
- generated packages remain review-only with `live_apply: false`

## Stage 7: Commit And Push Repo-Only Changes

Commands:

```powershell
git diff --check
git status --short --branch
git add <intentional-rpdb-files>
git commit -m "<message>"
git push origin main
git status --short --branch
git rev-parse HEAD origin/main
```

Validation:

- only RPDB files are committed
- `HEAD` matches `origin/main`
- working tree is clean

## Stage 8: Stop At Deployment Gate

This plan is complete when Stages 1 through 7 pass.

Do not proceed to live deployment until a separate deployment plan identifies:

- exact customer
- exact muxer instance
- exact VPN head-end
- exact backup commands
- exact apply commands
- exact packet-capture validation commands
- exact rollback commands
- change window
- approval owner

## Current Execution Checkpoint

Status: repo-only pre-deploy gate passed.

Last executed: 2026-04-15.

Completed stages:

- Stage 1 passed: repo boundary stayed inside
  `E:\Code1\muxingRPDB Platform Framework-main`.
- Stage 2 passed: `legacy-cust0002` validated as
  `effective_class=strict-non-nat`, `pool_class=non-nat`, with
  `nat_t_auto_promote`.
- Stage 2 passed: `vpn-customer-stage1-15-cust-0004` validated as
  `effective_class=strict-non-nat`, `pool_class=non-nat`, with
  `nat_t_auto_promote`.
- Stage 3 passed: `legacy-cust0002` package generated at
  `build/pre-deploy/legacy-cust0002`, status `ready_for_review`,
  environment `rpdb-empty-nonnat-active-a.yaml`, `live_apply: false`.
- Stage 4 passed: Customer 4 NAT-T watcher first pass detected one UDP/500
  then UDP/4500 sequence from `3.237.201.84`, generated one observation,
  produced a NAT package at
  `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004`,
  and kept `live_apply: false`.
- Stage 4 idempotency passed: second watcher pass detected zero new events.
- Stage 5 passed: `python muxer\scripts\run_repo_verification.py --json`
  completed successfully, including automated NAT-T watcher verification and
  staged head-end orchestration.

Generated evidence:

- `build/pre-deploy/legacy-cust0002/provisioning-run.json`
- `build/pre-deploy/legacy-cust0002/pilot-readiness.json`
- `build/pre-deploy/nat-t-watcher/out/watch-summary-first-pass.json`
- `build/pre-deploy/nat-t-watcher/out/watch-summary-second-pass.json`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004/provisioning-run.json`
- `build/pre-deploy/nat-t-watcher/packages/vpn-customer-stage1-15-cust-0004/pilot-readiness.json`
- `build/repo-verification/repo-verification-summary.json`

Current gate:

- Ready for artifact review and deployment-plan drafting.
- Not approved for live deployment yet.
- Live deployment remains blocked until the separate deployment plan names the
  exact node targets, backup commands, apply commands, packet-capture checks,
  rollback commands, change window, and approval owner.
