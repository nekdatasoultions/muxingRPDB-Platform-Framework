# RPDB NAT-T Listener Corrective Plan

## Purpose

This document records the implementation gap and the correction gate for
automatic NAT-T promotion.

The intended RPDB flow is:

```text
customer starts on UDP/500 + ESP
muxer observes UDP/4500 from the same peer
RPDB creates a NAT-T observation
the one-command customer workflow promotes the customer to the NAT head end
```

The repo had the watcher/orchestrator consumer, but the muxer runtime did not
have the producer: no listener service was packaged, installed, enabled, or
verified on the muxer.

## Correction

The runtime package must include:

- `muxer/runtime-package/src/nat_t_event_listener.py`
- `muxer/runtime-package/systemd/rpdb-nat-t-listener.service`
- installer support in `muxer/runtime-package/scripts/install-local.sh`
- CloudFormation/runtime converge hooks that enable the service on RPDB muxers
- SSH live-apply runtime sync that copies and validates the listener before
  applying customer state
- repo verification that fails if the listener, unit, installer, event log
  contract, and watcher handoff are not present

## Runtime Rules

- The listener is passive only.
- The listener writes JSONL to `/var/log/rpdb/muxer-events.jsonl`.
- The listener observes UDP/500 and UDP/4500.
- The listener ignores packets sourced from local muxer addresses.
- The listener does not call iptables.
- The listener does not program firewall or route state.
- Packet steering remains nftables/RPDB.

## Gate

Before any live listener deployment:

- the listener must compile
- the listener self-test must pass
- the systemd unit must exist in the runtime package
- the runtime installer must install the unit
- the fresh muxer CloudFormation/converge path must enable the unit
- the SSH runtime sync path must copy, validate, install, enable, and restart
  the unit
- the watcher must still consume listener-shaped JSONL and generate a NAT-T
  observation
- full repo verification must pass

No live node change is complete unless the same change exists in Git first.
