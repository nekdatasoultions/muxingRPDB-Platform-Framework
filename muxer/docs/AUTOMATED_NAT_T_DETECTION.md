# Automated NAT-T Detection

## Purpose

NAT-T promotion should not depend on an operator manually noticing UDP/4500.

The RPDB workflow now has an automated detector that can watch muxer log events,
correlate them to dynamic customer requests, write a reviewed NAT-T observation
event, and launch the repo-only provisioning package workflow.

The detector still has `live_apply: false`. It prepares the package and audit
artifacts. Applying that package to live muxer, DynamoDB, or VPN head-end
systems remains a separately approved deployment step.

## Detection Flow

1. A customer is provisioned from a normal request with no `customer_class` and
   no `backend.cluster`.
2. The initial generated package defaults to strict non-NAT:
   - UDP/500 enabled
   - ESP/50 enabled
   - UDP/4500 disabled
   - non-NAT backend pool
3. The watcher reads muxer log events.
4. The watcher records UDP/500 from the customer peer.
5. If UDP/4500 later appears from the same peer, the watcher writes an
   observation event.
6. The watcher can call `provision_customer_end_to_end.py` with that
   observation event.
7. The resulting package is a NAT-T promotion package with audit, readiness,
   bundle validation, and double verification.

## Supported Log Event Shapes

The watcher supports JSONL events:

```json
{"observed_peer":"3.237.201.84","observed_protocol":"udp","observed_dport":500,"observed_at":"2026-04-15T22:45:00Z"}
{"observed_peer":"3.237.201.84","observed_protocol":"udp","observed_dport":4500,"observed_at":"2026-04-15T22:45:02Z"}
```

It also supports iptables-style log lines that include at least:

```text
PROTO=UDP SRC=3.237.201.84 DPT=4500
```

## One-Shot Verification Command

Use this form to process current log contents once:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request muxer\config\customer-requests\migrated\vpn-customer-stage1-15-cust-0004.yaml `
  --log-file build\nat-t-log-watcher\muxer-events.jsonl `
  --out-dir build\nat-t-log-watcher\out `
  --state-file build\nat-t-log-watcher\state.json `
  --package-root build\nat-t-log-watcher\packages `
  --run-provisioning `
  --json
```

## Continuous Watch Command

Use this form when the muxer runtime is ready to run the detector as a service:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request-root muxer\config\customer-requests\migrated `
  --log-file C:\path\to\muxer-nat-t-events.jsonl `
  --state-file C:\path\to\nat-t-watcher-state.json `
  --out-dir C:\path\to\nat-t-watcher-output `
  --package-root C:\path\to\customer-provisioning `
  --run-provisioning `
  --follow
```

The command above is still repo/package automation only. It does not apply the
generated package live.

## Guardrails

- The customer peer must match the request.
- UDP/500 must be observed first when the customer request requires that
  guardrail.
- UDP/4500 must be observed from the same peer inside the configured
  observation window.
- Duplicate detections reuse state and do not create a second promotion event.
- The provisioning package remains `live_apply: false`.
- Live apply requires a separate deployment plan, backups, and approval.

## Generated Artifacts

The watcher writes:

- `watch-summary.json`
- `state.json`
- `observations/<customer>/<idempotency-key>.json`
- optional customer provisioning package under `--package-root`

When `--run-provisioning` is enabled, the package includes:

- `provisioning-run.json`
- `pilot-readiness.json`
- `customer-source.yaml`
- `customer-module.json`
- `customer-ddb-item.json`
- `allocation-summary.json`
- `allocation-ddb-items.json`
- `bundle/`
- `bundle-validation.json`
- `double-verification.json`
