# Server-Side Scripts

Server-side scripts belong here.

Current server-side builder:

- `render_server_package.py`
- `render_scenario1_server_configs.py`

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
