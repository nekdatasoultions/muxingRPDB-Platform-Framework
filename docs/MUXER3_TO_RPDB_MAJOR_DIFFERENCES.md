# MUXER3 To RPDB Major Differences

## Purpose

This document captures the major differences between the legacy `MUXER3`
codebase and the current RPDB codebase in this repository.

This is a high-value comparison, not a line-by-line diff.

The goal is to answer:

- what was carried forward
- what was extended
- what was fundamentally redesigned
- what those changes mean operationally

## Very Short Summary

The most important honest summary is this:

- the low-level Linux muxer runtime was mostly carried forward
- the biggest changes are around customer modeling, orchestration, validation,
  deployment safety, and customer-scoped operations
- RPDB is not just "MUXER3 with a few edits"
- RPDB is also not "totally unrelated code"

It is best understood as:

```text
MUXER3 runtime foundation
+ RPDB customer model
+ RPDB allocation and reservation model
+ RPDB packaging and deployment orchestration
+ RPDB platform lifecycle and validation gates
```

## What Stayed Broadly The Same

Before we talk about differences, it helps to be clear about what did not
change.

### The core muxer dataplane pattern stayed the same

Both codebases still center on the same Linux steering pattern:

```text
packet -> iptables mark -> ip rule -> customer route table -> customer tunnel -> head end
```

That means these ideas are still foundational in RPDB:

- packet classification with `iptables`
- fwmark-based policy routing
- customer-specific route tables
- customer-specific GRE or IPIP tunnels
- NAT rewrite where needed

Relevant RPDB code:

- [`muxer/runtime-package/src/muxerlib/cli.py`](../muxer/runtime-package/src/muxerlib/cli.py)
- [`muxer/runtime-package/src/muxerlib/core.py`](../muxer/runtime-package/src/muxerlib/core.py)
- [`muxer/runtime-package/src/muxerlib/modes.py`](../muxer/runtime-package/src/muxerlib/modes.py)
- [`muxer/runtime-package/src/muxerlib/dataplane.py`](../muxer/runtime-package/src/muxerlib/dataplane.py)

### The major runtime file layout stayed recognizable

`MUXER3` already had a modular muxer runtime with files such as:

- `cli.py`
- `core.py`
- `customers.py`
- `variables.py`
- `dynamodb_sot.py`
- `modes.py`
- `dataplane.py`
- `strongswan.py`

RPDB still uses that general layout, which is why the new runtime is familiar
to anyone who already understood the old one.

### Pass-through remained the main operating model

Both codebases still treat the muxer primarily as a steering system in front of
VPN head ends.

Termination mode still exists in the runtime, but the operational model in
RPDB is still centered on customer steering and head-end delivery.

## Major Difference 1: Customer Authoring Moved From One Shared Variables File To A Structured Multi-Stage Model

This is one of the biggest conceptual changes.

### MUXER3

`MUXER3` was centered on a shared customer authoring file:

- `customers.variables.yaml`

That file was the main authoring surface for customer definition and rendering.

### RPDB

RPDB splits the problem into multiple explicit stages:

- customer request
- normalized customer source
- merged customer module
- DynamoDB customer item
- allocation record
- deployment bundle

Relevant RPDB directories:

- [`muxer/config/customer-requests`](../muxer/config/customer-requests)
- [`muxer/config/customer-sources`](../muxer/config/customer-sources)
- [`muxer/config/schema/customer-request.schema.json`](../muxer/config/schema/customer-request.schema.json)
- [`muxer/config/schema/customer-source.schema.json`](../muxer/config/schema/customer-source.schema.json)
- [`muxer/config/schema/customer-ddb-item.schema.json`](../muxer/config/schema/customer-ddb-item.schema.json)

### Why this matters

This change makes the new system:

- easier to validate
- easier to reason about
- easier to review
- safer for automation

In `MUXER3`, the authoring layer and the rendered/runtime layer were much more
tightly coupled.

In RPDB, they are intentionally separated.

## Major Difference 2: RPDB Added An Explicit Allocation And Reservation Model

### MUXER3

In `MUXER3`, transport values were usually derived from the customer id or
supplied directly in the customer definition.

That worked, but it did not create a strong independent reservation model for
all platform-owned resources.

### RPDB

RPDB treats platform-owned values as things that should be assigned and tracked.

Examples:

- customer id
- fwmark
- route table
- RPDB priority
- tunnel key
- overlay block
- backend assignment

Relevant RPDB references:

- [`muxer/config/allocation-pools/defaults.yaml`](../muxer/config/allocation-pools/defaults.yaml)
- [`muxer/config/schema/customer-source.schema.json`](../muxer/config/schema/customer-source.schema.json)
- [`docs/RPDB_CUSTOMER_FILE_TO_DEPLOY_FULL_PROJECT_PLAN.md`](./RPDB_CUSTOMER_FILE_TO_DEPLOY_FULL_PROJECT_PLAN.md)

### Why this matters

This is what makes the new model scale more safely.

Instead of treating marks, tables, and overlay values as loose side effects of
rendering, RPDB treats them as managed platform resources.

## Major Difference 3: RPDB Added Customer-Scoped Operations Instead Of Staying Mostly Fleet-Oriented

### MUXER3

The legacy runtime surface was smaller and more fleet-oriented.

The CLI was centered on commands like:

- `apply`
- `flush`
- `show`
- `render-ipsec`

### RPDB

RPDB added explicit customer-scoped runtime commands:

- `show-customer`
- `apply-customer`
- `remove-customer`

Relevant RPDB runtime entrypoint:

- [`muxer/runtime-package/src/muxerlib/cli.py`](../muxer/runtime-package/src/muxerlib/cli.py)

### Why this matters

This is a major operational improvement.

It means the default operator flow can be:

- change one customer
- validate one customer
- apply one customer
- remove one customer

instead of treating every normal onboarding event like a fleet-wide render or
fleet-wide apply.

## Major Difference 4: RPDB Added Explicit RPDB Priority Handling

### MUXER3

The old code added policy rules, but the design did not center on explicit
priority management.

### RPDB

RPDB added explicit `rpdb_priority` handling in the runtime and cleanup paths.

Relevant RPDB runtime code:

- [`muxer/runtime-package/src/muxerlib/modes.py`](../muxer/runtime-package/src/muxerlib/modes.py)
- [`muxer/runtime-package/src/muxerlib/core.py`](../muxer/runtime-package/src/muxerlib/core.py)

### Why this matters

Explicit RPDB priorities are safer than relying on kernel-assigned or
implicitly-ordered behavior.

At scale, priority ambiguity becomes an operational risk.

## Major Difference 5: RPDB Fixed A Major Return-Path Weakness By Tracking Head-End Egress Source IPs

This is one of the most important practical runtime changes.

### MUXER3

In `MUXER3`, SNAT behavior on the reply path was largely centered on the single
customer backend underlay IP.

In practice that means the code assumed the head-end reply source was basically:

```text
cust_backend_ul
```

### RPDB

RPDB now tracks a list of valid head-end egress source IPs per customer and
uses that set when generating SNAT rules.

Relevant RPDB code:

- [`muxer/runtime-package/src/muxerlib/customers.py`](../muxer/runtime-package/src/muxerlib/customers.py)
- [`muxer/runtime-package/src/muxerlib/variables.py`](../muxer/runtime-package/src/muxerlib/variables.py)
- [`muxer/runtime-package/src/muxerlib/modes.py`](../muxer/runtime-package/src/muxerlib/modes.py)

### Why this matters

This change is directly tied to one-way traffic risk.

When reply traffic can originate from more than one valid head-end source,
assuming only one source IP is not good enough.

RPDB improves this by modeling the real source set instead of hard-coding one
reply origin assumption.

## Major Difference 6: RPDB Added A Full Customer Request And Validation Layer

### MUXER3

`MUXER3` had customer rendering and some validation, but it did not have the
same depth of formal schema-driven request handling.

### RPDB

RPDB introduced explicit schema validation for:

- customer request files
- customer source files
- customer DynamoDB items
- deployment environments
- NAT-T observations
- environment bindings

Relevant RPDB schema files:

- [`muxer/config/schema/customer-request.schema.json`](../muxer/config/schema/customer-request.schema.json)
- [`muxer/config/schema/customer-source.schema.json`](../muxer/config/schema/customer-source.schema.json)
- [`muxer/config/schema/customer-ddb-item.schema.json`](../muxer/config/schema/customer-ddb-item.schema.json)
- [`muxer/config/schema/deployment-environment.schema.json`](../muxer/config/schema/deployment-environment.schema.json)
- [`muxer/config/schema/dynamic-nat-t-observation.schema.json`](../muxer/config/schema/dynamic-nat-t-observation.schema.json)
- [`muxer/config/schema/environment-bindings.schema.json`](../muxer/config/schema/environment-bindings.schema.json)

### Why this matters

This is what makes one-file onboarding and automation credible.

A system is much easier to automate safely when the inputs have strict shape and
validation.

## Major Difference 7: RPDB Added Dynamic NAT-T Promotion As A Designed Workflow

### MUXER3

`MUXER3` supported strict and NAT-capable customer behaviors, but the operator
workflow was still much more centered on authoring the customer with the needed
shape.

### RPDB

RPDB is designed around:

- default non-NAT intake
- observation of actual NAT-T behavior
- promotion to NAT handling when UDP/4500 is observed

Relevant RPDB references:

- [`muxer/config/customer-requests/examples/example-dynamic-default-nonnat.yaml`](../muxer/config/customer-requests/examples/example-dynamic-default-nonnat.yaml)
- [`muxer/config/schema/dynamic-nat-t-observation.schema.json`](../muxer/config/schema/dynamic-nat-t-observation.schema.json)
- [`docs/RPDB_DYNAMIC_NAT_T_PROVISIONING_PLAN.md`](./RPDB_DYNAMIC_NAT_T_PROVISIONING_PLAN.md)
- [`scripts/customers/deploy_customer.py`](../scripts/customers/deploy_customer.py)

### Why this matters

This is a workflow difference, not just a code difference.

The operator should not have to manually decide the final stack in normal
cases. The system should learn from the observed customer behavior.

## Major Difference 8: RPDB Added A Real Customer Deployment Orchestrator

### MUXER3

`MUXER3` had rendering tools, sync tools, and operational scripts, but it did
not provide the same fully-shaped one-command customer deploy orchestration
model.

### RPDB

RPDB added a real customer deploy entrypoint with:

- environment validation
- blocked-customer enforcement
- target resolution
- dry-run planning
- touch plans
- approval-gated live apply
- execution-plan output

Relevant RPDB file:

- [`scripts/customers/deploy_customer.py`](../scripts/customers/deploy_customer.py)

### Why this matters

This is one of the clearest differences between the codebases.

`MUXER3` was stronger as a runtime-and-render repo.

RPDB is trying to be a full framework for:

- authoring
- allocation
- packaging
- validation
- deployment
- rollback

## Major Difference 9: RPDB Added Deployment Environments As A First-Class Model

### MUXER3

The old code was much more tied to the current operating environment and its
known runtime values.

### RPDB

RPDB added explicit deployment environment documents describing:

- muxer target
- NAT head-end targets
- non-NAT head-end targets
- data stores
- artifacts
- backups
- access methods
- live apply policy

Relevant RPDB references:

- [`muxer/config/deployment-environments`](../muxer/config/deployment-environments)
- [`muxer/config/schema/deployment-environment.schema.json`](../muxer/config/schema/deployment-environment.schema.json)
- [`scripts/customers/validate_deployment_environment.py`](../scripts/customers/validate_deployment_environment.py)

### Why this matters

This is what allows the same framework to target:

- example environments
- staged environments
- empty RPDB environments
- future production environments

without hard-coding every operational target into the runtime logic.

## Major Difference 10: RPDB Added Backup Gates, Dry-Run Gates, And Structured Review Artifacts

### MUXER3

The legacy codebase had useful tools and operational docs, but the code itself
was not centered on a formal review gate that always produced a structured
execution plan before apply.

### RPDB

RPDB added:

- bundle manifests
- readiness checks
- backup baseline checks
- rollout note generation
- double verification
- dry-run execution plans

Relevant RPDB references:

- [`scripts/backup/verify_backup_baseline.py`](../scripts/backup/verify_backup_baseline.py)
- [`scripts/packaging/validate_customer_bundle.py`](../scripts/packaging/validate_customer_bundle.py)
- [`scripts/deployment/deployment_readiness_check.py`](../scripts/deployment/deployment_readiness_check.py)
- [`scripts/deployment/run_double_verification.py`](../scripts/deployment/run_double_verification.py)
- [`docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md`](./PRE_DEPLOY_DOUBLE_VERIFICATION.md)

### Why this matters

This is a big operational maturity jump.

The RPDB model is much more explicit about:

- proving what will be touched
- proving what artifacts exist
- proving what backups exist
- proving what rollback expectations are

before live work happens.

## Major Difference 11: RPDB Added Customer-Scoped Apply, Validate, And Remove For Muxer, Head End, And Backend

### MUXER3

`MUXER3` had render and doctor-style tooling, and it generated per-customer
artifacts, but the apply path was not shaped the same way around customer-scoped
install and rollback helpers for each platform surface.

### RPDB

RPDB added customer-scoped deployment helpers for:

- backend
- muxer
- head end

Relevant RPDB references:

- [`scripts/deployment/apply_backend_customer.py`](../scripts/deployment/apply_backend_customer.py)
- [`scripts/deployment/validate_backend_customer.py`](../scripts/deployment/validate_backend_customer.py)
- [`scripts/deployment/remove_backend_customer.py`](../scripts/deployment/remove_backend_customer.py)
- [`scripts/deployment/apply_muxer_customer.py`](../scripts/deployment/apply_muxer_customer.py)
- [`scripts/deployment/validate_muxer_customer.py`](../scripts/deployment/validate_muxer_customer.py)
- [`scripts/deployment/remove_muxer_customer.py`](../scripts/deployment/remove_muxer_customer.py)
- [`scripts/deployment/apply_headend_customer.py`](../scripts/deployment/apply_headend_customer.py)
- [`scripts/deployment/validate_headend_customer.py`](../scripts/deployment/validate_headend_customer.py)
- [`scripts/deployment/remove_headend_customer.py`](../scripts/deployment/remove_headend_customer.py)

### Why this matters

This is a huge difference in operational shape.

RPDB is intentionally trying to make:

- apply one customer
- validate one customer
- remove one customer

the default way of working.

## Major Difference 12: RPDB Added Platform Lifecycle Code That MUXER3 Did Not Have In The Same Form

### MUXER3

The legacy repo had install and packaging scripts, but it was not built around a
clean empty-platform lifecycle with environment-safe parameter preparation,
wrapper-based deploy, and readiness verification.

### RPDB

RPDB added first-class platform lifecycle tooling for:

- preparing a safe empty platform
- deploying muxer and head-end stacks
- ensuring DynamoDB tables
- verifying empty-platform readiness
- verifying head-end bootstrap

Relevant RPDB references:

- [`scripts/platform/prepare_empty_platform_params.py`](../scripts/platform/prepare_empty_platform_params.py)
- [`scripts/platform/deploy_empty_platform.py`](../scripts/platform/deploy_empty_platform.py)
- [`scripts/platform/ensure_dynamodb_tables.py`](../scripts/platform/ensure_dynamodb_tables.py)
- [`scripts/platform/verify_empty_platform_readiness.py`](../scripts/platform/verify_empty_platform_readiness.py)
- [`scripts/platform/verify_headend_bootstrap.py`](../scripts/platform/verify_headend_bootstrap.py)
- [`docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md`](./FRESH_EMPTY_PLATFORM_RUNBOOK.md)

### Why this matters

This is why RPDB can behave like a platform framework, not just a runtime repo.

## Major Difference 13: RPDB Added Richer Post-IPsec NAT Service Intent Modeling

### MUXER3

The old repo had post-IPsec NAT rendering outputs, but the customer model was
not centered on the newer request-and-intent structure now used in RPDB.

### RPDB

RPDB models post-IPsec NAT as explicit service intent, including support for:

- translated subnets
- real subnets
- core subnets
- output marks
- MSS clamp behavior
- NETMAP-style translation
- explicit host mapping paths

Relevant RPDB references:

- [`muxer/config/customer-requests/examples/example-service-intent-netmap.yaml`](../muxer/config/customer-requests/examples/example-service-intent-netmap.yaml)
- [`muxer/config/customer-requests/examples/example-service-intent-explicit-host-map.yaml`](../muxer/config/customer-requests/examples/example-service-intent-explicit-host-map.yaml)
- [`muxer/runtime-package/src/muxerlib/dataplane.py`](../muxer/runtime-package/src/muxerlib/dataplane.py)

### Why this matters

This gives the new platform a cleaner place to express customer translation
intent without burying the logic inside ad hoc render-only side effects.

## Major Difference 14: RPDB Introduced Environment Defaults And Bindings As A Formal Layer

### MUXER3

`MUXER3` had more direct runtime configuration and render flow assumptions tied
to the known operating environment.

### RPDB

RPDB added explicit environment defaults and bindings.

Relevant RPDB references:

- [`muxer/config/environment-defaults`](../muxer/config/environment-defaults)
- [`muxer/config/schema/environment-bindings.schema.json`](../muxer/config/schema/environment-bindings.schema.json)

### Why this matters

This makes it easier to separate:

- customer intent
- platform assignment
- environment-specific rendering inputs

which is important when the same framework needs to support more than one
environment shape.

## Major Difference 15: RPDB Moved Away From The Old "Per-Customer Libreswan Termination Unit" Direction

This is more of an architectural intent difference than a low-level runtime
difference.

### MUXER3

The legacy `MUXER3` README described the project as:

- muxer plus per-customer Libreswan termination units
- container or namespace isolation as the next step

### RPDB

RPDB is currently centered on:

- muxer steering
- NAT and non-NAT head-end families
- customer-scoped artifact install onto those head ends

Relevant RPDB references:

- [`docs/HEADEND_CUSTOMER_ORCHESTRATION.md`](./HEADEND_CUSTOMER_ORCHESTRATION.md)
- [`docs/DEPLOYMENT_MODEL.md`](./DEPLOYMENT_MODEL.md)
- [`docs/RPDB_TARGET_ARCHITECTURE.md`](./RPDB_TARGET_ARCHITECTURE.md)

### Why this matters

This is a meaningful shift in platform direction.

RPDB is not trying to finish the exact same per-customer-container termination
path described in the old `MUXER3` intent docs. It is building a cleaner
customer-scoped framework around shared head-end roles.

## Major Difference 16: RPDB Added A Much Larger Operational Documentation Surface

### MUXER3

The old repo had useful docs, but they were more centered on the current
solution, muxer operation, testing, and architecture direction.

### RPDB

RPDB now carries a much larger documentation layer for:

- onboarding
- deployment
- dry-run review
- project planning
- platform deploy
- double verification
- dynamic NAT-T
- rollback expectations

Examples:

- [`docs/CUSTOMER_ONBOARDING_USER_GUIDE.md`](./CUSTOMER_ONBOARDING_USER_GUIDE.md)
- [`docs/CUSTOMER_ONBOARDING_RUNBOOK.md`](./CUSTOMER_ONBOARDING_RUNBOOK.md)
- [`docs/FRESH_EMPTY_PLATFORM_RUNBOOK.md`](./FRESH_EMPTY_PLATFORM_RUNBOOK.md)
- [`docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md`](./PRE_DEPLOY_DOUBLE_VERIFICATION.md)
- [`docs/MUXER_GUIDE.md`](./MUXER_GUIDE.md)

### Why this matters

The new repo is trying to be teachable and operationally repeatable, not just
technically functional.

## Major Difference 17: RPDB Added `nftables` Preparation Work

### MUXER3

The old muxer runtime did not include an `nftables.py` module.

### RPDB

RPDB now includes:

- [`muxer/runtime-package/src/muxerlib/nftables.py`](../muxer/runtime-package/src/muxerlib/nftables.py)

### Why this matters

Even if `iptables` remains the active operational path today, this reflects a
forward-looking attempt to move beyond large linear rule sets over time.

That lines up with the architecture goal of improving scale behavior.

## What Changed Least

The following areas changed less than people might assume:

- the basic Linux steering model
- the pass-through routing concept
- the importance of `iptables` marks
- the need for per-customer tunnels
- the general modular runtime file layout

This is useful because it means:

- old muxer troubleshooting knowledge still has value
- packet-path reasoning skills transfer well
- the new system can still be learned incrementally

## What Changed Most

The biggest changes are not the tunnel primitives themselves.

The biggest changes are:

1. how customers are modeled
2. how customers are allocated
3. how customer intent is validated
4. how one customer is packaged
5. how one customer is reviewed
6. how one customer is applied
7. how the whole base platform is deployed and verified

That is the real shift from `MUXER3` to RPDB.

## Operator Impact

From an operator point of view, the move is roughly:

### MUXER3 mindset

- edit shared customer definitions
- render outputs
- apply or troubleshoot on the muxer
- use supporting scripts around the current platform

### RPDB mindset

- create one customer request
- let the platform assign the reusable network resources
- validate the request and generated artifacts
- review a customer-scoped execution plan
- apply one customer through an orchestrated path
- validate and rollback in a structured way if needed

## Engineering Impact

From an engineering point of view, the move is roughly:

### MUXER3

- stronger as a runtime-and-render repo
- still partially tied to current-solution assumptions
- less formal around environment contracts and full deployment orchestration

### RPDB

- stronger as a framework and platform repo
- more formal around schemas and staged transformations
- more formal around target selection and deploy gates
- more formal around customer-scoped lifecycle operations

## Final Takeaway

The most honest final takeaway is:

- RPDB did not throw away the useful parts of `MUXER3`
- RPDB also did not stop at "copy the runtime and keep operating the same way"

The true difference is that RPDB takes the old muxer runtime ideas and wraps
them in a much more explicit framework for:

- customer input
- allocation
- validation
- packaging
- deployment
- rollback
- platform lifecycle

So if someone asks:

```text
What is the biggest difference from MUXER3 to RPDB?
```

the best short answer is:

```text
The packet-steering core is familiar, but the customer model and operational model are much more structured, customer-scoped, and automation-ready.
```
