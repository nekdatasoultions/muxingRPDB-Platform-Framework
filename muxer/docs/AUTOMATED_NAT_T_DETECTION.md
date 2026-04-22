# Automated NAT-T Detection

## Purpose

NAT-T promotion should not depend on an operator manually noticing UDP/4500.

The RPDB workflow has two pieces:

- the muxer runtime listener emits packet observations to JSONL
- the repo/control-plane watcher consumes those observations and can launch the
  customer provisioning workflow

The runtime listener is packaged in `muxer/runtime-package` as
`nat_t_event_listener.py` plus `rpdb-nat-t-listener.service`. It passively reads
UDP/500 and UDP/4500 with `tcpdump` and writes
`/var/log/rpdb/muxer-events.jsonl`. It does not program firewall state and does
not call iptables.

The watcher can run in dry-run/package mode or, when explicitly approved by the
deployment environment, call the one-command deploy orchestrator.

## Detection Flow

1. A customer is provisioned from a normal request with no `customer_class` and
   no `backend.cluster`.
2. The initial generated package defaults to strict non-NAT:
   - UDP/500 enabled
   - ESP/50 enabled
   - UDP/4500 disabled
   - non-NAT backend pool
3. The muxer runtime listener writes JSONL muxer events.
4. The watcher reads muxer log events.
5. The watcher records UDP/500 from the customer peer.
6. If UDP/4500 later appears from the same peer, the watcher writes an
   observation event.
7. The watcher can call the customer deploy orchestrator with that observation
   event.
8. The resulting package is a NAT-T promotion package with audit, readiness,
   bundle validation, and double verification.

## Supported Log Event Shapes

The watcher supports JSONL events:

```json
{"observed_peer":"3.237.201.84","observed_protocol":"udp","observed_dport":500,"observed_at":"2026-04-15T22:45:00Z"}
{"observed_peer":"3.237.201.84","observed_protocol":"udp","observed_dport":4500,"observed_at":"2026-04-15T22:45:02Z"}
```

For legacy/test parsing only, the watcher still understands log lines shaped
like historical firewall logs:

```text
PROTO=UDP SRC=3.237.201.84 DPT=4500
```

The RPDB runtime listener does not produce those legacy lines.

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

Use this form after the muxer runtime listener is installed and writing
`/var/log/rpdb/muxer-events.jsonl`:

```powershell
python muxer\scripts\watch_nat_t_logs.py `
  --customer-request-root muxer\config\customer-requests\migrated `
  --environment rpdb-empty-live `
  --state-file build\nat-t-watcher\state\state.json `
  --out-dir build\nat-t-watcher\out `
  --package-root build\nat-t-watcher\packages `
  --run-provisioning `
  --follow
```

When `--environment` defines `nat_t_watcher.log_source.path`, the watcher uses
that path automatically. You can still pass `--log-file` explicitly for lab
tests or staged replay.

The command above is still repo/package automation only. It does not apply the
generated package live.

## Guardrails

- The customer peer must match the request.
- UDP/500 must be observed first when the customer request requires that
  guardrail.
- UDP/4500 must be observed from the same peer inside the configured
  observation window.
- Duplicate detections reuse state and do not create a second promotion event.
- The runtime listener must be installed as `rpdb-nat-t-listener.service`.
- Runtime listener output must be JSONL at `/var/log/rpdb/muxer-events.jsonl`.
- Live apply requires backups, environment approval, and explicit operator
  approval.

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
