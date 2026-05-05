# Code Cleanup Matrix 2026-05-05

This document classifies the codebase by what is currently:

1. actively used and regression-validated
2. active and still required, but only indirectly validated
3. retained as migration inventory or operator support
4. historical or current-state documentation that should not be treated as the source of truth

It is meant to help us clean the repo without deleting live or proven paths.

## Evidence used

- Regression entrypoints:
  - `CGNAT/tests/run_tests.py`
  - `CGNAT/tests/run_regression.py`
- Live state snapshot:
  - `CGNAT/framework/docs/CGNAT_LIVE_STATUS_2026-05-05.md`
- Repo verification and deployment wiring:
  - `muxer/scripts/run_repo_verification.py`
  - `scripts/customers/deploy_customer.py`
  - `scripts/platform/deploy_empty_platform.py`

## Bucket 1: Active And Regression-Validated

These paths are on the current provisioning and deployment spine and are covered by the current CGNAT regression or unit suites.

| Path | Why it is active | Evidence | Cleanup stance |
| --- | --- | --- | --- |
| `CGNAT/framework/src/cgnat/` | CGNAT packaging, PKI, provisioning, Scenario 1 and Scenario 2 logic | exercised by `CGNAT/tests/*` and `run_regression.py` | Keep |
| `CGNAT/framework/scripts/prepare_cgnat_customer_pilot.py` | repo-only CGNAT review and live-plan generation | exercised by regression review flows | Keep |
| `CGNAT/framework/scripts/prepare_scenario1_backend_integration.py` | Scenario 1 backend integration rendering | called by `CGNAT/tests/run_regression.py` | Keep |
| `CGNAT/framework/config/` | Scenario 1 and Scenario 2 backend integration profiles | consumed by framework tests and staging flows | Keep |
| `muxer/src/muxerlib/customer_model.py` | normalized customer model for RPDB provisioning | covered by provisioning tests and regression harness | Keep |
| `muxer/src/muxerlib/customer_artifacts.py` | customer artifact rendering | covered by regression and artifact tests | Keep |
| `muxer/src/muxerlib/allocation.py` | allocation pipeline for customer requests | covered by provisioning integration path | Keep |
| `muxer/src/muxerlib/cgnat_profile_overrides.py` | Scenario parity overrides such as `outside_nat.route_via` | direct unit test coverage in `test_cgnat_profile_overrides.py` | Keep |
| `muxer/scripts/provision_customer_request.py` | request-to-source allocation entrypoint | used by shared provisioning path | Keep |
| `muxer/scripts/prepare_customer_pilot.py` | main package build for backend/muxer/headend | used by `provision_customer_end_to_end.py` and regression | Keep |
| `muxer/scripts/provision_customer_end_to_end.py` | repo-only end-to-end provisioning entrypoint | called directly by regression | Keep |
| `muxer/scripts/render_customer_artifacts.py` | artifact renderer used by prepare flow | used by provisioning path and repo verification | Keep |
| `scripts/customers/deploy_customer.py` | shared dry-run and live apply front door | used by staged regression and live workflow | Keep |
| `scripts/customers/live_apply_lib.py` | approved-apply orchestration, live and staged behavior | direct tests plus staged regression | Keep |
| `scripts/customers/validate_deployment_environment.py` | deployment environment validation for target selection | used in deploy flows and regression | Keep |
| `scripts/deployment/` | backend, muxer, head-end, CGNAT apply/remove/validate modules | used by staged apply and rollback regression | Keep |

## Bucket 2: Active And Required, But Not Fully Proven By The Fast CGNAT Suite

These areas are still part of the platform and are referenced by current deploy or verification code, but they are not fully represented by the compact CGNAT regression harness alone.

| Path | Why it still matters | Evidence | Cleanup stance |
| --- | --- | --- | --- |
| `muxer/runtime-package/` | deployable muxer runtime payload consumed by platform packaging and live/runtime checks | referenced by `scripts/platform/deploy_empty_platform.py`, `scripts/customers/live_apply_lib.py`, `muxer/scripts/run_repo_verification.py` | Keep; do not delete yet |
| `scripts/platform/` | empty-platform deployment, CloudFormation packaging, bootstrap verification | actively references `infra/cfn` and `muxer/runtime-package` | Keep |
| `infra/cfn/` | actual CloudFormation templates and parameter files for platform deployment | used by `scripts/platform/cfn_*` and `deploy_empty_platform.py` | Keep |
| `muxer/scripts/run_repo_verification.py` | broad repo verification harness spanning legacy migration, runtime package, and deploy flow | references active RPDB files and runtime package | Keep; likely split later, not now |
| `muxer/scripts/run_scale_baseline.py` | runtime scale harness using `muxer/runtime-package` | active tool path even if not in the daily CGNAT test loop | Keep |
| `scripts/customers/live_backend_lib.py` and `live_access_lib.py` | shared live helpers under `deploy_customer.py` and `live_apply_lib.py` | imported by customer deploy stack | Keep |

## Bucket 3: Manual Migration Inventory And Operator Support

These files are not the current green CGNAT canary path, but they are not junk. They represent real migration inventory, examples, or manual runbooks we still need.

| Path | Why it exists | Evidence | Cleanup stance |
| --- | --- | --- | --- |
| `muxer/config/customer-requests/migrated/` | migrated customer request definitions still referenced by repo verification and migration docs | referenced by `muxer/scripts/run_repo_verification.py` and deployment environment examples | Keep, but label as migration inventory |
| `muxer/config/customer-sources/migrated/` | migrated source examples for live/manual migration examples | referenced by migration docs | Keep, but label as migration inventory |
| `docs/MANUAL_LINUX_CUSTOMER_PROVISIONING.md` | operator playbook for manual customer install and removal | still references migrated customers and nftables runtime | Keep; mark as manual lane |
| `muxer/docs/LIVE_CUSTOMER_MIGRATION_EXAMPLE.md` | manual migration guidance for legacy customer moves | explicitly tied to migrated customer artifacts | Keep; mark as migration playbook |
| `muxer/docs/LIVE_NAT_CUSTOMER_MIGRATION_EXAMPLE.md` | NAT customer migration reference | explicitly tied to migrated inventory | Keep; mark as migration playbook |

## Bucket 4: Historical Or Snapshot Docs

These are useful context, but they should not be treated as the current source of truth for `rpdb-empty-live` or the current CGNAT design.

| Path | Why it is not the current source of truth | Evidence | Cleanup stance |
| --- | --- | --- | --- |
| `docs/current-state/` | captures earlier dev/current-state snapshots and older node names | `HEADEND_RUNTIME_STATUS.md` is explicitly "as of 2026-04-03" and references non-`rpdb-empty` nodes | Keep, but clearly label as historical snapshot |
| `docs/current-state/HEADEND_RUNTIME_STATUS.md` | references older muxer/head-end fleet, not the current `rpdb-empty-live` keep set | cites `muxer-single-prod-node` and older `vpn-headend-*-dev-*` nodes | Do not use as current SoT |
| `muxer/runtime-package/docs/MUXER_END_TO_END_DEMO_RUNBOOK.md` | demonstrates older demo customers and legacy examples | references `legacy-cust0002` and `vpn-customer-stage1-15-*` | Keep as historical/operator reference |
| `docs/RPDB_TECHNICAL_DEMO_WALKTHROUGH.md` | still useful, but includes old migrated customers and mixed transitional examples | references migrated customer requests and earlier demo flows | Keep; do not treat as current implementation contract |

## Bucket 5: Generated Or Local Artifact Areas

These are not the primary source tree and should not drive design decisions.

| Path | Why it should not drive cleanup decisions | Evidence | Cleanup stance |
| --- | --- | --- | --- |
| `muxer_passthrough/` | ignored local/generated workspace for pass-through artifacts | ignored by `.gitignore`; repo references the nftables concept, not this top-level workspace | Safe to treat as local artifact workspace |
| `CGNAT/build/` | generated review, regression, and live-plan outputs | created by test and review scripts | Keep locally as needed; never treat as source |
| `backups/` outside repo | backup snapshots, not source | backup manifest created on `2026-05-05` | Keep external to repo; not code cleanup target |

## What This Means Operationally

### Safe to clean up first

1. Historical docs that need banner text such as "snapshot" or "not current SoT".
2. Manual migration docs that need clearer labeling so they are not confused with the new canary path.
3. Local/generated artifact workspaces that are not checked in.

### Do not clean up yet

1. `muxer/runtime-package/`
2. `scripts/platform/`
3. `infra/cfn/`
4. `muxer/scripts/run_repo_verification.py`
5. `muxer/config/customer-requests/migrated/`

These all still carry active or near-active behavior, even if parts of them feel old.

## Recommended Cleanup Order

1. **Documentation labeling pass**
   - mark snapshot docs as historical
   - mark migration docs as manual migration inventory
   - point current workflow docs at:
     - `CGNAT/framework/docs/CGNAT_LIVE_STATUS_2026-05-05.md`
     - `CGNAT/framework/docs/CUSTOMER_PROVISIONING_INTEGRATION_DESIGN.md`
     - `CGNAT/framework/docs/CUSTOMER_PROVISIONING_REGRESSION_GATES.md`

2. **Validation boundary pass**
   - keep the fast CGNAT suite as the green bar
   - decide whether `muxer/scripts/run_repo_verification.py` should be split into:
     - current RPDB checks
     - legacy migration checks
     - runtime-package checks

3. **Structural cleanup pass**
   - only after the validation split
   - consider whether `muxer/runtime-package/` remains a long-term runtime home or should later be consolidated

4. **Migration archive pass**
   - once manual customer migrations are complete
   - move migrated request/source examples and old runbooks into an explicitly archived area

## Short Version

The repo is not mostly random dead code. It is a mix of:

- a current validated RPDB plus CGNAT provisioning spine
- an active runtime/deploy spine that still depends on `muxer/runtime-package` and `infra/cfn`
- a migration inventory that is still intentionally present
- older snapshot docs that need clearer labeling

So the right cleanup strategy is:

**label first, split validation second, remove last.**
