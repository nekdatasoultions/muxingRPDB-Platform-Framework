# Server-Side Scripts

Server-side scripts belong here.

Current server-side builder:

- `render_server_package.py`
- `render_scenario1_server_configs.py`
- `materialize_scenario1_demo_materials.py`
- `prepare_scenario1_host_apply.py`
- `prepare_scenario1_remote_apply_plan.py`
- `execute_scenario1_remote_apply_plan.py`

Usage:

```powershell
python CGNAT\server\scripts\render_server_package.py `
  CGNAT\framework\config\deployment-bundle.example.json `
  CGNAT\build\sample\server-package
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
  CGNAT\build\sample\server-package `
  CGNAT\build\sample\server-configs
```

This renders:

- head-end structured config
- ISP-side structured config
- customer-router structured config
- backend validation expectations
- runtime input manifest
- runtime environment file
- validation command sheet
- strongSwan `swanctl.conf` fragments
- Linux iproute2 GRE/route scripts
- per-customer-router inner-tunnel config and loopback setup scripts

Demo material generation:

```powershell
python CGNAT\server\scripts\materialize_scenario1_demo_materials.py `
  CGNAT\framework\config\deployment-bundle.rpdb-empty-live.json `
  CGNAT\build\rpdb-empty-live\demo-materials
```

This prepares:

- demo outer-tunnel CA material
- demo head-end server cert/key
- demo ISP-side client cert/key
- demo inner-VPN PSK material
- a materials manifest for host-apply packaging

Host apply packaging:

```powershell
python CGNAT\server\scripts\prepare_scenario1_host_apply.py `
  CGNAT\build\sample\server-configs `
  CGNAT\build\sample\host-apply `
  --materials-manifest-json CGNAT\build\rpdb-empty-live\demo-materials\materials-manifest.json
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
  CGNAT\build\sample\host-apply `
  CGNAT\server\config\host-access.example.json `
  CGNAT\build\sample\remote-apply-plan
```

This prepares:

- remote stage command scripts
- remote apply command scripts
- a no-execution remote apply manifest

Remote apply execution planning:

```powershell
python CGNAT\server\scripts\execute_scenario1_remote_apply_plan.py `
  CGNAT\build\sample\remote-apply-plan `
  CGNAT\build\sample\remote-apply-execution `
  --mode plan
```

This prepares:

- an execution plan
- an execution readiness report
- optional live execution path when explicitly invoked later
