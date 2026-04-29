# AWS Implementation Issues

## Purpose

This document records concrete AWS-side implementation issues discovered while
turning the CGNAT Scenario 1 plan into executable deployment tooling.

The goal is to document blockers clearly, keep moving, and avoid losing
important deployment assumptions in chat history alone.

## Issue 1: Current AWS Package Is Not Yet Sufficient for Live EC2 Creation

### Status

- resolved for the current Scenario 1 contract

### Discovered During

- initial implementation of `deploy_scenario1_aws.py`

### Summary

The current Scenario 1 AWS package is good enough to express:

- role placement
- instance naming
- instance type
- subnet usage
- EIP association intent

But it is not yet sufficient to safely create EC2 instances.

### Missing Launch Inputs

The original AWS package did not yet define required launch values such as:

- AMI ID
- security group IDs
- IAM instance profile

Those minimum fields are now being added to the CGNAT AWS package and consumed
by the Scenario 1 deploy planner.

The Scenario 1 contract now also defines:

- optional key pair policy
- root volume policy
- default tagging policy

### Why This Matters

Without these values, a live deployment script would have to guess at launch
behavior, and that would violate the current CGNAT deployment safety model.

### Current Handling

The first Scenario 1 AWS deploy script should:

- support plan/dry-run mode
- detect and report missing launch inputs
- refuse live apply when required launch inputs are not available

### Resolution

For the current Scenario 1 contract, the AWS package now carries enough launch
shape to produce:

- concrete EC2 `run_instances` request payloads
- post-create EIP association intent
- readiness evaluation for dry-run and later live execution

Remaining caution before live deployment is now operational review, not missing
launch-shape definition.

## Issue 2: Scenario 1 ISP HEAD END Cannot Span the Current Fixed Subnets

### Status

- open hard no-go for `rpdb-empty-live`

### Discovered During

- live AWS preflight for `deployment-bundle.rpdb-empty-live.json`

### Summary

The current Scenario 1 placement rule says the CGNAT ISP HEAD END must attach
to:

- transit subnet `subnet-04a6b7f3a3855d438`
- customer subnet `subnet-0e6ae1d598e08d002`

In the live AWS environment, those subnets are in different availability
zones:

- `subnet-04a6b7f3a3855d438` -> `us-east-1a`
- `subnet-0e6ae1d598e08d002` -> `us-east-1b`

A single EC2 instance cannot attach ENIs across different availability zones.

### Why This Matters

This is not a documentation mismatch or a soft warning. It is a real
infrastructure constraint that prevents live deployment of the current
single-instance CGNAT ISP HEAD END model in `rpdb-empty-live`.

### Current Handling

The live preflight now detects this condition and raises:

- `isp_head_end_subnet_az_mismatch`
- severity: `hard_no_go`

### What Must Change Before Live Apply

At least one of these must happen:

- choose a customer-facing subnet in the same AZ as the transit subnet
- choose a transit subnet in the same AZ as the customer-facing subnet
- redesign the CGNAT ISP HEAD END away from a single EC2 instance with ENIs in
  both subnets

Until one of those changes is made, Scenario 1 cannot safely move into live
infrastructure apply for this environment.
