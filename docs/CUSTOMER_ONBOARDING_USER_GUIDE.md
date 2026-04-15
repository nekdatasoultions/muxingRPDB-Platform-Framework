# Customer Onboarding User Guide

## What This Guide Is

This is the operator-facing guide for onboarding one customer into the RPDB
platform.

Use this guide when you need to answer:

- what information do I need from the customer
- what request file do I create
- what commands do I run
- what artifacts should I review
- when do I stop before touching live nodes

This guide does not replace the engineering runbook. For the deeper validation
and deployment details, see:

- `docs/CUSTOMER_ONBOARDING_RUNBOOK.md`
- `docs/PRE_DEPLOY_DOUBLE_VERIFICATION.md`
- `docs/HEADEND_CUSTOMER_ORCHESTRATION.md`

## Golden Rule

Onboarding has two phases.

Phase 1 is safe and repo-only:

- create the customer request
- validate it
- let RPDB auto-assign marks, tables, tunnel keys, overlays, and backend
  placement
- render artifacts
- build a customer bundle
- run double verification
- review everything

Phase 2 is live deployment:

- write to the live customer database
- apply muxer runtime changes
- apply VPN head-end changes
- change customer-side peer settings
- validate traffic
- rollback if needed

This document only takes you through Phase 1. Stop before Phase 2 unless the
change window is approved.

## Before You Start

Work from the RPDB repo root:

```powershell
cd "E:\Code1\muxingRPDB Platform Framework-main"
```

Confirm the repo is clean enough to start:

```powershell
git status --short --branch
```

Expected:

```text
## main...origin/main
```

If unrelated changes are present, stop and ask whether they should be preserved,
committed, or ignored.

## What The Operator Provides

The operator provides normal site-to-site VPN information.

The operator should not manually assign RPDB platform values such as marks,
route tables, tunnel keys, RPDB priorities, or overlay addresses.

### Required Customer Information

Fill out this intake form before creating the request.

```text
Customer name:
New customer or migrated customer:
NAT customer or strict non-NAT customer:

Customer peer public IP:
Customer remote ID:
Our local ID expected by customer:
PSK secret reference:

IKE version:
IKE policy options:
ESP policy options:
DPD delay:
DPD timeout:
DPD action:
PFS required:
PFS groups:
Replay protection:
Force encapsulation:
MOBIKE:
Fragmentation:
Clear DF bit:

Our local/core subnets:
Customer remote subnets:

Post-IPsec NAT required:
Real customer subnet or host:
Translated subnet or /27:
Explicit host mappings:
Core subnets participating after NAT:

Requested backend cluster:
Preferred backend assignment:

Customer-side public IP change required:
SmartGateway or downstream route change required:
Dynamic NAT-T promotion allowed:
Rollback owner:
Validation owner:
```

## Decide The Customer Type

Choose `nat` when the customer uses NAT-T or is expected to use UDP/4500.

Choose `strict-non-nat` when the customer must use native ESP and should not use
UDP/4500.

Quick decision table:

```text
Customer uses UDP/4500: nat
Customer uses native ESP only: strict-non-nat
Customer requires post-IPsec translation to a /27: nat
Customer must preserve strict public identity and ESP: strict-non-nat
Not sure: stop and review the live VPN behavior first
```

## Dynamic NAT-T Discovery

When NAT behavior is unknown, start with strict non-NAT by default.

That means:

- UDP/500 is enabled
- ESP/50 is enabled
- UDP/4500 is disabled
- the customer is placed on the non-NAT stack

If the muxer later sees UDP/4500 from that same peer, do not hand-edit the
customer into production. Generate a repo-only NAT-T promotion package and
review it.

Use this committed example for the initial request shape:

```text
muxer\config\customer-requests\examples\example-dynamic-default-nonnat.yaml
```

Create an observation file after the muxer has seen UDP/4500 from the same
peer:

```powershell
$Observation = "$WorkRoot\nat-t-observation.json"

@{
  schema_version = 1
  event_id = "$CustomerName-udp4500-observed"
  customer_name = $CustomerName
  observed_peer = "CUSTOMER_PUBLIC_IP"
  observed_protocol = "udp"
  observed_dport = 4500
  initial_udp500_observed = $true
  packet_count = 1
  observed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  source = "operator-reviewed"
} | ConvertTo-Json | Set-Content -Encoding utf8 $Observation
```

Then process it through the audited repo-only workflow:

```powershell
python muxer\scripts\process_nat_t_observation.py $Request `
  --observation $Observation `
  --out-dir "$WorkRoot\dynamic-nat-t" `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

Run the same command twice. The second run should return
`status: already_planned` and `new_allocation_created: false`.

Stop after reviewing the promoted request, source, module, DynamoDB item view,
allocation summary, and audit record. Live promotion still needs its own
approved change window.

## Create The Customer Request

Customer request files live under:

```text
muxer\config\customer-requests\
```

Use an example as the starting point.

For NAT:

```powershell
Copy-Item `
  "muxer\config\customer-requests\examples\example-service-intent-netmap.yaml" `
  "muxer\config\customer-requests\CUSTOMER_NAME.yaml"
```

For strict non-NAT:

```powershell
Copy-Item `
  "muxer\config\customer-requests\examples\example-minimal-nonnat.yaml" `
  "muxer\config\customer-requests\CUSTOMER_NAME.yaml"
```

Replace `CUSTOMER_NAME` with the actual customer name.

## NAT Customer Request Template

Use this shape for a NAT-T customer with `/27` post-IPsec NAT.

```yaml
schema_version: 1

customer:
  name: CUSTOMER_NAME
  customer_class: nat

  peer:
    public_ip: CUSTOMER_PUBLIC_IP
    remote_id: CUSTOMER_REMOTE_ID
    psk_secret_ref: /muxingrpdb/customers/CUSTOMER_NAME/psk

  backend:
    cluster: nat

  selectors:
    local_subnets:
      - 172.31.54.39/32
      - 194.138.36.80/28
    remote_subnets:
      - CUSTOMER_REAL_SUBNET_OR_HOST

  protocols:
    udp500: true
    udp4500: true
    esp50: false

  ipsec:
    ike_version: ikev2
    ike_policies:
      - aes256-sha256-modp2048
    esp_policies:
      - aes256-sha256
    dpddelay: 30s
    dpdtimeout: 120s
    dpdaction: restart
    forceencaps: true
    mobike: false
    fragmentation: true
    clear_df_bit: true
    replay_protection: true
    pfs_required: false
    pfs_groups:
      - modp2048

  post_ipsec_nat:
    enabled: true
    mode: netmap
    mapping_strategy: one_to_one
    real_subnets:
      - CUSTOMER_REAL_SUBNET_OR_HOST
    translated_subnets:
      - TRANSLATED_SUBNET_OR_27
    core_subnets:
      - 172.31.54.39/32
      - 194.138.36.80/28
    tcp_mss_clamp: 1360
```

Important NAT notes:

- `selectors.remote_subnets` is the customer-side traffic inside the VPN.
- `post_ipsec_nat.real_subnets` is the customer-side traffic that gets
  translated after decrypt.
- `post_ipsec_nat.translated_subnets` is what we present internally after NAT.
- `post_ipsec_nat.core_subnets` is our side of the traffic after translation.

## Strict Non-NAT Customer Request Template

Use this shape for a strict non-NAT customer.

```yaml
schema_version: 1

customer:
  name: CUSTOMER_NAME
  customer_class: strict-non-nat

  peer:
    public_ip: CUSTOMER_PUBLIC_IP
    remote_id: CUSTOMER_REMOTE_ID
    psk_secret_ref: /muxingrpdb/customers/CUSTOMER_NAME/psk

  backend:
    cluster: non-nat

  selectors:
    local_subnets:
      - 172.31.54.39/32
      - 194.138.36.80/28
    remote_subnets:
      - CUSTOMER_REMOTE_SUBNET_OR_HOST

  protocols:
    udp500: true
    udp4500: false
    esp50: true

  natd_rewrite:
    enabled: true
    initiator_inner_ip: ""

  ipsec:
    ike_version: ikev2
    ike_policies:
      - aes256-sha256-modp2048
    esp_policies:
      - aes256-sha256
    dpddelay: 10s
    dpdtimeout: 120s
    dpdaction: restart
    forceencaps: false
    mobike: false
    fragmentation: true
    clear_df_bit: true
    replay_protection: true
    pfs_required: false
    pfs_groups:
      - modp2048

  post_ipsec_nat:
    enabled: false
    mode: disabled
```

Important strict non-NAT notes:

- `udp4500` must be `false`.
- ESP must be allowed.
- The customer must be placed on the non-NAT head-end side.
- Do not use post-IPsec NAT unless the design is reviewed first.

## Run The Onboarding Commands

Set variables for the customer.

```powershell
$CustomerName = "CUSTOMER_NAME"
$WorkRoot = "build\onboarding\$CustomerName"
$Request = "muxer\config\customer-requests\$CustomerName.yaml"
$AllocatedSource = "$WorkRoot\customer-source.yaml"
$CustomerModule = "$WorkRoot\customer-module.json"
$CustomerDdbItem = "$WorkRoot\customer-ddb-item.json"
$AllocationSummary = "$WorkRoot\allocation-summary.json"
$RenderDir = "$WorkRoot\render"
$HandoffDir = "$WorkRoot\handoff"
$BoundDir = "$WorkRoot\bound-handoff"
$BundleDir = "$WorkRoot\bundle"
$HeadendRoot = "$WorkRoot\headend-root"
New-Item -ItemType Directory -Force $WorkRoot | Out-Null
```

Choose the right environment file.

For NAT:

```powershell
$EnvironmentFile = "muxer\config\environment-defaults\rpdb-empty-nat-active-a.yaml"
```

For strict non-NAT:

```powershell
$EnvironmentFile = "muxer\config\environment-defaults\rpdb-empty-nonnat-active-a.yaml"
```

### 1. Validate The Request

```powershell
python muxer\scripts\validate_customer_request.py $Request
```

Stop if validation fails.

### 2. Provision The Customer

```powershell
python muxer\scripts\provision_customer_request.py $Request `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --source-out $AllocatedSource `
  --module-out $CustomerModule `
  --item-out $CustomerDdbItem `
  --allocation-out $AllocationSummary
```

Review:

```powershell
Get-Content $AllocationSummary
Get-Content $AllocatedSource
```

Confirm RPDB assigned the values automatically.

### 3. Validate The Allocated Source

```powershell
python muxer\scripts\validate_customer_source.py $AllocatedSource
```

Stop if validation fails.

### 4. Render Artifacts

```powershell
python muxer\scripts\render_customer_artifacts.py $AllocatedSource `
  --out-dir $RenderDir `
  --source-ref $AllocatedSource
```

Validate the render:

```powershell
python muxer\scripts\validate_rendered_artifacts.py $RenderDir
```

### 5. Export The Handoff

```powershell
python muxer\scripts\export_customer_handoff.py $AllocatedSource `
  --export-dir $HandoffDir `
  --muxer-dir "$RenderDir\muxer" `
  --headend-dir "$RenderDir\headend" `
  --source-ref $AllocatedSource
```

### 6. Bind To The Target Environment

```powershell
python muxer\scripts\validate_environment_bindings.py $EnvironmentFile
```

```powershell
python muxer\scripts\bind_rendered_artifacts.py $HandoffDir `
  --environment-file $EnvironmentFile `
  --out-dir $BoundDir
```

```powershell
python muxer\scripts\validate_bound_artifacts.py $BoundDir
```

Review:

```powershell
Get-Content "$BoundDir\binding-report.json"
```

### 7. Build The Customer Bundle

```powershell
python scripts\packaging\assemble_customer_bundle.py `
  --customer-name $CustomerName `
  --bundle-dir $BundleDir `
  --export-dir $BoundDir
```

```powershell
python scripts\packaging\validate_customer_bundle.py $BundleDir
```

```powershell
python scripts\packaging\build_customer_bundle_manifest.py $BundleDir
```

Review:

```powershell
Get-Content "$BundleDir\manifest.txt"
Get-Content "$BundleDir\sha256sums.txt"
```

### 8. Test Head-End Install In A Staged Root

This does not touch a real head end.

```powershell
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

```powershell
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

```powershell
python scripts\deployment\remove_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

## Review The Generated Artifacts

Review these files before any live deployment.

Customer artifacts:

```text
build\onboarding\<customer>\customer-source.yaml
build\onboarding\<customer>\customer-module.json
build\onboarding\<customer>\customer-ddb-item.json
build\onboarding\<customer>\allocation-summary.json
```

Rendered and bound artifacts:

```text
build\onboarding\<customer>\render\
build\onboarding\<customer>\handoff\
build\onboarding\<customer>\bound-handoff\
```

Deployment bundle:

```text
build\onboarding\<customer>\bundle\
```

Staged head-end proof:

```text
build\onboarding\<customer>\headend-root\
```

## What To Check In The Review

Customer request:

- customer name is correct
- NAT or strict non-NAT class is correct
- peer public IP is correct
- remote ID is correct
- PSK secret reference is correct
- local/core selectors are correct
- remote/customer selectors are correct
- NAT intent is correct

Allocated source:

- customer ID was assigned
- fwmark was assigned
- route table was assigned
- RPDB priority was assigned
- tunnel key was assigned
- overlay block was assigned
- interface name was assigned
- backend placement matches customer class

NAT customer:

- UDP/4500 is enabled
- NAT head-end environment binding is used
- post-IPsec NAT is enabled when needed
- translated `/27` or explicit host map is correct
- SmartGateway/core subnet list is correct

Strict non-NAT customer:

- UDP/4500 is disabled
- ESP is enabled
- non-NAT head-end environment binding is used
- NAT-D rewrite behavior is intentional
- post-IPsec NAT is disabled unless reviewed

Bundle:

- manifest exists
- checksums exist
- customer source exists
- customer module exists
- DynamoDB item exists
- muxer artifacts exist
- head-end artifacts exist
- staged apply and remove were tested

## Stop Gate Before Live Deployment

Stop here.

Do not touch live nodes until the deployment owner approves:

- exact customer
- exact change window
- exact muxer platform
- exact NAT or non-NAT head end
- exact customer-side peer IP change
- exact database write target
- exact rollback steps
- exact backup locations
- exact validation commands

## Live Deployment Is Separate

Live deployment will use the reviewed bundle, but it is not part of this user
onboarding guide.

Before live deployment, confirm:

- muxer backup exists
- VPN head-end backup exists
- customer-side backup exists
- route and firewall backup exists
- rollback owner is available
- validation owner is available
- customer contact is available

## Common Mistakes

Do not manually assign marks, route tables, or tunnel keys.

Do not put raw PSKs in the request when a secret reference should be used.

Do not choose NAT vs non-NAT based on customer name. Choose it based on the VPN
behavior.

Do not confuse customer-side real subnet with translated subnet.

Do not assume `local_subnets` means muxer-side routing. These are VPN selectors
for the head-end/customer relationship.

Do not apply generated artifacts to `/etc`, `/usr/local/sbin`, live DynamoDB, or
live iptables during repo-only onboarding.

Do not proceed if double verification fails.

## Quick Success Definition

Onboarding is complete when:

- request validation passes
- provisioning succeeds
- allocation summary is reviewed
- allocated customer source validation passes
- render validation passes
- environment binding validation passes
- bundle validation passes
- staged head-end apply succeeds
- staged head-end validation succeeds
- staged head-end remove succeeds
- generated artifacts are reviewed
- live deployment stop gate is acknowledged

At that point, the customer is ready for deployment planning, not automatically
deployed.
