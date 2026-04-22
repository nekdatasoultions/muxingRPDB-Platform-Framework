# RPDB Automatic NAT-T Promotion Project Plan

## Purpose

This plan fixes the gap between NAT-T detection and NAT-T deployment.

The target operator experience is:

```bash
python3 scripts/customers/deploy_customer.py \
  --customer-file muxer/config/customer-requests/migrated/$CUSTOMER.yaml \
  --environment rpdb-empty-live \
  --approve \
  --json
```

The operator does not choose NAT-T or non-NAT. The customer starts on the
strict non-NAT path. If RPDB later observes that the peer is using UDP/4500,
the platform promotes that customer to the NAT-T head-end path automatically.

## Core Requirements

- The automation must work for any eligible customer request, including future
  customers not known when this code was written.
- No customer name, peer IP, tunnel key, mark, route table, RPDB priority, or
  head-end target may be hard-coded into the watcher or promotion logic.
- Customer-specific behavior must come from the customer request, SoT state,
  deployment environment contract, and observed packet events.
- MUXER3 must not be modified.
- Runtime and generated packet-handling artifacts must remain nftables-only.
- Customer 2 and Customer 4 are validation examples only, never production
  special cases.

## Current Gap

The muxer-side listener writes UDP/500 and UDP/4500 observations to the muxer
event log. The control-plane watcher can consume those events when run by hand,
but it was not wired as an always-on control-plane process.

There is also a promotion conflict when the same customer already exists as
strict non-NAT and the NAT-T package tries to write the same customer as NAT.
The currently safe strategy is controlled remove-and-reapply by the automation:

1. Resolve the existing customer from SoT.
2. Remove only that customer from the current muxer/head-end/backend path.
3. Apply the NAT-T package generated from the observation.

This is the same successful sequence used manually, but moved into the
customer-agnostic watcher workflow.

## Phase 1: Repo State Gate

Actions:

- Keep all changes inside this repo.
- Confirm no MUXER3 paths are touched.
- Keep dynamic-routing implementation separate from this NAT-T repair.
- Add this plan and link it from the docs index.

Validation:

- `git diff --name-only` shows only RPDB repo paths.
- No file under `MUXER3` changes.
- The plan explicitly says no customer hard-coding.

## Phase 2: Watcher Policy Gate

Actions:

- Extend the deployment environment contract with NAT-T watcher automation
  policy.
- Add policy fields for enabled state, approval behavior, promotion strategy,
  log sync behavior, and unknown-customer behavior.
- Default promotion strategy to `remove_reapply` for approved automation.

Validation:

- Example environments validate against the schema.
- Live environment can express the same policy without changing customer YAML.
- Blocked customers still prevent promotion.

## Phase 3: Universal Customer Discovery Gate

Actions:

- Make the watcher discover eligible customers from the environment's
  `customer_requests.allowed_roots`.
- Keep explicit `--customer-request` and `--customer-request-root` overrides for
  one-off testing.
- Correlate events by observed peer IP and eligible customer request.

Validation:

- Watcher detects a customer from an allowed root without naming that customer
  in code.
- A peer shared by two eligible customer requests is rejected.
- Customer 3 variants stay blocked by environment policy.

## Phase 4: Controlled Promotion Gate

Actions:

- Add watcher-controlled `remove_reapply` promotion mode.
- Before applying a NAT-T package, the watcher plans the existing customer
  removal.
- If SoT says the customer is already NAT, the watcher skips duplicate apply.
- If SoT says the customer is strict non-NAT, the watcher removes that one
  customer and then applies the NAT-T package.
- If the customer is not yet present, the watcher can apply the NAT-T package
  directly when policy allows.

Validation:

- No manual `--observation` is required by an operator.
- No manual `remove_customer.py` step is required by an operator.
- Duplicate UDP/4500 observations do not duplicate allocations.
- The remove step is customer-scoped.

## Phase 5: Control-Plane Runner Gate

Actions:

- Add a control-plane runner that can sync the muxer listener log from the
  RPDB muxer target defined in the environment.
- The runner invokes the watcher with environment-derived roots, state, output,
  and package paths.
- Add a systemd service template for running the control-plane watcher.

Validation:

- Runner can operate in local/staged mode without AWS or live nodes.
- Runner can be configured for SSH sync using the RPDB muxer target.
- Service template does not contain customer-specific values.

## Phase 6: Repo Verification Gate

Actions:

- Extend repo verification to cover the automatic watcher path.
- Verify listener output, watcher detection, environment-root discovery,
  promotion planning, and idempotency.

Validation:

- Full repo verification passes.
- Verification proves the logic is customer-agnostic.
- Verification proves `iptables` is not reintroduced.

## Phase 7: Live Rollout Gate

This phase is not executed by this repo-only project block.

Before live rollout:

- Review generated artifacts.
- Confirm current Customer 4 and any pilot customer state.
- Install or update the control-plane watcher service only on the approved RPDB
  control/jump node.
- Confirm the muxer listener remains active on the RPDB muxer.
- Run watcher dry-run mode first.
- Only then enable approved promotion.

Validation:

- A normal customer apply starts strict non-NAT.
- Real UDP/4500 observation promotes the customer automatically.
- SOT, muxer, NAT head ends, non-NAT cleanup, IKE/CHILD SAs, and nftables-only
  runtime are verified after promotion.

## Definition Of Done

- One customer file and one initial deploy command are enough for onboarding.
- NAT-T promotion is automatic after observed UDP/4500.
- The watcher handles any eligible customer from configured roots.
- The operator does not pass `--observation`.
- The operator does not choose NAT-T or non-NAT.
- The operator does not manually remove and reapply during normal promotion.
- No MUXER3 files are modified.
- Full repo verification passes.

## Implemented Repo Artifacts

- Environment policy is modeled in
  `muxer/config/schema/deployment-environment.schema.json`.
- Live and example environments carry NAT-T watcher automation, promotion, and
  log-sync policy under `nat_t_watcher`.
- The watcher implementation lives in `muxer/scripts/watch_nat_t_logs.py`.
- The control-plane runner lives in `scripts/customers/run_nat_t_watcher.py`.
- The service template lives in
  `scripts/customers/systemd/rpdb-nat-t-watcher.service`.
- Repo verification covers listener output, watcher detection, environment-root
  discovery, staged orchestrator apply, idempotency, and the service template.

## Verified Status

Verified on April 22, 2026:

```text
python muxer/scripts/run_repo_verification.py
Repo verification completed: 40 step(s) passed
```
