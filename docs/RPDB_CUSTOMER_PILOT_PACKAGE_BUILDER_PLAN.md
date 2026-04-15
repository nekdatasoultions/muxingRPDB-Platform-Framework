# RPDB Customer Pilot Package Builder Plan

## Boundary

This plan is RPDB-only.

Allowed workspace:

- `E:\Code1\muxingRPDB Platform Framework-main`

Not allowed in this plan:

- changes to `E:\Code1\MUXER3`
- changes to legacy MUXER3 GitHub repositories
- live node changes
- production DynamoDB writes
- live muxer apply
- live VPN head-end apply
- customer cutover

## Goal

Build one command that prepares a complete repo-only pilot review package from
one customer request YAML.

The package must make the customer ready for human review before any live
deployment decision.

The command should support:

- normal NAT customers
- normal strict non-NAT customers
- dynamic default non-NAT customers
- dynamic NAT-T promotion packages when a reviewed UDP/4500 observation exists

## Package Contract

Each pilot package should produce a deterministic review folder containing:

- `customer-source.yaml`
- `customer-module.json`
- `customer-ddb-item.json`
- `allocation-summary.json`
- `allocation-ddb-items.json`
- `rendered/`
- `handoff/`
- `bound/`
- `bundle/`
- `bundle-validation.json`
- `double-verification.json`
- `pilot-readiness.json`
- `README.md`

Validation:

- package paths are repo-local and deterministic
- no live-node target exists in the package contract
- no production database write target exists in the package contract
- every required artifact is either present or the readiness report marks the
  package blocked

## Stage 1: Define Package Contract

Document the review folder layout and required artifact names.

The contract should explain:

- what each artifact is
- which artifact is operator-facing
- which artifact is machine-readable
- which artifact is review-only
- which artifacts would later feed a separately approved live deployment

Validation:

- package contract exists in repo docs
- package contract does not include live apply behavior
- package contract is usable for NAT, strict non-NAT, and dynamic NAT-T paths

## Stage 2: Add Pilot Builder Orchestration Script

Add:

- `muxer/scripts/prepare_customer_pilot.py`

Inputs:

- customer request YAML
- output directory
- environment binding file
- existing source roots
- optional NAT-T observation event
- optional customer replacement name for promotion planning

Behavior:

- validate the customer request
- provision the customer request
- render customer artifacts
- export the framework handoff
- bind environment placeholders
- assemble the customer bundle
- validate the customer bundle
- run staged double verification
- write a readiness report
- write a human-readable package README

Validation:

- script compiles
- script refuses any live apply behavior
- script writes all required package artifacts
- script exits non-zero if required artifacts are missing
- script writes `live_apply: false` in the readiness report

## Stage 3: Support Dynamic NAT-T Path

If no observation event is provided:

- package the normal initial request

If a NAT-T observation event is provided:

- call the audited dynamic NAT-T observation workflow first
- package the promoted NAT-T source as the pilot candidate
- include the NAT-T observation audit artifacts in the review folder

Validation:

- initial dynamic non-NAT request packages from non-NAT pools
- observed UDP/4500 path packages the promoted customer from NAT pools
- duplicate observation remains idempotent
- readiness report includes the NAT-T audit path
- readiness report says `live_apply: false`

## Stage 4: Add Readiness Report

Generate:

- `pilot-readiness.json`

The report should include:

- customer name
- customer class
- backend cluster
- peer IP
- local selectors
- remote selectors
- allocated fwmark
- allocated route table
- allocated RPDB priority
- allocated tunnel key
- allocated interface name
- allocated overlay block
- NAT-T promotion status when applicable
- bundle validation status
- double-verification status
- live gate status
- rollback checklist status

Validation:

- report is machine-readable JSON
- report clearly says `ready_for_review` or `blocked`
- report always says no live apply occurred
- report includes enough information to compare muxer, database, head-end, and
  rollback expectations before approval

## Stage 5: Add Human Package README

Generate:

- `README.md`

The README should explain:

- what this package is
- what customer request produced it
- which customer class was packaged
- which backend stack was selected
- whether dynamic NAT-T promotion was used
- what was generated
- what the operator must review
- what is not done yet
- the exact stop gate before live work

Validation:

- README is readable by an operator
- README names the important package artifacts
- README explicitly says not to apply live without separate approval
- README does not include secrets

## Stage 6: Extend Repo Verification

Add the pilot builder to:

- `muxer/scripts/run_repo_verification.py`

Verify:

- normal strict non-NAT pilot package
- normal NAT pilot package
- dynamic NAT-T promoted pilot package

Validation:

- full repo verification passes
- existing provisioning checks still pass
- existing allocation collision checks still pass
- existing runtime staged-load checks still pass
- existing nftables render checks still pass
- existing head-end staged apply/remove checks still pass
- dynamic NAT-T idempotency still passes

## Stage 7: Update Documentation

Update:

- `docs/CUSTOMER_ONBOARDING_RUNBOOK.md`
- `docs/CUSTOMER_ONBOARDING_USER_GUIDE.md`
- `muxer/scripts/README.md`
- `muxer/docs/DYNAMIC_NAT_T_PROVISIONING.md`

Documentation should show the pilot builder as the primary repo-only command.

Lower-level commands should remain documented as advanced/debug commands.

Validation:

- docs show the one-command pilot package path
- docs preserve the no-live-work gate
- docs explain where to find the generated package
- docs explain what must be reviewed before live work

## Stage 8: Final Verification, Commit, And Push

Run:

- `python -m py_compile` for new and changed Python scripts
- pilot-builder smoke tests
- `python muxer\scripts\run_repo_verification.py --json`
- `git diff --check`
- `git status --short --branch`

If validation passes:

- commit RPDB-only changes
- push to `origin/main`
- confirm `HEAD == origin/main`
- confirm working tree is clean

Validation:

- repo verification passes
- GitHub is updated
- local branch matches `origin/main`
- all changed paths are inside `E:\Code1\muxingRPDB Platform Framework-main`

## Definition Of Done

This plan is complete when:

- one command can generate a full repo-only pilot review package
- the package includes muxer artifacts
- the package includes DynamoDB customer item view
- the package includes allocation reservation item views
- the package includes head-end artifacts
- the package includes bundle validation
- the package includes double verification
- the package includes readiness and rollback-review artifacts
- dynamic NAT-T promotion can be included through the audited observation flow
- full repo verification passes
- the implementation is committed and pushed
- no live systems were touched
