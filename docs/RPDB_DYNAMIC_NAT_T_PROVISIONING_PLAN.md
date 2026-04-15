# RPDB Dynamic NAT-T Provisioning Plan

## Boundary

This plan is RPDB-only.

Allowed workspace:

- `E:\Code1\muxingRPDB Platform Framework-main`

Not allowed in this plan:

- changes to `E:\Code1\MUXER3`
- changes to legacy MUXER3 GitHub repositories
- live node changes
- production DynamoDB writes
- live muxer or VPN head-end apply
- customer cutover

## Goal

Provision a new customer safely when the real VPN encapsulation is not known
yet.

The default first package starts as strict non-NAT:

- UDP/500 is enabled
- ESP protocol 50 is enabled
- UDP/4500 is disabled
- backend placement is the non-NAT stack

If the muxer later observes UDP/4500 from the same customer peer, RPDB should
produce a reviewed NAT-T promotion package:

- customer class changes to `nat`
- backend placement changes to the NAT-T stack
- UDP/4500 is enabled
- NAT allocation pools are used
- the old non-NAT package is not mutated in place by the planner
- no live apply happens without a separate approval gate

## Project Stages

### Stage 1: Checkpoint

Verify current Git state and identify any uncommitted RPDB-only work.

Validation:

- `git status --short --branch`
- confirm all dirty paths are under `E:\Code1\muxingRPDB Platform Framework-main`

### Stage 2: Model The Intent

Add `dynamic_provisioning` as a first-class customer request/source section.

The model records:

- initial class: `strict-non-nat`
- initial backend: `non-nat`
- trigger: UDP destination port `4500`
- promotion target: `nat`
- promotion backend: `nat`

Validation:

- request schema accepts the new section
- source schema accepts the new section after allocation
- merged customer module carries the section for auditability

### Stage 3: Add Repo-Only Promotion Planning

Add a helper that receives:

- current customer request or allocated source
- observed peer IP
- observed protocol
- observed destination port
- whether UDP/500 was observed first when required

The helper outputs:

- promoted NAT customer request YAML
- promotion summary JSON

The helper must not:

- write to live DynamoDB
- touch live nodes
- apply iptables/nftables
- modify the source customer file in place

Validation:

- peer IP must match the customer peer
- observed protocol must be UDP
- observed destination port must be `4500`
- initial customer must be strict non-NAT
- initial effective protocols must be UDP/500 + ESP/50 with UDP/4500 disabled
- promoted request must validate as a NAT request

### Stage 4: Provision Both Packages Repo-Only

Use existing provisioning to create:

- initial non-NAT allocation package
- promoted NAT-T allocation package
- observation audit record
- idempotency key for the UDP/4500 trigger

Validation:

- initial package allocates from non-NAT pools
- promoted package allocates from NAT pools
- promoted package can use `--replace-customer` to ignore the old same-name
  package during planning
- reprocessing the same observation returns the existing audit/artifacts
  instead of allocating again
- neither package is applied live

### Stage 5: Document Operator Flow

Update onboarding docs so operators understand the safe workflow:

- start non-NAT by default when NAT-T is unknown
- observe UDP/4500 as the trigger for NAT-T promotion
- generate and review a NAT promotion package
- stop before live deployment

Validation:

- user guide includes the plain-language flow
- engineering runbook includes command examples
- stop gates remain explicit

### Stage 6: Full Repo Verification

Run repo-only verification after every stage is complete.

Validation:

- Python compile checks pass
- request validation passes
- initial non-NAT provisioning passes
- NAT-T observation processing passes
- duplicate NAT-T observation idempotency passes
- promoted NAT provisioning passes
- render/package/staged head-end validation still passes
- full repo verification passes

### Stage 7: Commit And Push

Only after validation passes:

- commit RPDB-only changes
- push to GitHub
- confirm `HEAD == origin/main`
- confirm working tree is clean

## Live Deployment Gate

This plan ends before live deployment.

Live migration requires a separate approved plan with:

- exact customer
- exact muxer instance
- exact NAT or non-NAT head end
- current-state backups
- rollback owner
- validation owner
- packet-capture validation commands
- human approval
