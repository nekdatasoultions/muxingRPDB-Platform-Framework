# Scripts

This directory holds the early customer-scoped workflow commands.

Current scaffold helpers:

- `validate_customer_request.py`
  - validates a minimal customer provisioning request
  - checks customer class and backend cluster alignment
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
    behavior, termination guards, and nftables batch render

Current proof artifact:

- [repo-verification-summary.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/build/repo-verification/repo-verification-summary.json)
