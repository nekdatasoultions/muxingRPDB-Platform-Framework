# Environment Binding Model

## Goal

Keep the framework reusable while making environment-specific values explicit.

That means:

- framework rendering can emit placeholders like `${HEADEND_PUBLIC_IP}`
- environment binding resolves those placeholders later
- the same customer model can be reused in another environment with a different
  binding file

## Inputs

The binding layer uses:

- a rendered artifact tree or handoff export
- an environment bindings file
- the optional `customer-module.json` for derived values such as
  `BACKEND_UNDERLAY_IP`
  and logical placement values such as `BACKEND_CLUSTER` and
  `BACKEND_ASSIGNMENT`

## Example Binding File

- [example-environment.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/environment-defaults/example-environment.yaml)
- [CURRENT_ENVIRONMENT_PROFILES.md](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/docs/CURRENT_ENVIRONMENT_PROFILES.md)

## Workflow

1. render customer artifacts
2. validate rendered artifacts
3. bind environment-specific placeholders
4. validate the bound artifact tree
5. export or package the bound output

## Initial Binding Keys

- `MUXER_TRANSPORT_IP`
- `MUXER_UNDERLAY_IFACE`
- `BACKEND_UNDERLAY_IP`
- `BACKEND_CLUSTER`
- `BACKEND_ASSIGNMENT`
- `BACKEND_ROLE`
- `HEADEND_PUBLIC_IP`
- `HEADEND_ID`
- `HEADEND_CLEAR_IFACE`
- `PSK_FROM_SECRET_REF`

## Backend Resolution

The preferred RPDB shape is:

- customer source owns logical backend placement
  - `backend.cluster`
  - `backend.assignment`
  - `backend.role`
- environment binding owns physical placement
  - `BACKEND_UNDERLAY_IP`
  - `HEADEND_PRIMARY_IP`
  - `HEADEND_PUBLIC_IP`
  - `HEADEND_ID`

Environment files can now carry a `backend_resolver` section with either:

- `roles.<backend-role>`
- `clusters.<cluster>.<assignment>`

Cluster/assignment-specific bindings override role bindings when both exist.

## Current Profiles

The framework also carries current dev environment examples so the migration
path can be tested without hard-wiring those values into customer source files.

## Initial Helpers

- [validate_environment_bindings.py](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/scripts/validate_environment_bindings.py)
- [bind_rendered_artifacts.py](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/scripts/bind_rendered_artifacts.py)
- [validate_bound_artifacts.py](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/scripts/validate_bound_artifacts.py)
