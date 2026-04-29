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
  - optionally prepares a no-execution remote apply plan when host access data is supplied
  - does not deploy infrastructure

Useful references in this lane:

- [Project Plan](./docs/PROJECT_PLAN.md)
- [Scenario 1 Project Plan](./docs/SCENARIO1_PROJECT_PLAN.md)
- [Field Boundaries](./docs/FIELD_BOUNDARIES.md)
- [Backend Contract Map](./docs/SHARED_INTEGRATION_MAP.md)
- [Framework Config Example](./config/framework.example.json)
- [Deployment Bundle Example](./config/deployment-bundle.example.json)
