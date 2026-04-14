# MUXER3 C4 Diagram Set

This folder breaks the current MUXER3 codebase into a C4 diagram set that
matches the code we actually run today:

- DynamoDB-backed customer source of truth
- pass-through muxer mode
- per-customer GRE delivery to VPN head ends
- Libreswan termination on the VPN head ends

It is meant to complement, and in a few places correct, the older
`MUXER3_ARCHITECTURE.md` design-target document in the parent docs folder.
That older document still describes a per-customer Libreswan runtime on the
muxer host, while the live code now routes encrypted traffic to VPN head ends.

## Diagram order

1. `01-system-context.mmd`
2. `02-container-view.mmd`
3. `03-muxer-component-view.mmd`
4. `04-headend-component-view.mmd`
5. `05-nat-t-dynamic-flow.mmd`
6. `06-strict-nonnat-dynamic-flow.mmd`
7. `07-aws-deployment-view.mmd`

## How to use these

- In Lucid, import the contents of a single `.mmd` file as Mermaid.
- In Markdown viewers that support Mermaid C4, paste the file contents directly.
- Keep these files in git with the code so architecture changes can be reviewed
  alongside implementation changes.

## Code map

### Customer source of truth and config resolution

- `E:\Code1\MUXER3\config\muxer.yaml`
- `E:\Code1\MUXER3\config\customers.variables.yaml`
- `E:\Code1\MUXER3\src\muxerlib\variables.py`
- `E:\Code1\MUXER3\src\muxerlib\dynamodb_sot.py`
- `E:\Code1\MUXER3\src\muxerlib\customers.py`

These files define the global muxer settings, load customers from variables or
DynamoDB, resolve backend roles to active backend IPs, and derive customer
protocol and tunnel settings.

### Muxer control plane

- `E:\Code1\MUXER3\src\muxerlib\cli.py`
- `E:\Code1\MUXER3\src\muxerlib\dataplane.py`
- `E:\Code1\MUXER3\scripts\render_customer_variables.py`

These files coordinate apply/show/flush operations, derive the readable
dataplane model, and render per-customer artifacts.

### Muxer dataplane

- `E:\Code1\MUXER3\src\muxerlib\modes.py`
- `E:\Code1\MUXER3\src\muxerlib\core.py`

These files build and maintain the live Linux dataplane:

- `MUXER_FILTER`
- `MUXER_MANGLE`
- `MUXER_NAT_PRE`
- `MUXER_NAT_POST`
- per-customer GRE tunnels
- per-customer `ip rule` and route tables

### VPN head-end artifact generation

- `E:\Code1\MUXER3\scripts\render_headend_customer_bundle.py`
- `E:\Code1\MUXER3\config\headend-bundles\`

These files generate Libreswan configs, GRE apply scripts, post-IPsec NAT
scripts, and systemd units for the head-end clusters.

### Operator tooling

- `E:\Code1\MUXER3\scripts\muxer_customer_doctor.py`
- `E:\Code1\MUXER3\docs\MUXER_OPERATOR_PLAYBOOK.md`

These files provide drift detection, operational explainability, and repair
guidance.

## Notes on scope

- The muxer diagrams reflect the current `mode: pass_through` implementation.
- The deployment view includes AWS services that are part of the running
  solution, even when the provisioning code lives in the deployments repo.
- The dynamic views are split into NAT-T and strict non-NAT because the muxer
  handles those classes differently at the NAT-rewrite stage.
