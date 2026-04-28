# SoT Lane

This lane holds source-of-truth assets:

- SoT interaction documents
- SoT example config

Use this lane for service intent and identity inputs owned by the source of
truth.

For the current design, this lane assumes CGNAT-owned SoT shapes even if the
same underlying database platform is reused.

Useful reference:

- [Backend Contract Map](../framework/docs/SHARED_INTEGRATION_MAP.md)
- [SoT Record Shape](./docs/SOT_RECORD_SHAPE.md)
- [SoT Service Example](./config/cgnat-service-record.example.json)
