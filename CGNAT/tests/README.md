# CGNAT Tests

These tests stay inside the `CGNAT/` workspace and exercise the current local
framework contract.

Current coverage:

- workspace boundary enforcement for output paths
- end-to-end local rendering of:
  - framework artifacts
  - AWS package artifacts
  - server package artifacts
- Scenario 1 local preparation orchestration without deployment
- Scenario 1 host-apply package generation without remote execution

Run with:

```powershell
python CGNAT\tests\run_tests.py
```
