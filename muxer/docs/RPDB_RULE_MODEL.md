# RPDB Rule Model

## Purpose

This document defines the intended RPDB rule strategy for the new muxing
platform.

## Current Direction

We keep fwmark-based routing policy, but we stop relying on implicit kernel
priority assignment.

## Rule Shape

Per customer, the intended steering rule remains:

```text
fwmark <customer-mark> -> lookup <customer-table>
```

## Priority Plan

Reserve an explicit priority range for customer rules.

Initial plan:

- `1000-19999`
  - customer fwmark rules
- `20000-20999`
  - operator or temporary rules
- keep the built-in Linux defaults untouched
  - `0`
  - `32766`
  - `32767`

## Why This Matters

This gives us:

- deterministic ordering
- easier troubleshooting
- safer large-customer growth

It does not by itself solve rule-count scale, but it removes one avoidable
control-plane ceiling.
