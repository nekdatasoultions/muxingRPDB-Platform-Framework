# Framework Lane

This lane holds framework-owned assets:

- reusable CGNAT design documents
- framework-level config shapes
- local bundle/validation/render tooling
- framework source code

Use this lane for work that should remain portable across AWS environments.

The current rule for this lane is that CGNAT remains net new and does not edit
muxer-owned code or schemas.

Current orchestration entry point:

- `scripts/prepare_scenario1.py`
  - validates the bundle
  - renders framework artifacts
  - renders AWS package artifacts
  - builds the AWS plan in plan mode only
  - renders server package and server config artifacts
  - prepares per-host apply bundles
  - optionally runs a live AWS preflight against the rendered AWS package
  - optionally prepares a no-execution remote apply plan when host access data is supplied
  - does not deploy infrastructure
- `scripts/prepare_scenario1_predeploy_review.py`
  - assembles a pre-deploy review package from the generated prep and AWS
    dry-run artifacts
  - highlights open operator items before host apply
  - does not deploy infrastructure
- `scripts/prepare_scenario1_backend_integration.py`
  - generates a backend-native customer request from the CGNAT bundle
  - runs the existing `deploy_customer` flow in dry-run mode
  - produces a reusable backend integration summary without touching shared code
- `scripts/prepare_scenario1_deployment_stage_review.py`
  - combines the CGNAT predeploy review and backend integration dry-run into a
    single deployment-stage review package
  - does not deploy infrastructure

Useful references in this lane:

- [Project Plan](./docs/PROJECT_PLAN.md)
- [Scenario 1 Project Plan](./docs/SCENARIO1_PROJECT_PLAN.md)
- [Field Boundaries](./docs/FIELD_BOUNDARIES.md)
- [Backend Contract Map](./docs/SHARED_INTEGRATION_MAP.md)
- [Framework Config Example](./config/framework.example.json)
- [Deployment Bundle Example](./config/deployment-bundle.example.json)
- `config/deployment-bundle.rpdb-empty-live.json`
- `config/scenario1-backend-integration.rpdb-empty-live.json`
