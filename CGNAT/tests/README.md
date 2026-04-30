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
- backend reuse request generation and deployment-stage review logic

Run with:

```powershell
python CGNAT\tests\run_tests.py
```

Full dry-run regression:

```powershell
python CGNAT\tests\run_regression.py
```

That regression runner executes the unit test suite, `compileall`, the sample
Scenario 1 prep flow, the live-bundle prep flow with demo materials, AWS
dry-run apply, backend integration dry-run, and the combined deployment-stage
review without touching live infrastructure.
