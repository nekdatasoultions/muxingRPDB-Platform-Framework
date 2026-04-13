# Stack SoT - us-east-1

Note:
- this file is a historical stack snapshot from an earlier deployment state
- it is not the current runtime reference for the Graviton strongSwan head-end cutover
- for the live runtime view, use:
  - `HEADEND_RUNTIME_STATUS.md`
  - `..\inventory\current-stack-summary.us-east-1.md`

Generated from live AWS state after deploying:
- `muxer-cluster-prod-us-east-1`
- `vpn-headend-non-nat-us-east-1`
- `vpn-headend-nat-us-east-1`

## Environment

- Region: `us-east-1`
- VPC: `vpc-0f74bd28e5a4239a2`
- Subnets:
  - `subnet-04a6b7f3a3855d438` (`us-east-1a`)
  - `subnet-0cc9697bd58c319ec` (`us-east-1b`)
- AMI: `ami-0f3caa1cf4417e51b`
- Instance type: `t3.medium`
- Key pair: `muxer`
- Disk layout:
  - OS: `/dev/xvda` 16 GiB
  - Logging: `/dev/sdf` 30 GiB mounted to `/LOG`
  - Application: `/dev/sdg` 80 GiB mounted to `/Application`

## Muxer Cluster

- Stack: `muxer-cluster-prod-us-east-1`
- Cluster: `muxer-cluster-prod`
- Security group: `sg-0d3b1b66a98ef8af8`
- Lease table: `muxer-cluster-prod-us-east-1-MuxerLeaseTable-PO1V71P3LWS1`
- Nodes:
  - A: `i-03f05bedef2d9ba02`, `172.31.42.35`, `eni-0b1ce5271f2fb83a8`
  - B: `i-031e6965c7a999166`, `172.31.142.208`, `eni-0f28538abb1c46427`

## VPN Headend Cluster - Non NAT

- Stack: `vpn-headend-non-nat-us-east-1`
- Cluster: `vpn-headend-non-nat`
- Security group: `sg-08b665a543da0b838`
- Lease table: `vpn-headend-non-nat-us-east-1-HaLeaseTable-1H9TB6MHZWVJR`
- Mode: `FlowSyncMode=conntrackd`, `SaSyncMode=libreswan-no-sa-sync`, `IpsecService=ipsec`
- Nodes:
  - A: `i-03fc7362e3c030a42`, `172.31.40.210`, `eni-011d444c4054043e3`
  - B: `i-07b1c0dbb9efeb29c`, `172.31.141.210`, `eni-0f2101e640f5093da`

## VPN Headend Cluster - NAT

- Stack: `vpn-headend-nat-us-east-1`
- Cluster: `vpn-headend-nat`
- Security group: `sg-087c119b69e1fdd1b`
- Lease table: `vpn-headend-nat-us-east-1-HaLeaseTable-154XXHGAN1W2V`
- Mode: `FlowSyncMode=conntrackd`, `SaSyncMode=libreswan-no-sa-sync`, `IpsecService=ipsec`
- Nodes:
  - A: `i-0376a67c9c4ac5d0f`, `172.31.40.211`, `eni-0cdc9f66cca184bb6`
  - B: `i-09ca57bab451379ee`, `172.31.141.211`, `eni-051f24d4a6d1c4a14`

## SoT Files

- Machine-readable AWS snapshot: `config/sot.aws.us-east-1.json`
- NetBox-oriented SoT snapshot: `config/netbox-sot.us-east-1.yaml`
- Live regional manifest: `config/regional-deployment.json`
- Parameter files used:
  - `cfn/parameters.muxer.us-east-1.json`
  - `cfn/parameters.vpn-headend.non-nat.us-east-1.json`
  - `cfn/parameters.vpn-headend.nat.us-east-1.json`
