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
