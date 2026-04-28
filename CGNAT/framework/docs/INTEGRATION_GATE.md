# Integration Gate

## Purpose

This document records the explicit stop point before anything outside `CGNAT/`
is touched.

The CGNAT project is allowed to progress inside `CGNAT/` through deployable
shape definition, local validation, and first working version preparation. It
must stop here before shared-repo integration begins.

## Integration Gate Rule

If work appears to require any file outside `CGNAT/`:

1. stop
2. list the exact file paths
3. explain why each file must change
4. describe the minimum required integration surface
5. wait for explicit approval

No exceptions.

## What This Protects

This gate protects:

- the workspace boundary guardrail
- the publication freeze
- the separation between CGNAT framework design and shared RPDB integration

## Required Inputs Before Crossing the Gate

- deployable shapes are defined
- validation artifacts exist
- a first working version is credible
- the integration targets are specific
- the user explicitly approves the cross-workspace change

## Acceptance Criteria

This document is complete enough for the current phase when:

- the stop point is explicit
- the approval steps are explicit
- the document clearly supports the project guardrails
