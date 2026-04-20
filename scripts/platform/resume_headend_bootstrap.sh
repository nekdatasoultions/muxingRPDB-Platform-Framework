#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  resume_headend_bootstrap.sh <cluster_id> <node_id> <region> <lease_table> <eip_alloc_id> <eni_id> <sync_peer_ip> <primary_if> <primary_ip> <sync_if> <sync_ip> <core_if> <core_ip> [project_package_s3_uri] [shared_efs_fs_id] [shared_efs_ap_id]

Or:
  resume_headend_bootstrap.sh \
    --cluster-name <cluster_id> \
    --node-name <node_id> \
    --region <region> \
    --lease-table <lease_table> \
    --eip-allocation-id <eip_alloc_id> \
    --eni-id <eni_id> \
    --sync-peer-ip <sync_peer_ip> \
    --primary-interface <primary_if> \
    --primary-ip <primary_ip> \
    --sync-interface <sync_if> \
    --sync-ip <sync_ip> \
    --core-interface <core_if> \
    --core-ip <core_ip> \
    [--ipsec-service <ipsec_service>] \
    [--ipsec-backend <ipsec_backend>] \
    [--sa-sync-mode <sa_sync_mode>] \
    [--flow-sync-mode <flow_sync_mode>] \
    [--strongswan-archive-uri <archive_uri>] \
    [--s3-package-uri <project_package_s3_uri>] \
    [--shared-efs-fs-id <shared_efs_fs_id>] \
    [--shared-efs-ap-id <shared_efs_ap_id>] \
    [--shared-dir <shared_dir>]
EOF
}

PROJECT_PACKAGE_S3_URI="s3://baines-networking/Code/muxingRPDB-Platform-Framework/rpdb-platform-bundle.zip"
SHARED_EFS_FS_ID=""
SHARED_EFS_AP_ID=""
SHARED_DIR="/Shared"
IPSEC_SERVICE="ipsec"
IPSEC_BACKEND="libreswan"
SA_SYNC_MODE="libreswan-no-sa-sync"
FLOW_SYNC_MODE="conntrackd"
STRONGSWAN_ARCHIVE_URI=""

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

if [[ "$1" == --* ]]; then
  HA_CLUSTER_ID=""
  HA_NODE_ID=""
  HA_REGION=""
  HA_DDB_TABLE=""
  HA_EIP_ALLOC_ID=""
  HA_ENI_ID=""
  HA_SYNC_PEER_IP=""
  HA_PRIMARY_INTERFACE=""
  HA_PRIMARY_LOCAL_IP=""
  HA_SYNC_INTERFACE=""
  HA_SYNC_LOCAL_IP=""
  HA_CORE_INTERFACE=""
  HA_CORE_LOCAL_IP=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --cluster-name)
        HA_CLUSTER_ID="$2"
        shift 2
        ;;
      --node-name)
        HA_NODE_ID="$2"
        shift 2
        ;;
      --region)
        HA_REGION="$2"
        shift 2
        ;;
      --lease-table)
        HA_DDB_TABLE="$2"
        shift 2
        ;;
      --eip-allocation-id)
        HA_EIP_ALLOC_ID="$2"
        shift 2
        ;;
      --eni-id)
        HA_ENI_ID="$2"
        shift 2
        ;;
      --sync-peer-ip)
        HA_SYNC_PEER_IP="$2"
        shift 2
        ;;
      --primary-interface)
        HA_PRIMARY_INTERFACE="$2"
        shift 2
        ;;
      --primary-ip)
        HA_PRIMARY_LOCAL_IP="$2"
        shift 2
        ;;
      --sync-interface)
        HA_SYNC_INTERFACE="$2"
        shift 2
        ;;
      --sync-ip)
        HA_SYNC_LOCAL_IP="$2"
        shift 2
        ;;
      --core-interface)
        HA_CORE_INTERFACE="$2"
        shift 2
        ;;
      --core-ip)
        HA_CORE_LOCAL_IP="$2"
        shift 2
        ;;
      --ipsec-service)
        IPSEC_SERVICE="$2"
        shift 2
        ;;
      --ipsec-backend)
        IPSEC_BACKEND="$2"
        shift 2
        ;;
      --sa-sync-mode)
        SA_SYNC_MODE="$2"
        shift 2
        ;;
      --flow-sync-mode)
        FLOW_SYNC_MODE="$2"
        shift 2
        ;;
      --strongswan-archive-uri)
        STRONGSWAN_ARCHIVE_URI="$2"
        shift 2
        ;;
      --s3-package-uri)
        PROJECT_PACKAGE_S3_URI="$2"
        shift 2
        ;;
      --shared-efs-fs-id)
        SHARED_EFS_FS_ID="$2"
        shift 2
        ;;
      --shared-efs-ap-id)
        SHARED_EFS_AP_ID="$2"
        shift 2
        ;;
      --shared-dir)
        SHARED_DIR="$2"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
  done

  for required_var in \
    HA_CLUSTER_ID HA_NODE_ID HA_REGION HA_DDB_TABLE HA_EIP_ALLOC_ID HA_ENI_ID \
    HA_SYNC_PEER_IP HA_PRIMARY_INTERFACE HA_PRIMARY_LOCAL_IP HA_SYNC_INTERFACE \
    HA_SYNC_LOCAL_IP HA_CORE_INTERFACE HA_CORE_LOCAL_IP
  do
    if [[ -z "${!required_var}" ]]; then
      echo "Missing required argument: $required_var"
      usage
      exit 1
    fi
  done
else
  if [[ $# -lt 13 ]]; then
    usage
    exit 1
  fi

  HA_CLUSTER_ID="$1"
  HA_NODE_ID="$2"
  HA_REGION="$3"
  HA_DDB_TABLE="$4"
  HA_EIP_ALLOC_ID="$5"
  HA_ENI_ID="$6"
  HA_SYNC_PEER_IP="$7"
  HA_PRIMARY_INTERFACE="$8"
  HA_PRIMARY_LOCAL_IP="$9"
  HA_SYNC_INTERFACE="${10}"
  HA_SYNC_LOCAL_IP="${11}"
  HA_CORE_INTERFACE="${12}"
  HA_CORE_LOCAL_IP="${13}"
  PROJECT_PACKAGE_S3_URI="${14:-$PROJECT_PACKAGE_S3_URI}"
  SHARED_EFS_FS_ID="${15:-$SHARED_EFS_FS_ID}"
  SHARED_EFS_AP_ID="${16:-$SHARED_EFS_AP_ID}"
fi

LOG_DIR="/LOG"
APP_DIR="/Application"
SHARED_ROOT="$SHARED_DIR/$HA_CLUSTER_ID"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

case "$IPSEC_BACKEND" in
  libreswan|strongswan)
    ;;
  *)
    echo "Unsupported IPsec backend: $IPSEC_BACKEND"
    exit 1
    ;;
esac

dnf install -y amazon-efs-utils unzip jq awscli conntrack-tools nftables
if [[ "$IPSEC_BACKEND" == "libreswan" ]]; then
  dnf install -y libreswan
fi

if [[ -n "$SHARED_EFS_FS_ID" ]]; then
  if [[ ! "$SHARED_EFS_FS_ID" =~ ^fs-[a-z0-9]+$ ]]; then
    echo "Invalid EFS file system id: $SHARED_EFS_FS_ID"
    exit 1
  fi
  if [[ -n "$SHARED_EFS_AP_ID" && ! "$SHARED_EFS_AP_ID" =~ ^fsap-[a-z0-9]+$ ]]; then
    echo "Invalid EFS access point id: $SHARED_EFS_AP_ID"
    exit 1
  fi
  mkdir -p "$SHARED_DIR"
  if [[ -n "$SHARED_EFS_AP_ID" ]]; then
    EFS_FSTAB="$SHARED_EFS_FS_ID:/ $SHARED_DIR efs _netdev,tls,accesspoint=$SHARED_EFS_AP_ID 0 0"
  else
    EFS_FSTAB="$SHARED_EFS_FS_ID:/ $SHARED_DIR efs _netdev,tls 0 0"
  fi
  grep -qE "[[:space:]]$SHARED_DIR[[:space:]]" /etc/fstab || echo "$EFS_FSTAB" >> /etc/fstab
  mount -a
  mkdir -p "$SHARED_ROOT/customer-bundles" "$SHARED_ROOT/backups" "$SHARED_ROOT/log-archive" "$SHARED_ROOT/exports"
fi

mkdir -p "$APP_DIR/muxingplus-ha"
rm -rf /opt/muxingplus-ha
ln -sfn "$APP_DIR/muxingplus-ha" /opt/muxingplus-ha
if [[ -n "$SHARED_EFS_FS_ID" ]]; then
  ln -sfn "$SHARED_ROOT" /opt/muxingplus-ha/shared
fi

aws s3 cp "$PROJECT_PACKAGE_S3_URI" /tmp/muxingplus-ha.zip
unzip -oq /tmp/muxingplus-ha.zip -d "$APP_DIR/muxingplus-ha"
if [[ ! -f "$APP_DIR/muxingplus-ha/README.md" ]]; then
  inner_dir="$(find "$APP_DIR/muxingplus-ha" -mindepth 1 -maxdepth 1 -type d | head -n1 || true)"
  if [[ -n "$inner_dir" && -f "$inner_dir/README.md" ]]; then
    cp -a "$inner_dir"/. "$APP_DIR/muxingplus-ha/"
  fi
fi

if [[ "$IPSEC_BACKEND" == "strongswan" ]]; then
  STRONGSWAN_ARCHIVE_URI="$STRONGSWAN_ARCHIVE_URI" \
    bash "$APP_DIR/muxingplus-ha/scripts/install_strongswan_from_source.sh"
fi

bash "$APP_DIR/muxingplus-ha/ops/headend-ha-active-standby/scripts/install-local.sh" "$APP_DIR/muxingplus-ha"

cat >/etc/muxingplus-ha/ha.env <<EOF
HA_CLUSTER_ID=$HA_CLUSTER_ID
HA_NODE_ID=$HA_NODE_ID
HA_REGION=$HA_REGION
HA_DDB_TABLE=$HA_DDB_TABLE
HA_LEASE_TTL_SEC=15
HA_LOOP_INTERVAL_SEC=3
HA_EIP_ALLOC_ID=$HA_EIP_ALLOC_ID
HA_ENI_ID=$HA_ENI_ID
HA_IPSEC_SERVICE=$IPSEC_SERVICE
FLOW_SYNC_MODE=$FLOW_SYNC_MODE
SA_SYNC_MODE=$SA_SYNC_MODE
HA_CONNTRACKD_SERVICE=conntrackd
HA_CONNTRACKD_COMMIT_ON_PROMOTE=true
HA_CONNTRACKD_RESYNC_ON_DEMOTE=true
HA_DEMOTE_STOP_IPSEC=true
HA_STATE_DIR=/run/muxingplus-ha
HA_LOG_FILE=$LOG_DIR/muxingplus-ha.log
HA_PRIMARY_INTERFACE=$HA_PRIMARY_INTERFACE
HA_PRIMARY_LOCAL_IP=$HA_PRIMARY_LOCAL_IP
HA_SYNC_INTERFACE=$HA_SYNC_INTERFACE
HA_SYNC_LOCAL_IP=$HA_SYNC_LOCAL_IP
HA_SYNC_PEER_IP=$HA_SYNC_PEER_IP
HA_CORE_INTERFACE=$HA_CORE_INTERFACE
HA_CORE_LOCAL_IP=$HA_CORE_LOCAL_IP
EOF
chmod 600 /etc/muxingplus-ha/ha.env

cp /etc/muxingplus-ha/examples/conntrackd.conf.ftfw.example /etc/conntrackd/conntrackd.conf
sed -i "s#<SYNC_LOCAL_IP>#$HA_SYNC_LOCAL_IP#g" /etc/conntrackd/conntrackd.conf
sed -i "s#<SYNC_PEER_IP>#$HA_SYNC_PEER_IP#g" /etc/conntrackd/conntrackd.conf
sed -i "s#<SYNC_INTERFACE>#$HA_SYNC_INTERFACE#g" /etc/conntrackd/conntrackd.conf

systemctl enable --now conntrackd || true
systemctl enable --now muxingplus-ha.service

systemctl is-active muxingplus-ha conntrackd "$IPSEC_SERVICE" || true
