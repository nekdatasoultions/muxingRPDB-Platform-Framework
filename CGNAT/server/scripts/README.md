# Server-Side Scripts

Server-side scripts belong here.

Current server-side builder:

- `render_server_package.py`
- `render_scenario1_server_configs.py`
- `prepare_scenario1_host_apply.py`
- `prepare_scenario1_remote_apply_plan.py`
- `execute_scenario1_remote_apply_plan.py`

Usage:

```powershell
python CGNAT\server\scripts\render_server_package.py `
  CGNAT\build\sample-from-split\deployment-bundle.json `
  CGNAT\build\sample-from-split\server-package
```

This renders server-side package artifacts only:

- package manifest
- CGNAT HEAD END tunnel and GRE handoff shape
- CGNAT ISP HEAD END path shape
- backend expectations
- validation targets

Concrete Scenario 1 config artifact render:

```powershell
python CGNAT\server\scripts\render_scenario1_server_configs.py `
  CGNAT\build\sample-from-split\server-package `
  CGNAT\build\sample-from-split\server-configs
```

This renders:

- head-end structured config
- ISP-side structured config
- backend validation expectations
- runtime input manifest
- runtime environment file
- validation command sheet
- strongSwan `swanctl.conf` fragments
- Linux iproute2 GRE/route scripts

Host apply packaging:

```powershell
python CGNAT\server\scripts\prepare_scenario1_host_apply.py `
  CGNAT\build\sample-from-split\server-configs `
  CGNAT\build\sample-from-split\host-apply
```

This prepares:

- per-host apply bundles
- preflight scripts
- apply scripts
- rollback notes
- validation bundle copy-outs

Remote apply command planning:

```powershell
python CGNAT\server\scripts\prepare_scenario1_remote_apply_plan.py `
  CGNAT\build\sample-from-split\host-apply `
  CGNAT\server\config\host-access.example.json `
  CGNAT\build\sample-from-split\remote-apply-plan
```

This prepares:

- remote stage command scripts
- remote apply command scripts
- a no-execution remote apply manifest

Remote apply execution planning:

```powershell
python CGNAT\server\scripts\execute_scenario1_remote_apply_plan.py `
  CGNAT\build\sample-from-split\remote-apply-plan `
  CGNAT\build\sample-from-split\remote-apply-execution `
  --mode plan
```

This prepares:

- an execution plan
- an execution readiness report
- optional live execution path when explicitly invoked later
