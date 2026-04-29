# AWS Scripts

AWS-side scripts belong here.

The framework render and validation tooling stays under
`CGNAT/framework/scripts/` because it is neutral framework tooling rather than
AWS-only logic.

Current AWS-side builder:

- `render_aws_package.py`
- `deploy_scenario1_aws.py`

Usage:

```powershell
python CGNAT\aws\scripts\render_aws_package.py `
  CGNAT\build\sample-from-split\deployment-bundle.json `
  CGNAT\build\sample-from-split\aws-package
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
  CGNAT\build\sample-from-split\aws-package `
  CGNAT\build\sample-from-split\aws-deploy-plan `
  --mode plan
```

Current behavior:

- `plan` mode writes deployment plan artifacts
- `apply` mode uses AWS EC2 DryRun by default
- `apply --execute-live` is the real create path once review is complete
