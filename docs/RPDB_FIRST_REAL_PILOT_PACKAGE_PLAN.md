# RPDB First Real Pilot Package Plan

## Boundary

This plan is RPDB-only.

Allowed workspace:

- `<repo-root>`

Not allowed in this plan:

- changes to `<legacy-muxer3-repo>`
- changes to legacy MUXER3 GitHub repositories
- SSH or SSM to live nodes
- production DynamoDB writes
- live muxer apply
- live VPN head-end apply
- EIP movement
- customer cutover

## Goal

Use the repo-only pilot package builder to prepare the first real RPDB customer
pilot packages from verified customer facts.

This plan ends with a reviewable package and a human decision gate. It does not
deploy any customer.

## Inputs Needed

The pilot package requires:

- customer name
- NAT or strict non-NAT starting class
- customer peer public IP
- customer peer ID if different from public IP
- PSK secret reference
- local/core protected subnets
- remote/customer protected subnets
- target environment binding file
- whether post-IPsec NAT is required
- if post-IPsec NAT is required:
  - real customer-side subnet or host list
  - translated subnet or host list
  - core subnets participating in the translated path
- if dynamic NAT-T discovery is allowed:
  - default strict non-NAT request
  - reviewed UDP/4500 observation file when promotion is needed

## Stage 1: Select Pilot Customers

Pick pilot customers to model in RPDB.

Selection requirements:

- customer facts are known and verified
- customer can be represented without touching live systems
- customer request can be created or updated inside this repo
- default starting behavior is understood
- normal requests omit NAT/non-NAT and default to strict non-NAT first
- target environment binding file is known
- customer 3 variants are excluded while they are real-time/live customers

Validation:

- selected customers are named in the plan notes or package README
- no live system was queried by the package builder
- no MUXER3 files were modified

## Stage 2: Create Or Confirm Customer Request

Create or update customer request YAML files under:

- `muxer/config/customer-requests/`

Use committed examples as templates:

- `muxer/config/customer-requests/examples/example-minimal-nonnat.yaml`
- `muxer/config/customer-requests/examples/example-service-intent-netmap.yaml`
- `muxer/config/customer-requests/examples/example-service-intent-explicit-host-map.yaml`
- `muxer/config/customer-requests/examples/example-dynamic-default-nonnat.yaml`

Validation:

- request includes only customer/service intent
- request does not hand-assign allocator-owned resources
- request validates with `validate_customer_request.py`
- request stays inside the RPDB repo

## Stage 3: Run Repo-Only Pilot Builder

Run the primary command for each selected pilot customer:

```powershell
python muxer\scripts\prepare_customer_pilot.py muxer\config\customer-requests\<customer-name>.yaml `
  --out-dir build\customer-pilots\<customer-name> `
  --environment-file muxer\config\environment-defaults\<target-environment>.yaml `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

If dynamic NAT-T promotion is being reviewed, use:

```powershell
python muxer\scripts\prepare_customer_pilot.py muxer\config\customer-requests\<customer-name>.yaml `
  --observation build\customer-pilots\<customer-name>\nat-t-observation.json `
  --out-dir build\customer-pilots\<customer-name>-nat-t `
  --environment-file muxer\config\environment-defaults\<target-environment>.yaml `
  --existing-source-root muxer\config\customer-sources\examples `
  --existing-source-root muxer\config\customer-sources\migrated `
  --json
```

Validation:

- command exits successfully
- `pilot-readiness.json` exists
- readiness status is `ready_for_review`
- readiness has `live_apply: false`
- bundle validation is true
- double verification is true

## Stage 4: Review Pilot Package

Review these files:

- `pilot-readiness.json`
- `README.md`
- `customer-source.yaml`
- `customer-module.json`
- `customer-ddb-item.json`
- `allocation-summary.json`
- `allocation-ddb-items.json`
- `bundle-validation.json`
- `double-verification.json`
- `bundle/`

Review points:

- customer class is correct
- request did not preselect NAT or non-NAT unless the package is a promoted
  NAT-T artifact
- backend cluster is correct
- peer IP is correct
- local selectors are correct
- remote selectors are correct
- post-IPsec NAT intent is correct when used
- allocated customer ID is in the expected band
- fwmark is allocated
- route table is allocated
- RPDB priority is allocated
- tunnel key is allocated
- overlay block is allocated
- interface name is allocated
- bundle contains muxer artifacts
- bundle contains head-end artifacts
- staged head-end apply/validate/remove passed
- no live apply occurred

Validation:

- reviewer can trace request to allocated source
- reviewer can trace allocated source to module and DynamoDB item view
- reviewer can trace module to bundle artifacts
- reviewer can trace bundle to double verification

## Stage 5: Handle Blocked Package

If `pilot-readiness.json` reports `blocked`:

- stop
- read the readiness error
- fix the repo-only request/model/script issue
- rerun the pilot builder
- rerun full repo verification if code changed

Validation:

- do not proceed to live planning while blocked
- document the failure and fix in the commit message if code changed

## Stage 6: Full Repo Verification

After the first real pilot packages are generated and reviewed, run:

```powershell
python muxer\scripts\run_repo_verification.py --json
```

Validation:

- repo verification passes
- existing dynamic NAT-T verification still passes
- existing pilot-builder verification still passes
- no unrelated repo changes appear

## Stage 7: Commit And Push

If this stage creates or updates customer request files or docs:

```powershell
git diff --check
git status --short --branch
git add <changed-rpdb-files>
git commit -m "Add first RPDB pilot customer package inputs"
git push origin main
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Validation:

- local `main` matches `origin/main`
- working tree is clean
- changed files are only inside the RPDB repo

## Stage 8: Stop Before Live Deployment

This plan stops after repo-only package review.

Live deployment requires a separate approved plan with:

- exact customer
- exact muxer instance
- exact VPN head-end
- exact backup commands
- exact package apply commands
- packet-capture validation commands
- rollback commands
- rollback owner
- validation owner
- change window
- human approval

## Definition Of Done

This plan is complete when:

- the selected real customer requests exist or are confirmed in the RPDB repo
- `prepare_customer_pilot.py` produces packages for the selected customers
- each `pilot-readiness.json` says `ready_for_review`
- generated artifacts are reviewed
- full repo verification passes
- changes are committed and pushed if repo files changed
- no MUXER3 files were touched
- no live nodes were touched
- no production DynamoDB writes occurred

## Execution Checkpoint

Current repo-only pilot candidates:

- customer: `legacy-cust0002`
- request: `muxer/config/customer-requests/migrated/legacy-cust0002.yaml`
- stack selection in request: omitted; defaults to strict non-NAT
- package output: `build/customer-pilots/legacy-cust0002`
- environment binding: `muxer/config/environment-defaults/rpdb-empty-nonnat-active-a.yaml`
- package status: `ready_for_review`
- allocated customer ID: `2000`
- allocated fwmark: `0x2000`
- allocated route table: `2000`
- allocated tunnel key: `2000`
- live apply: `false`

- customer: `vpn-customer-stage1-15-cust-0004`
- request: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004.yaml`
- stack selection in request: omitted; defaults to strict non-NAT
- NAT-T observation: `muxer/config/customer-requests/migrated/vpn-customer-stage1-15-cust-0004-nat-t-observation.json`
- package output: `build/customer-pilots/vpn-customer-stage1-15-cust-0004`
- environment binding: `muxer/config/environment-defaults/rpdb-empty-nat-active-a.yaml`
- package status: `ready_for_review`
- allocated customer ID: `41000`
- allocated fwmark: `0x41000`
- allocated route table: `41000`
- allocated tunnel key: `41000`
- live apply: `false`

Excluded pilot candidates:

- `legacy-cust0003`
- `vpn-customer-stage1-15-cust-0003`

Reason:

- customer 3 variants are real-time/live customers and are not part of this
  repo-only pilot package exercise.

Important note:

- The generated pilot package is ignored by Git under `build/`.
- The committed source of truth for reproducing the package is the customer
  request plus the pilot builder command.
