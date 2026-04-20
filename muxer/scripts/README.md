# Scripts

This directory holds the early customer-scoped workflow commands.

Current scaffold helpers:

- `provision_customer_end_to_end.py`
  - operator-facing single entrypoint for repo-only customer provisioning
  - takes one customer request file and writes the complete provisioning
    package, readiness report, bundle, and double-verification artifacts
  - accepts an optional NAT-T observation file to run the audited promotion
    workflow before packaging
- `watch_nat_t_logs.py`
  - watches muxer JSONL or iptables-style logs for UDP/500 then UDP/4500
  - correlates observed peers to dynamic customer requests
  - writes idempotent NAT-T observation files
  - can call the one-file provisioning entrypoint automatically
- `validate_customer_request.py`
  - validates a minimal customer provisioning request
  - reports the effective customer class and allocation pool
- `validate_customer_allocations.py`
  - scans full customer source files
  - verifies exclusive namespace uniqueness
- `provision_customer_request.py`
  - expands a minimal provisioning request into a fully allocated compatibility
    customer source
  - emits allocation summaries and exclusive allocation DDB item views
  - supports reviewed same-customer replacement planning with
    `--replace-customer`
- `plan_nat_t_promotion.py`
  - creates a repo-only NAT-T promotion request when a dynamic strict non-NAT
    customer is later observed on UDP/4500
  - writes a promotion summary without touching live nodes or DynamoDB
- `process_nat_t_observation.py`
  - consumes a repo-only UDP/4500 observation event
  - stages the promoted NAT-T request, allocated source, module, DynamoDB item
    view, allocation views, promotion summary, and audit record
  - is idempotent for repeat observations of the same customer, peer,
    protocol, and destination port
- `prepare_customer_pilot.py`
  - prepares a complete repo-only pilot review package from one customer
    request
  - writes the allocated source, module, DynamoDB item view, allocation item
    views, rendered artifacts, handoff, bound bundle, validation reports,
    readiness report, and package README
  - can include the audited dynamic NAT-T observation flow before packaging
- `validate_customer_source.py`
  - validates a single customer source file
  - loads defaults and class overrides
  - assembles a merged customer module
- `build_customer_item.py`
  - builds a merged customer module
  - emits the DynamoDB item shape for one customer
- `render_customer_artifacts.py`
  - renders customer-scoped muxer and head-end artifact trees
  - writes structured files under `muxer/` and `headend/`
  - includes both JSON intent files and concrete command/config fragments
- `validate_rendered_artifacts.py`
  - validates a rendered customer artifact tree
  - checks `render-manifest.json` and the expected structured files
- `bind_rendered_artifacts.py`
  - binds rendered artifacts or handoff exports to environment-specific values
  - writes `binding-report.json`
- `validate_environment_bindings.py`
  - validates the environment bindings YAML against the schema
- `validate_bound_artifacts.py`
  - verifies a bound artifact tree no longer contains unresolved placeholders
- `export_customer_handoff.py`
  - exports one standard framework-side handoff directory
  - writes `customer-module.json` and `customer-ddb-item.json`
  - copies the source YAML
  - generates muxer and head-end intent artifacts by default
  - optionally copies muxer and head-end customer artifact directories
- `run_repo_verification.py`
  - runs the repo-only completion proof
  - verifies provisioning, allocation tracking, customer-scoped runtime
    behavior, termination guards, strict DynamoDB customer lookup boundaries,
    the live pass-through `nftables` classification backend, and the synthetic
    scale baseline harness
- `run_scale_baseline.py`
  - generates synthetic strict non-NAT, NAT-T, translated NAT-T, and mixed
    customer scenarios plus bridge-focused profiles
  - records rule growth, command growth, classification backend, batched
    `nftables` model size, apply/remove/rollback plan timing, CPU time, and
    peak memory for 100, 1k, 5k, 10k, and 20k customer counts
  - writes a repo-only scale baseline artifact without touching AWS or live
    nodes
- `generate_scale_report.py`
  - evaluates one scale harness summary against
    `muxer/config/scale-thresholds.json`
  - writes machine-checked JSON and Markdown pass/fail reports
  - is allowed to report `failed` so the repo can record an honest no-go state
    without interpretation drift

Current proof artifact:

- `build/repo-verification/repo-verification-summary.json`

Current scale baseline artifact:

- `build/scale-baseline/scale-baseline-summary.json`

Current explicit scale gate artifacts:

- `build/scale-baseline/phase7-metrics.json`
- `build/scale-baseline/phase7-report.json`
- `build/scale-baseline/phase7-report.md`
