# Scale Baseline Harness

## Purpose

This harness creates a repeatable repo-only scale baseline for the current RPDB
runtime.

It does not touch:

- AWS
- live nodes
- DynamoDB
- local host dataplane state

It measures the current runtime shape by generating synthetic customer modules
and deriving:

- active classification backend
- muxer legacy rule counts
- muxer transport command counts
- head-end post-IPsec NAT command counts
- batched `nftables` model sizes
- timing for derivation, apply planning, remove planning, rollback planning, and
  preview render
- CPU time for derivation and plan building
- peak memory for derivation and plan building

## Script

- `muxer/scripts/run_scale_baseline.py`

## Default Scenarios

The default run covers these customer counts:

- `100`
- `1000`
- `5000`
- `10000`
- `20000`

And these profiles:

- `strict_non_nat`
- `nat_t`
- `nat_t_netmap`
- `mixed`
- `force4500_bridge`
- `natd_bridge`

The `mixed` profile is a 50/50 split between strict non-NAT and NAT-T.

## Command

From the repo root:

```powershell
python muxer/scripts/run_scale_baseline.py --json
```

To compare different backend configs explicitly:

```powershell
python muxer/scripts/run_scale_baseline.py `
  --muxer-config muxer/runtime-package/config/muxer.yaml `
  --json
```

To write the summary to the default build artifact:

```powershell
python muxer/scripts/run_scale_baseline.py `
  --out build/scale-baseline/scale-baseline-summary.json `
  --json
```

## What The Output Means

For each scenario, the summary records:

- customer mix
- total legacy muxer rules
- per-customer rule growth
- estimated shell command growth
- post-IPsec NAT apply and rollback command growth
- batched `nftables` object sizes
- derivation timing
- apply, remove, and rollback plan timing
- derivation and plan CPU time
- derivation and plan peak memory

This is a baseline harness, not a proof that scale is solved.

Its job is to answer:

- how much linear growth still exists today
- which layers still expand per customer
- whether the `nftables` preview is reducing only the first classification
  layer or the whole dataplane problem

The current harness also records which classification backend was selected, so
repo verification can compare the active `nftables` path against a forced
legacy-iptables baseline.

## Explicit Thresholds And Reports

The harness summary is the raw measurement layer.

The explicit pass/fail layer is:

- `muxer/config/scale-thresholds.json`
- `muxer/scripts/generate_scale_report.py`

The threshold manifest defines the expected pass/fail policy for the measured
profiles at:

- `1000`
- `5000`
- `10000`
- `20000`

The report generator consumes one harness summary and emits a machine-checked
report that says which profiles passed and which failed.

From the repo root:

```powershell
python muxer/scripts/generate_scale_report.py `
  --summary build/scale-baseline/scale-baseline-summary.json `
  --thresholds muxer/config/scale-thresholds.json `
  --out-json build/scale-baseline/scale-report.json `
  --out-md build/scale-baseline/scale-report.md `
  --json
```

This is intentionally allowed to produce `failed` output. That is how the repo
now records an honest no-go instead of drifting into narrative-only claims.

## Interpretation

If the summary still shows:

- legacy rule count growing linearly with customer count
- translation stages staying on the legacy rule path
- high shell command counts per customer

then the scalable dataplane backend is still incomplete.

That is the expected current state of the repo.

## Verification

The repo verification suite runs this harness and checks:

- all default scenarios render successfully
- the 20k scenarios exist
- legacy rule growth remains visible only as comparison evidence
- the current `nftables` classification backend reports lower 20k
  classification-layer rule growth than the forced legacy-iptables config
- explicit translated NAT scenarios use nftables head-end activation units
- the mixed profile stays 50/50
- the explicit scale report covers every target count
- the explicit scale report is generated twice and agrees

## Current Honest Result

The current repo-only result is:

- muxer-side classification, translation, and bridge metrics pass the current
  explicit thresholds
- translated NAT-T customers using `nat_t_netmap` pass the explicit thresholds
  at `1000`, `5000`, `10000`, and `20000`
- the head-end post-IPsec NAT activation path is now represented as nftables
  batch activation units

That means the harness is now doing its job correctly: it shows the fixed
head-end NAT activation shape while keeping legacy command growth visible for
comparison.

See:

- [RUNTIME_COMPLETION_PLAN.md](./RUNTIME_COMPLETION_PLAN.md)
- [CUSTOMER_COMMAND_MODEL.md](./CUSTOMER_COMMAND_MODEL.md)
