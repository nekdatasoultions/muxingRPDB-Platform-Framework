# AWS Scripts

AWS-side scripts belong here.

The framework render and validation tooling stays under
`CGNAT/framework/scripts/` because it is neutral framework tooling rather than
AWS-only logic.

Current AWS-side builder:

- `render_aws_package.py`

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
