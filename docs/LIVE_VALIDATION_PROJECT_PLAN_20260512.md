# Live Validation Project Plan - 2026-05-12

## Goal

Validate the completed customer provisioning changes from the jump-host MOM
checkout at `/home/ec2-user/rpdb`, using the normal customer deployment and
removal scripts only.

## Guard Rails

- Run every live customer operation from the jump host.
- Commit and push code to GitHub and CodeCommit before syncing the jump host.
- Pull the latest code on the jump host before customer work begins.
- De-provision each customer before provisioning it.
- Work one customer/use case at a time.
- Do not move to the next customer until the current customer is fully
  provisioned and verified.
- Provide a status update at least every 2 minutes while a live operation is
  running or being verified.
- Keep generated private keys, local PSKs, and handoff material on the jump
  host only; do not commit those secrets to Git.
- Generate jump-host-only validation inputs with
  `scripts/customers/prepare_live_validation_requests.py`; the outputs live
  under `build/live-validation/`, which is intentionally gitignored.

## Use Cases

1. `vpn-customer-stage1-15-cust-0002`
   - Purpose: local PSK validation.
   - Pre-step: create a jump-host-only validation request with
     `customer.peer.psk_source: local`.
   - Environment requirement: use a live validation environment copy with
     `secrets.allow_local_psk: true`.
   - Flow: remove, deploy, verify head-end/muxer/SmartConnect state.

2. `vpn-customer-stage1-15-cust-0004`
   - Purpose: certificate-auth validation for a regular VPN customer.
   - Pre-step: issue a demo CA certificate bundle on the jump host.
   - Pre-step: install the customer-side certificate material on the customer
     VPN host, replacing its current PSK-side config for this test.
   - Flow: remove, deploy certificate-auth request, verify tunnel/auth state.

3. `vpn-customer-stage1-15-cust-0005`
   - Purpose: explicit inside-NAT host-map validation.
   - Pre-step: create a jump-host-only validation request using
     `post_ipsec_nat.mode: explicit_map` and
     `post_ipsec_nat.mapping_strategy: explicit_host_map`.
   - Flow: remove, deploy, verify nftables maps and SmartConnect translated
     route behavior.

4. CGNAT customers
   - Purpose: validate CGNAT customer deployment scripts with the new CA/provided
     certificate mechanism.
   - Pre-step: issue CGNAT demo CA bundles on the jump host.
   - Flow: remove, deploy with `scripts/customers/deploy_customer.py`, verify
     CGNAT deployment review, PKI material staging, CGNAT head-end state, and
     rollback/removal readiness.

## Execution Pattern

For each customer:

1. Build or update the jump-host-only validation request.
   Use:
   `python3 scripts/customers/prepare_live_validation_requests.py`
2. Run `scripts/customers/remove_customer.py --approve --json`.
3. Verify removal completed on all selected surfaces.
4. Run `scripts/customers/deploy_customer.py --approve --json`.
5. Verify execution-plan status is `applied`.
6. Verify component state and any use-case-specific behavior.
7. Record the result before moving to the next customer.
