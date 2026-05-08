# Scope01 Layout Alignment Plan

## Goal

Align the RPDB/CGNAT repo structure with the layout style used by
`Scope01-feature-security-hardening-and-test-env` so that future code sharing
or repo merging is much less painful.

This is a **layout and ownership** plan, not an instruction to rewrite working
logic all at once.

## What We Are Matching

The Scope01 repo is organized around a very simple top-level shape:

```text
Scope01/
  cloudformation/
    templates/
    parameters/
  containers/
  scripts/
  tests/
  README.md
```

That structure has a few useful properties:

1. infra is under one obvious home
2. tests are under one obvious home
3. deployment entrypoints are under one obvious home
4. environment parameters are grouped by deployment surface
5. service-specific implementation details sit below a small number of
   predictable roots

## Current RPDB Shape

Today the RPDB repo is workable, but more fragmented:

```text
muxingRPDB Platform Framework-main/
  CGNAT/
  config/
  docs/
  infra/
  muxer/
  muxer_passthrough/
  ops/
  scripts/
  build/
```

The biggest differences versus Scope01 are:

1. infra is split across `infra/`, `scripts/platform`, and some config roots
2. service code is split across `muxer/` and `CGNAT/`
3. tests are not unified at the repo root
4. generated artifacts and historical/reference content are visually close to
   active code
5. active runtime, control-plane code, and scenario/framework work are not
   grouped under a single service-oriented structure

## Recommended Target Shape

We should move toward this root layout:

```text
muxingRPDB Platform Framework-main/
  cloudformation/
    templates/
    parameters/
  config/
  docs/
  scripts/
    platform/
    deployment/
    customers/
    packaging/
    backup/
  services/
    muxer/
    cgnat/
  tests/
    unit/
    regression/
    integration/
  ops/
  README.md
```

### Important Notes

- `build/` should remain generated output and should **not** become part of the
  merge target structure.
- `containers/` should only be added if we actually carry container build
  assets. We should not force that directory into existence just to imitate
  Scope01.
- legacy migration inventory can stay, but it should not sit in the same visual
  lane as active code paths.

## Mapping From Current Layout To Target Layout

### 1. CloudFormation

Current:

- `infra/cfn`

Target:

- `cloudformation/templates`
- `cloudformation/parameters`

Planned mapping:

- `infra/cfn/*.yaml` -> `cloudformation/templates/`
- `infra/cfn/parameters.*.json` -> `cloudformation/parameters/`

We should further normalize parameter files into environment folders where it
makes sense:

```text
cloudformation/parameters/
  shared/
  dev/
  staging/
  prod/
  rpdb-empty/
```

### 2. Service Code

Current:

- `muxer/src`
- `muxer/runtime-package`
- `CGNAT/framework/src/cgnat`
- `CGNAT/framework/config`
- `CGNAT/framework/scripts`

Target:

- `services/muxer`
- `services/cgnat`

Planned mapping:

```text
services/muxer/
  src/
  runtime/
  config/
  docs/

services/cgnat/
  src/
  config/
  docs/
```

This keeps service ownership clear and removes the current split between
`muxer/` and `CGNAT/` as top-level peers with different internal conventions.

### 3. Shared Config

Current:

- `config/`
- `muxer/config/`
- `CGNAT/framework/config/`

Target:

- repo-level shared config stays in `config/`
- service-specific config moves under `services/<service>/config`

Planned mapping:

- `config/strongswan`, `config/conntrackd` remain repo-shared
- `muxer/config/*` -> `services/muxer/config/*`
- `CGNAT/framework/config/*` -> `services/cgnat/config/*`

### 4. Scripts

Current:

- `scripts/platform`
- `scripts/customers`
- `scripts/deployment`
- `scripts/packaging`
- `scripts/backup`
- `muxer/scripts`
- `CGNAT/framework/scripts`

Target:

- keep `scripts/` as the operator/entrypoint home
- move service-specific helper scripts below service roots unless they are true
  operator entrypoints

Planned split:

- **keep in `scripts/`**
  - cross-cutting deploy/apply/backup/packaging/operator entrypoints
- **move under `services/muxer/scripts/`**
  - muxer-only render/provision/model helpers
- **move under `services/cgnat/scripts/`**
  - cgnat-only preparation/review/materialization helpers

This mirrors Scope01's idea that top-level `scripts/` should feel like
operators' front door, not a catch-all for every internal helper.

### 5. Tests

Current:

- `CGNAT/tests`
- `muxer/scripts/run_repo_verification.py`
- scattered verification logic in scripts

Target:

```text
tests/
  unit/
  regression/
  integration/
```

Planned mapping:

- `CGNAT/tests/test_*` -> `tests/unit/` or `tests/regression/` depending on role
- `CGNAT/tests/run_regression.py` -> `tests/regression/run_regression.py`
- `CGNAT/tests/run_tests.py` -> `tests/unit/run_tests.py`
- `muxer/scripts/run_repo_verification.py` should be split and converted into:
  - `tests/regression/run_repo_verification.py`
  - helper library under `tests/` or `scripts/`

This is one of the highest-value alignments because Scope01 has a very obvious
test entrypoint model.

### 6. Docs

Current:

- `docs/`
- `muxer/docs/`
- `CGNAT/framework/docs/`
- `infra/runbooks/`

Target:

- `docs/` becomes the top-level documentation home
- service-specific docs live under:
  - `services/muxer/docs`
  - `services/cgnat/docs`
- infra-specific runbooks move under:
  - `cloudformation/docs` or `docs/platform`

We should keep the current "supported path" vs "migration/reference path"
language that we already added.

## What We Should Not Move Yet

These are still active enough that they should move only after wrappers and
tests are in place:

- `scripts/customers/deploy_customer.py`
- `scripts/customers/live_apply_lib.py`
- `scripts/platform/deploy_empty_platform.py`
- `muxer/runtime-package`

They should move in a controlled phase with compatibility shims, not in an
"everything everywhere all at once" refactor.

## Execution Plan

### Phase 0 - Freeze And Inventory

1. Freeze current active entrypoints
2. Freeze current test commands
3. Record current import paths and file references
4. Do not move any live-sensitive behavior yet

Deliverable:

- authoritative move map for code, docs, config, and tests

### Phase 1 - Create Target Skeleton

Create the new directories without moving behavior yet:

```text
cloudformation/
  templates/
  parameters/
services/
  muxer/
    src/
    runtime/
    config/
    docs/
    scripts/
  cgnat/
    src/
    config/
    docs/
    scripts/
tests/
  unit/
  regression/
  integration/
```

Deliverable:

- target tree exists
- README files explain ownership

### Phase 2 - Move CloudFormation Surface

1. move `infra/cfn` into `cloudformation/`
2. keep thin compatibility wrappers if existing scripts still point at old
   paths
3. update active docs and validation scripts

Deliverable:

- active infra surface lives under `cloudformation/`

### Phase 3 - Move Service Code

1. move `muxer/src`, `muxer/config`, `muxer/docs`, `muxer/runtime-package`
   under `services/muxer/`
2. move `CGNAT/framework/src`, `CGNAT/framework/config`,
   `CGNAT/framework/docs`, `CGNAT/framework/scripts` under `services/cgnat/`
3. leave transition wrappers in the old locations until tests are green

Deliverable:

- service ownership is explicit
- top-level clutter drops sharply

### Phase 4 - Unify Tests

1. create root `tests/`
2. move CGNAT test suite into root test categories
3. split `run_repo_verification.py` into proper regression entrypoints
4. make `python tests/...` the standard test interface

Deliverable:

- one obvious test root
- one obvious unit/regression split

### Phase 5 - Normalize Scripts

1. keep top-level `scripts/` for operator entrypoints
2. move service-only helper scripts under `services/*/scripts`
3. leave only stable front-door commands at top-level `scripts/`

Deliverable:

- top-level script surface looks closer to Scope01
- internals are no longer mixed with operator entrypoints

### Phase 6 - Remove Compatibility Wrappers

1. after imports and tests are stable, remove old path wrappers
2. update docs and CI/test commands one final time
3. confirm no active code references old roots

Deliverable:

- clean post-migration tree

## Merge-Prep Rules

When we do this work, we should follow these rules:

1. **No behavior changes mixed with layout changes**
2. **One root move at a time**
3. **Tests must stay green after every phase**
4. **Leave wrappers first, delete wrappers later**
5. **Never move generated build artifacts into the source layout**
6. **Do not delete migration inventory until the migration program is done**

## Recommended First Slice

The safest first slice is:

1. create `cloudformation/`
2. create `services/muxer/` and `services/cgnat/`
3. move only docs and non-runtime config first
4. add wrappers
5. run regression

That gives us a low-risk structural win before we move the hotter code paths.

## Success Definition

We are aligned enough for an eventual merge when:

1. infra lives under `cloudformation/`
2. service code lives under `services/`
3. tests live under root `tests/`
4. top-level `scripts/` contains only operator entrypoints
5. active docs clearly describe the new structure
6. old paths are gone or reduced to deliberate compatibility wrappers

