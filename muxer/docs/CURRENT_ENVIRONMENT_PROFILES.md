# Current Environment Profiles

## Goal

Keep the RPDB framework reusable while still documenting the current dev
environment bindings we will use during migration validation.

These files are not customer data. They are deployment-side bindings for the
current live estate as of April 13, 2026.

## Files

- [current-dev-nat-active-a.yaml](../config/environment-defaults/current-dev-nat-active-a.yaml)
- [current-dev-nonnat-active-a.yaml](../config/environment-defaults/current-dev-nonnat-active-a.yaml)
- [rpdb-empty-nat-active-a.yaml](../config/environment-defaults/rpdb-empty-nat-active-a.yaml)
- [rpdb-empty-nonnat-active-a.yaml](../config/environment-defaults/rpdb-empty-nonnat-active-a.yaml)
- [example-environment.yaml](../config/environment-defaults/example-environment.yaml)

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

## RPDB Empty Platform Bindings

Shared values:

- muxer public VPN IP: `13.221.247.80`
- muxer public-side private IP: `172.31.141.2`
- muxer transport IP: `172.31.127.237`
- muxer transport interface: `ens35`

RPDB-empty NAT active A:

- backend/head-end primary IP: `172.31.40.222`
- head-end core IP: `172.31.55.122`
- clear-side interface: `ens36`

RPDB-empty non-NAT active A:

- backend/head-end primary IP: `172.31.40.223`
- head-end core IP: `172.31.59.221`
- clear-side interface: `ens36`

## Notes

- These profiles intentionally carry a placeholder `PSK_FROM_SECRET_REF` value.
- The framework stays secret-free by resolving real PSKs outside repo content.
- Additional environment profiles can be added later for standby nodes, other
  AWS accounts, or other regions.
