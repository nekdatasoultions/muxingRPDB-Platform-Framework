# Server Implementation Issues

## Purpose

This document records concrete server-side implementation issues discovered
while turning the CGNAT Scenario 1 package into executable host-side
configuration artifacts.

## Issue 1: Exact Daemon/Config Syntax Is Not Yet Frozen

### Status

- resolved for the current Scenario 1 contract

### Summary

The current server package cleanly expresses:

- outer tunnel intent
- GRE handoff intent
- backend expectations
- validation targets

The original server package did not yet commit to one final daemon-specific or
distro-specific configuration syntax for:

- IPsec daemon configuration
- GRE device creation commands
- host routing persistence

The current Scenario 1 renderer now freezes that target syntax as:

- strongSwan `swanctl.conf` fragments for the outer tunnel
- Linux `iproute2` shell scripts for GRE and route handling

### Why This Matters

The framework can now render structured server-side config artifacts, but a
full host apply step should not pretend the final runtime syntax is settled if
it is not.

### Current Handling

The current server-side renderer now:

- generates structured config artifacts
- generates concrete strongSwan config fragments
- generates concrete Linux iproute2 scripts
- generates validation commands aligned to that runtime choice

### Resolution

For the current Scenario 1 contract, the runtime/config style is now frozen
well enough to continue building toward deployment without pretending the
backend platform has changed:

- strongSwan for outer-tunnel config syntax
- Linux iproute2 for GRE and routing command syntax

The server-side renderer now also avoids hand-wavy placeholder output by
emitting:

- concrete swanctl fragments
- concrete GRE and route scripts
- a runtime input manifest
- a runtime environment file for apply-time values

The remaining work is host apply integration, not unresolved artifact shape.

## Issue 2: Host Apply Packaging Was Not Yet Defined

### Status

- resolved for the current Scenario 1 contract

### Summary

The earlier server-side work produced good configuration artifacts, but it did
not yet package them into a per-host apply model that operators could stage in
a consistent order.

### Why This Matters

Without a host-apply package, the path from generated artifacts to controlled
host changes would still rely on ad hoc operator interpretation.

### Current Handling

The current Scenario 1 server tooling now prepares:

- per-host bundles for `cgnat_head_end` and `cgnat_isp_head_end`
- preflight scripts
- apply scripts
- rollback notes
- copied validation references

### Resolution

For the current Scenario 1 contract, host apply integration is now modeled
well enough to continue toward real infrastructure review without crossing into
live execution:

- host staging structure is explicit
- apply order is explicit
- preflight checks are explicit
- rollback notes are explicit

## Issue 3: Remote Apply Command Planning Was Not Yet Defined

### Status

- resolved for the current Scenario 1 contract

### Summary

Even after per-host bundles existed, we still lacked a consistent way to turn
them into explicit remote stage/apply command plans once host access details
became known.

### Current Handling

The current tooling now supports a separate remote-apply planning step that
consumes:

- the Scenario 1 host-apply package
- a host access mapping

and produces:

- remote stage command scripts
- remote apply command scripts
- a no-execution remote apply manifest

### Resolution

For the current Scenario 1 contract, we now have a cleaner ladder from
rendered artifacts to real infrastructure execution:

- rendered server configs
- per-host apply package
- remote apply command plan

Remote execution itself is still intentionally outside the current step.

## Issue 4: Remote Execution Wrapper Was Not Yet Present

### Status

- resolved for the current Scenario 1 contract

### Summary

Even with a remote-apply command plan, we still lacked a final wrapper that
could:

- assess execution readiness
- produce an execution plan
- provide a single gated path to real remote execution later

### Current Handling

The current tooling now includes a remote execution wrapper that:

- reads the prepared remote-apply plan
- emits an execution plan and readiness report in `plan` mode
- refuses live execution unless explicitly requested

### Resolution

For the current Scenario 1 contract, the apply ladder is now explicit all the
way to the edge of real infrastructure execution:

- host artifacts
- host-apply package
- remote-apply command plan
- remote execution wrapper with gated live mode
