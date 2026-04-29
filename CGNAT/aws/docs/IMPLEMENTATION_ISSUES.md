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
