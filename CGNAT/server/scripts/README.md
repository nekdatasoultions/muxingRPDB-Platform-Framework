# Server-Side Scripts

Server-side scripts belong here.

Current server-side builder:

- `render_server_package.py`

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
