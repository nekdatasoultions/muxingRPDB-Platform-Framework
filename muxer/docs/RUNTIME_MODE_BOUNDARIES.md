# Runtime Mode Boundaries

## Supported Migration Scope

The RPDB migration path is intentionally scoped to:

- `pass_through` mode on the muxer

That means:

- the muxer owns customer steering, RPDB, GRE, and public-edge filtering
- the VPN head ends remain the IPsec endpoints

This is the architecture the current platform is actually using, so this is the
mode the repo now treats as migration-relevant.

## What Is Supported

For pass-through mode, the runtime now supports:

- `show-customer`
- `apply-customer`
- `remove-customer`

And those customer-scoped write commands are delta-oriented:

- they do not flush the whole chain set
- they do not rebuild every loaded customer
- they only clear/reapply the selected customer's runtime state

## What Remains Explicit Fleet Scope

These commands still exist as intentional fleet-style actions:

- `show`
- `apply`
- `flush`

That is acceptable as long as operators treat them as explicit fleet actions,
not as the normal customer-by-customer path.

## What Is Intentionally Blocked

`termination` mode is not part of the migration target right now.

So the runtime explicitly blocks:

- `apply-customer` in termination mode
- `remove-customer` in termination mode

The repo-only verifier proves that boundary today and expects the CLI to return:

- `apply-customer is not implemented yet for muxer termination mode`

## Why We Are Drawing This Boundary

This keeps the project focused on the architecture we are actually moving to:

- RPDB muxer as steering/control plane
- head ends as IPsec endpoints

It prevents us from burning time on muxer-local IPsec termination behavior that
is not needed for the planned customer migration model.

## Verification

The boundary is exercised by:

- [run_repo_verification.py](/E:/Code1/muxingRPDB%20Platform%20Framework-main/muxer/scripts/run_repo_verification.py)

And the summary artifact is written to:

- [repo-verification-summary.json](/E:/Code1/muxingRPDB%20Platform%20Framework-main/build/repo-verification/repo-verification-summary.json)
