# AWS Scripts

AWS-side scripts belong here.

The framework render and validation tooling stays under
`CGNAT/framework/scripts/` because it is neutral framework tooling rather than
AWS-only logic.

Current AWS-side builder:

- `render_aws_package.py`
- `deploy_scenario1_aws.py`
- `preflight_scenario1_aws.py`

Usage:

```powershell
python CGNAT\aws\scripts\render_aws_package.py `
  CGNAT\framework\config\deployment-bundle.example.json `
  CGNAT\build\sample\aws-package
```

This renders AWS deployment package artifacts only:

- package manifest
- CGNAT HEAD END infra shape
- CGNAT ISP HEAD END infra shape
- external dependency summary
- deployment order

Scenario 1 plan/apply scaffold:

```powershell
python CGNAT\aws\scripts\deploy_scenario1_aws.py `
  CGNAT\build\sample\aws-package `
  CGNAT\build\sample\aws-deploy-plan `
  --mode plan
```

To add only customer-side VPN router instances from a reviewed package, keep the
existing CGNAT headend and ISP roles out of the create plan:

```powershell
python CGNAT\aws\scripts\deploy_scenario1_aws.py `
  CGNAT\build\sample\aws-package `
  CGNAT\build\sample\aws-deploy-plan-routers-only `
  --mode plan `
  --role-scope customer-vpn-routers
```

Current behavior:

- `plan` mode writes deployment plan artifacts
- `apply` mode uses AWS EC2 DryRun by default
- `apply --execute-live` is the real create path once review is complete
- `--role-scope customer-vpn-routers` creates a router-only plan so existing
  CGNAT headend and ISP gateway instances are not recreated
- `apply` falls back to the AWS CLI when `boto3` is not available on the local
  machine

Live AWS preflight:

```powershell
python CGNAT\aws\scripts\preflight_scenario1_aws.py `
  CGNAT\build\rpdb-empty-live\scenario1-prep\aws-package `
  CGNAT\build\rpdb-empty-live\scenario1-prep\aws-preflight
```

This checks the real AWS environment against the rendered package without
creating infrastructure. Treat `hard_no_go` findings as true stop conditions
for live apply.
