# Current Environment Profiles

## Goal

Keep the RPDB framework reusable while still documenting the current dev
environment bindings we will use during migration validation.

These files are not customer data. They are deployment-side bindings for the
current live estate as of April 13, 2026.

## Files

- [current-dev-nat-active-a.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/environment-defaults/current-dev-nat-active-a.yaml)
- [current-dev-nonnat-active-a.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/environment-defaults/current-dev-nonnat-active-a.yaml)
- [example-environment.yaml](/E:/Code1/muxingRPDB%20Platform%20Framework/muxer/config/environment-defaults/example-environment.yaml)

## Current Dev Bindings

Shared values:

- muxer public VPN IP: `54.204.221.89`
- muxer public-side private IP: `172.31.34.89`
- muxer transport IP: `172.31.69.213`
- muxer transport interface: `ens34`

NAT active A:

- backend/head-end primary IP: `172.31.40.221`
- head-end core IP: `172.31.55.121`
- clear-side interface: `ens36`

Non-NAT active A:

- backend/head-end primary IP: `172.31.40.220`
- head-end core IP: `172.31.59.220`
- clear-side interface: `ens36`

## Notes

- These profiles intentionally carry a placeholder `PSK_FROM_SECRET_REF` value.
- The framework stays secret-free by resolving real PSKs outside repo content.
- Additional environment profiles can be added later for standby nodes, other
  AWS accounts, or other regions.
