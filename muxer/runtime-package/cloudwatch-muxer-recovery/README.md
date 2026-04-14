# Muxer Recovery Lambda

This Lambda is the convergence layer for the single-muxer recovery model.

It is intended to run on a schedule and after instance replacement events.

## Responsibilities

For the target Auto Scaling Group it will:

1. select the best current muxer instance
2. attach the correct transport ENI for that instance AZ
3. reassociate the shared EIP
4. update `/etc/muxer/config/muxer.yaml` with:
   - actual public interface
   - actual transport interface
   - DynamoDB customer SoT settings
5. restart `muxer.service`

## Inputs

Environment variables:

- `ASG_NAME`
- `EIP_ALLOCATION_ID`
- `TRANSPORT_ENI_A`
- `TRANSPORT_ENI_B`
- `CUSTOMER_SOT_TABLE`
- `MUXER_SERVICE_NAME`

## Packaging

Package and upload with:

```bash
bash "E:\Code1\Muxingplus HA\scripts\package_muxer_recovery_lambda_to_s3.sh" \
s3://baines-networking/Code/muxingRPDB-Platform-Framework/muxer-recovery-lambda.zip
```

The CloudFormation stack uses that uploaded object when creating the recovery Lambda.
