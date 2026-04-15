# RPDB Customer Onboarding Runbook

## Purpose

This runbook describes how to onboard one customer into the RPDB model without
touching live nodes until the generated artifacts have been reviewed and double
verified.

The process is intentionally customer-scoped:

- one customer request
- one allocated customer source
- one merged muxer runtime module
- one DynamoDB customer item
- one resource allocation summary
- one muxer artifact set
- one head-end artifact set
- one customer bundle
- one rollback plan

## Hard Boundary

Do not apply anything to live muxer, VPN head-end, customer-side devices, route
tables, iptables/nftables, DynamoDB production tables, or Elastic IPs during the
repo-only onboarding flow.

Live-node work starts only after:

- the pilot customer is explicitly selected
- current-state backups are captured
- the customer request is built from verified live facts
- provisioning and allocation validation pass
- rendered artifacts are reviewed
- package validation passes
- double verification passes
- rollback is tied to real backup locations
- a human approves the exact change window and cutover steps

## Model Split

The customer request describes service intent.

Customer-provided intent includes:

- customer name
- VPN behavior and whether NAT-T has already been observed
- peer public IP and remote ID
- PSK secret reference
- IKE/IKEv2 behavior and crypto policy options
- DPD behavior
- PFS behavior
- replay protection behavior
- fragmentation, force-encapsulation, MOBIKE, and DF-bit behavior
- interesting traffic selectors
- post-IPsec NAT intent
- translated `/27` or explicit `/32` mapping requirements

The RPDB allocator assigns platform namespaces.

Allocator-owned values include:

- `customer_id`
- `fwmark`
- `route_table`
- `rpdb_priority`
- `tunnel_key`
- overlay block
- GRE or VTI interface names
- backend assignment result

Operators should not hand-pick collision-prone platform namespaces unless this
is a controlled migration compatibility case.

## Customer Intake Checklist

Collect and verify these facts before creating the customer request.

Customer identity:

- customer name
- known NAT-T behavior, if already proven
- whether this is a new customer or a migrated legacy customer
- whether the customer is reserved for demo use

Peer and authentication:

- customer peer public IP
- customer remote ID
- our local ID expected by the customer
- PSK secret reference, not the raw PSK in the request

VPN compatibility:

- IKE version: IKEv1 or IKEv2
- allowed IKE policy list
- allowed ESP policy list
- DPD delay, timeout, and action
- PFS required or flexible
- allowed PFS groups
- replay protection setting
- force-encapsulation setting
- MOBIKE setting
- fragmentation setting
- DF-bit handling

Traffic intent:

- local/core subnets that participate in the VPN
- remote/customer subnets that participate in the VPN
- whether post-IPsec NAT is required
- real customer subnets to translate
- translated subnet or `/27` pool to present
- explicit `/32` host mappings, if required
- SmartGateway or downstream route expectations

Placement intent:

- preferred backend assignment, if any
- active and standby head-end expectation
- customer-side public IP change expectation
- whether there is an approved reason to disable the default NAT-T
  auto-promotion workflow

Operational readiness:

- current muxer backup location
- current VPN head-end backup location
- current customer-side config backup location
- current route and firewall backup location
- rollback decision point
- validation timeout
- owner who can approve rollback

## Recommended Workspace Variables

Run commands from the repo root:

```powershell
cd "E:\Code1\muxingRPDB Platform Framework-main"
```

Set a customer name for repeatable command examples:

```powershell
$CustomerName = "example-customer-0001"
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

Choose the default initial environment binding file:

```powershell
$EnvironmentFile = "muxer\config\environment-defaults\rpdb-empty-nonnat-active-a.yaml"
```

For a reviewed NAT-T promotion package, switch to the NAT binding:

```powershell
$EnvironmentFile = "muxer\config\environment-defaults\rpdb-empty-nat-active-a.yaml"
```

## Step 1: Create The Customer Request

Start from the committed examples:

- `muxer\config\customer-requests\examples\example-dynamic-default-nonnat.yaml`
- `muxer\config\customer-requests\examples\example-service-intent-netmap.yaml`
- `muxer\config\customer-requests\examples\example-service-intent-explicit-host-map.yaml`

Create a new request file:

```powershell
Copy-Item `
  "muxer\config\customer-requests\examples\example-dynamic-default-nonnat.yaml" `
  $Request
```

Edit the request with verified customer facts only. Do not invent peer IPs,
selectors, PSK paths, or NAT pools.

Minimum normal request shape:

```yaml
schema_version: 1

customer:
  name: example-customer-0001
  peer:
    public_ip: 198.51.100.45
    remote_id: 198.51.100.45
    psk_secret_ref: /muxingrpdb/customers/example-customer-0001/psk
  selectors:
    local_subnets:
      - 172.31.54.39/32
      - 194.138.36.80/28
    remote_subnets:
      - 10.129.3.154/32
```

Do not add `customer_class` or `backend.cluster` for normal onboarding. The
allocator defaults the initial package to strict non-NAT and records dynamic
NAT-T promotion as enabled. If the muxer later observes UDP/4500 from the same
peer, process that observation to generate a reviewed NAT-T package.

Post-IPsec NAT one-to-one `/27` example:

```yaml
post_ipsec_nat:
  enabled: true
  mode: netmap
  mapping_strategy: one_to_one
  real_subnets:
    - 10.129.3.128/27
  translated_subnets:
    - 172.30.0.64/27
  core_subnets:
    - 172.31.54.39/32
    - 194.138.36.80/28
```

Explicit host mapping example:

```yaml
post_ipsec_nat:
  enabled: true
  mode: explicit_map
  mapping_strategy: explicit_host_map
  translated_subnets:
    - 172.30.0.64/27
  real_subnets:
    - 10.129.3.154/32
    - 10.129.3.155/32
  host_mappings:
    - real_ip: 10.129.3.154/32
      translated_ip: 172.30.0.70/32
    - real_ip: 10.129.3.155/32
      translated_ip: 172.30.0.71/32
  core_subnets:
    - 172.31.54.39/32
    - 194.138.36.80/28
```

## Preferred: Prepare The Complete Pilot Package

Use this command for the normal repo-only onboarding path. It validates the
request, provisions allocations, renders artifacts, exports the handoff, binds
the environment, assembles the bundle, validates it, exercises staged head-end
install/validate/remove, and writes readiness output.

```powershell
python muxer\scripts\prepare_customer_pilot.py $Request `
  --out-dir $WorkRoot `
  --environment-file $EnvironmentFile `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

For a reviewed dynamic NAT-T promotion event, include the observation file:

```powershell
python muxer\scripts\prepare_customer_pilot.py $Request `
  --observation "$WorkRoot\nat-t-observation.json" `
  --out-dir $WorkRoot `
  --environment-file $EnvironmentFile `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

Review these primary outputs:

- `$WorkRoot\pilot-readiness.json`
- `$WorkRoot\README.md`
- `$WorkRoot\bundle-validation.json`
- `$WorkRoot\double-verification.json`
- `$WorkRoot\bundle\`

The remaining steps in this runbook are the lower-level manual path and the
debug path behind the pilot builder.

## Step 2: Validate The Request

```powershell
python muxer\scripts\validate_customer_request.py $Request
```

Optional expanded view:

```powershell
python muxer\scripts\validate_customer_request.py $Request --show-request
```

Do not continue if validation fails.

## Step 3: Provision And Reserve Allocations

Provision the request into an allocated compatibility customer source, merged
runtime module, DynamoDB item, and allocation summary:

```powershell
python muxer\scripts\provision_customer_request.py $Request `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --source-out $AllocatedSource `
  --module-out $CustomerModule `
  --item-out $CustomerDdbItem `
  --allocation-out $AllocationSummary
```

Review the allocated values:

```powershell
Get-Content $AllocationSummary
Get-Content $AllocatedSource
```

Expected review points:

- customer ID is in the expected NAT or non-NAT band
- fwmark is unique
- route table is unique
- RPDB priority is unique
- tunnel key is unique
- overlay block is unique
- generated interface name is unique
- backend assignment matches the requested class

Do not write the customer item or allocation records to a live table in this
step. The generated JSON files are review artifacts.

## Step 4: Validate The Allocated Customer Source

```powershell
python muxer\scripts\validate_customer_source.py $AllocatedSource
```

Optional merged view:

```powershell
python muxer\scripts\validate_customer_source.py $AllocatedSource --show-merged
```

## Optional: Plan Dynamic NAT-T Promotion

Use this only when the customer was intentionally started as strict non-NAT and
the muxer later observes UDP/4500 from the same peer.

This step is repo-only. It creates an audited NAT-T promotion package. It does
not modify live muxer state, live head-end state, or DynamoDB.

```powershell
$Observation = "$WorkRoot\nat-t-observation.json"
$DynamicOutDir = "$WorkRoot\dynamic-nat-t"
```

Write the observation event:

```powershell
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

Process the observation and stage the full promotion package:

```powershell
python muxer\scripts\process_nat_t_observation.py $Request `
  --observation $Observation `
  --out-dir $DynamicOutDir `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

Run the same command again. The second result should report
`status: already_planned` and `new_allocation_created: false`.

Validate the staged promoted artifacts using the paths returned in the JSON:

```powershell
python muxer\scripts\validate_customer_request.py `
  "$DynamicOutDir\$CustomerName\IDEMPOTENCY_KEY\promoted-nat-request.yaml"

python muxer\scripts\validate_customer_source.py `
  "$DynamicOutDir\$CustomerName\IDEMPOTENCY_KEY\promoted-customer-source.yaml"
```

Review:

- `$AllocationSummary` should show the initial non-NAT pool allocation
- the promoted allocation summary should show the proposed NAT pool allocation
- the audit record should show `live_apply: false`
- duplicate processing should not create a new allocation
- the promoted request should enable UDP/4500
- old non-NAT reservations should not be released until the live promotion has
  either succeeded or rollback ownership says they can be released

## Step 5: Render Customer Artifacts

```powershell
python muxer\scripts\render_customer_artifacts.py $AllocatedSource `
  --out-dir $RenderDir `
  --source-ref $AllocatedSource
```

Validate the render:

```powershell
python muxer\scripts\validate_rendered_artifacts.py $RenderDir
```

Review these rendered outputs:

- muxer module
- muxer routing intent
- muxer policy intent
- head-end IPsec intent
- head-end route intent
- head-end post-IPsec NAT intent
- generated NAT snippets

## Step 6: Export The Framework Handoff

```powershell
python muxer\scripts\export_customer_handoff.py $AllocatedSource `
  --export-dir $HandoffDir `
  --muxer-dir "$RenderDir\muxer" `
  --headend-dir "$RenderDir\headend" `
  --source-ref $AllocatedSource
```

Review the handoff directory:

```powershell
Get-ChildItem -Recurse $HandoffDir
```

The handoff is the boundary between customer modeling and deployment packaging.

## Step 7: Bind To An Environment

Validate the selected environment file:

```powershell
python muxer\scripts\validate_environment_bindings.py $EnvironmentFile
```

Bind the handoff:

```powershell
python muxer\scripts\bind_rendered_artifacts.py $HandoffDir `
  --environment-file $EnvironmentFile `
  --out-dir $BoundDir
```

Validate the bound artifacts:

```powershell
python muxer\scripts\validate_bound_artifacts.py $BoundDir
```

Review the binding report:

```powershell
Get-Content "$BoundDir\binding-report.json"
```

Expected review points:

- no unresolved placeholders remain
- NAT customers bind to NAT head-end placement
- strict non-NAT customers bind to non-NAT head-end placement
- public identity matches the target platform
- head-end underlay matches the target environment
- muxer transport values match the target environment

## Step 8: Assemble And Validate The Customer Bundle

```powershell
python scripts\packaging\assemble_customer_bundle.py `
  --customer-name $CustomerName `
  --bundle-dir $BundleDir `
  --export-dir $BoundDir
```

Validate the bundle:

```powershell
python scripts\packaging\validate_customer_bundle.py $BundleDir
```

Rebuild the manifest if needed:

```powershell
python scripts\packaging\build_customer_bundle_manifest.py $BundleDir
```

Review:

```powershell
Get-Content "$BundleDir\manifest.txt"
Get-Content "$BundleDir\sha256sums.txt"
```

## Step 9: Exercise Staged Head-End Install, Validate, And Remove

Install into a staged filesystem root only:

```powershell
python scripts\deployment\apply_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

Validate the staged install:

```powershell
python scripts\deployment\validate_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

Remove from the staged root:

```powershell
python scripts\deployment\remove_headend_customer.py `
  --bundle-dir $BundleDir `
  --headend-root $HeadendRoot
```

Validate removal by inspecting the staged root:

```powershell
Get-ChildItem -Recurse $HeadendRoot
```

This stage proves the customer-scoped apply/remove model without touching a
real head end.

## Step 10: Run Double Verification

When using separate framework and deployment worktrees, run:

```powershell
python scripts\deployment\run_double_verification.py `
  --framework-repo "E:\Code1\muxingRPDB Platform Framework-main" `
  --deployment-repo "E:\Code1\muxingRPDB Platform Framework-main" `
  --customer-source $AllocatedSource `
  --environment-file $EnvironmentFile `
  --baseline-dir "E:\Code1\muxingRPDB Platform Framework-main\build\verification-fixtures\pre-rpdb-baseline" `
  --operator "rpdb-operator" `
  --change-summary "Prepare RPDB customer onboarding package for $CustomerName"
```

The command may use the same repo path for both arguments when the framework and
deployment code are merged into one checkout. If separate branches or worktrees
are restored later, point each argument at the appropriate checkout.

Review the generated summary under:

```text
build\double-verification\<customer-name>\double-verification-summary.json
```

Do not continue if any step fails.

## Step 11: Deployment Readiness Check

Run readiness against the reviewed bundle and backup baseline:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name $CustomerName `
  --bundle-dir $BundleDir `
  --baseline-dir "build\verification-fixtures\pre-rpdb-baseline" `
  --json
```

If a rollout-specific pre-change note or rollback note exists, include it:

```powershell
python scripts\deployment\deployment_readiness_check.py `
  --customer-name $CustomerName `
  --bundle-dir $BundleDir `
  --baseline-dir "build\verification-fixtures\pre-rpdb-baseline" `
  --prechange-backup-note "$WorkRoot\notes\prechange.md" `
  --rollback-notes "$WorkRoot\notes\rollback.md" `
  --json
```

## Step 12: Human Review Gate

Before live deployment, review:

- customer request YAML
- allocated customer source YAML
- customer module JSON
- customer DynamoDB item JSON
- allocation summary JSON
- environment binding report
- muxer artifacts
- head-end IPsec artifacts
- head-end route artifacts
- post-IPsec NAT artifacts
- bundle manifest
- bundle checksums
- double-verification summary
- rollout notes
- rollback notes
- backup locations

The review must explicitly answer:

- which customer is being changed
- which public IP the customer will use
- which muxer public identity is active
- which NAT or non-NAT head end will terminate the tunnel
- whether the customer side must change its peer IP
- whether SmartGateway or downstream routing must change
- what exact validation proves success
- what exact validation triggers rollback
- who can approve rollback

## Live Deployment Stop Point

Stop after artifact review unless the change window is approved.

Live deployment is a separate operation and should use the customer-scoped
bundle, backups, and rollback notes created above.

Do not convert repo-only commands into live commands by changing paths to
`/etc`, `/usr/local/sbin`, live DynamoDB tables, or live head-end roots without a
separate deployment approval.

## Post-Deployment Validation Checklist

After an approved live deployment, validate in this order:

- muxer customer item can be read
- muxer customer-specific fwmark exists
- muxer customer-specific RPDB rule exists
- muxer route table points to the expected GRE interface
- muxer GRE interface is up
- NAT or non-NAT head-end GRE interface is up
- head-end IPsec configuration exists
- head-end IPsec SA is established
- post-IPsec NAT rules exist when required
- packet capture proves ingress from customer
- packet capture proves decrypt on head end
- packet capture proves post-IPsec NAT when required
- packet capture proves traffic reaches the core destination
- packet capture proves return traffic reaches the head end
- packet capture proves return traffic reaches the customer
- application-level test passes

## Rollback Checklist

Rollback should be tied to the captured backups and customer-specific bundle.

Typical rollback steps:

- stop new customer-side traffic toward the RPDB public identity
- remove customer-scoped head-end artifacts
- remove customer-scoped muxer runtime state
- restore prior VPN head-end config if it was modified
- restore prior route/firewall state if it was modified
- restore customer-side peer settings if they were changed
- remove or disable the RPDB customer SoT item if it was written
- mark or release resource allocations according to the rollback decision
- validate the old path again

Do not release allocator reservations until the rollback owner confirms whether
the customer will retry on RPDB or remain on the old platform.

## Common Failure Gates

Stop and fix before moving forward when:

- customer request validation fails
- allocation validation finds a collision
- rendered artifacts contain unresolved placeholders
- environment binding points to the wrong head-end class
- bundle validation fails
- staged head-end apply fails
- staged head-end validation fails
- staged head-end removal fails
- double verification fails
- backup baseline is missing
- rollback notes are incomplete
- SSM or SSH management path is not accepted for the change window
- live customer facts do not match the request

## Current Recommended Next Action

For the first real RPDB pilot:

1. select the pilot customer
2. build the customer request from live facts
3. run the repo-only onboarding flow through double verification
4. review every artifact
5. stop for deployment approval
