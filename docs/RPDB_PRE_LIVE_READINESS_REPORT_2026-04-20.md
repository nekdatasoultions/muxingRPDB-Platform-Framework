# RPDB Pre-Live Readiness Report - 2026-04-20

## Scope

This report records the repo-only readiness gate for the RPDB customer
workflow.

The target operating model remains:

```text
provide one customer request file
run one customer deploy script
RPDB handles allocation, target selection, packaging, validation, and rollback artifacts
```

No live apply was performed during this gate.

## Guardrails

- stayed inside this repository
- did not modify or use the MUXER3 repository
- did not call AWS APIs
- did not use SSH, SSM, or live-node commands
- did not deploy or apply a real customer
- did not move EIPs
- did not touch Customer 3 variants
- did not allow `iptables-restore` as a generated runtime fallback
- kept the head-end post-IPsec NAT activation path on `nftables`

## Gate Summary

| Phase | Result | Evidence |
| --- | --- | --- |
| Phase 1: baseline repo gate | passed | `main` was aligned with `origin/main` at commit `6ca3bcb17483c367f35f36025f67cf18401f1a0c` before new work began. |
| Phase 2: customer dry-run gate | passed | Customer 2 and Customer 4 both produced `dry_run_ready` execution plans. |
| Phase 3: artifact integrity gate | passed after fix | Initial generated artifacts still contained the literal `iptables-restore` token as prohibited metadata. The generator and bundle validator were corrected, packages were regenerated, and the final artifact scan found zero matches. |
| Phase 4: staged apply/remove gate | passed | Both customers installed, validated, and removed from local staged head-end roots. |
| Phase 5: scale/regression gate | passed | Full repo verification completed with `30` passed steps and zero failed steps. |
| Phase 6: readiness report | passed | This report captures the evidence and stop point. |
| Phase 7: live-node stop point | active | Stop before live-node validation or customer apply. |

## Customer Dry-Run Results

### Legacy Customer 2

- request file: `muxer/config/customer-requests/migrated/legacy-cust0002.yaml`
- environment contract: `example-rpdb`
- execution plan: `build/pre-live-readiness/legacy-cust0002/execution-plan.json`
- status: `dry_run_ready`
- selected head-end family: `non_nat`
- dynamic NAT-T promotion: `not_used`
- live apply: `false`
- errors: none

### Customer 4

- request file: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
- NAT-T observation file: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004-nat-t-observation.json`
- environment contract: `example-rpdb`
- execution plan: `build/pre-live-readiness/vpn-customer-stage1-15-cust-0004/execution-plan.json`
- status: `dry_run_ready`
- selected head-end family: `nat`
- dynamic NAT-T promotion: `planned`
- live apply: `false`
- errors: none

## Customer 3 Protection

The `example-rpdb` environment blocks these customers by policy:

- `legacy-cust0003`
- `vpn-customer-stage1-15-cust-0003`

No Customer 3 request was executed or modified during this gate.

## Artifact Integrity Results

Both customer bundles passed bundle validation:

- Customer 2 bundle validation: `valid`
- Customer 4 bundle validation: `valid`
- Customer 2 checksum entries: `21`, checksum errors: `0`
- Customer 4 checksum entries: `21`, checksum errors: `0`
- generated artifact `iptables-restore` matches: `0`
- generated artifact `MUXER3` matches: `0`

Head-end post-IPsec NAT activation metadata:

| Customer | Activation Backend | Apply Units | Rollback Units | Fallback Policy |
| --- | --- | ---: | ---: | --- |
| `legacy-cust0002` | `nftables` | `0` | `0` | `nftables_only`, legacy fallbacks disabled |
| `vpn-customer-stage1-15-cust-0004` | `nftables` | `2` | `1` | `nftables_only`, legacy fallbacks disabled |

## Staged Apply And Remove Results

The staged head-end root checks were local filesystem checks only.

| Customer | Staged Head-End Root | Apply | Validate | Remove | Remaining Files |
| --- | --- | --- | --- | --- | --- |
| `legacy-cust0002` | `build/pre-live-readiness/staged-headends/non_nat` | passed | passed | passed | none |
| `vpn-customer-stage1-15-cust-0004` | `build/pre-live-readiness/staged-headends/nat` | passed | passed | passed | none |

Validation details:

- Customer 2 staged validation backend: `nftables`
- Customer 2 staged validation apply units: `0`
- Customer 2 staged validation rollback units: `0`
- Customer 4 staged validation backend: `nftables`
- Customer 4 staged validation apply units: `2`
- Customer 4 staged validation rollback units: `1`

## Scale And Regression Results

Full repo verification:

- summary file: `build/repo-verification/repo-verification-summary.json`
- verified at: `2026-04-20T03:06:13Z`
- passed steps: `30`
- failed steps: `0`
- final step: `post_apply_auto_rollback_gate`

Explicit scale reports:

- `build/repo-verification/scale-gate-report-a.json`: `passed`
- `build/repo-verification/scale-gate-report-b.json`: `passed`
- missing targets: none
- evaluations per report: `24`
- failures per report: `0`

Measured `nat_t_netmap` at `20000` customers:

- activation backend: `nftables`
- active apply units: `40000`
- active rollback units: `20000`
- max active apply units per customer: `2`
- legacy comparison apply commands: `80000`
- legacy comparison rollback commands: `60000`

The legacy comparison counts are retained as measurement evidence only. They
are not the active apply path.

## Code Changes Made During This Gate

Two repo files were changed to close the Phase 3 artifact issue:

- `muxer/src/muxerlib/customer_artifacts.py`
- `scripts/packaging/validate_customer_bundle.py`

The generator now writes a neutral `fallback_policy` object into generated
post-IPsec NAT metadata instead of embedding forbidden fallback command names
inside customer artifacts.

The bundle validator now rejects generated bundles that contain the banned
runtime token `iptables-restore`.

## Stop Point

The repo-only pre-live gate is ready once these changes are committed and pushed.

The next gate is live-node readiness validation only. That future gate would
validate the RPDB muxer node, the RPDB non-NAT head-end nodes, the RPDB NAT-T
head-end nodes, datastore targets, artifact targets, backup baselines, package
installation paths, `nftables`, StrongSwan, and rollback paths.

Do not apply a customer until that live-node validation gate passes and a human
explicitly approves a customer apply.
