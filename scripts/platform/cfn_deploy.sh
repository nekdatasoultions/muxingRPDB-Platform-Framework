#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <stack-name> <parameters-json> [region] [template]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_NAME="$1"
PARAM_FILE="$2"
REGION="${3:-us-east-1}"
TEMPLATE_FILE="${4:-$REPO_ROOT/infra/cfn/vpn-headend-unit.yaml}"

host_path() {
  local path="$1"
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$path"
    return
  fi
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path"
    return
  fi
  printf '%s\n' "$path"
}

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

mapfile -t PARAM_OVERRIDES < <(python3 - "$PARAM_FILE" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
for item in data:
    k = item["ParameterKey"]
    v = item["ParameterValue"]
    print(f"{k}={v}")
PY
)

declare -A PARAM_MAP=()
for kv in "${PARAM_OVERRIDES[@]}"; do
  key="${kv%%=*}"
  value="${kv#*=}"
  PARAM_MAP["$key"]="$value"
done

validate_ip_in_subnet() {
  local ip_addr="$1"
  local cidr_block="$2"
  local label="$3"
  [[ -z "$ip_addr" ]] && return 0
  python3 - "$ip_addr" "$cidr_block" "$label" <<'PY'
import ipaddress
import sys

ip_addr = ipaddress.ip_address(sys.argv[1])
cidr = ipaddress.ip_network(sys.argv[2], strict=False)
label = sys.argv[3]

if ip_addr not in cidr:
    print(f"[AZ-GUARD] ERROR: {label}={ip_addr} is outside subnet CIDR {cidr}", file=sys.stderr)
    sys.exit(1)
PY
}

validate_subnet_pair() {
  local subnet_a_id="$1"
  local subnet_b_id="$2"
  local node_a_ip="$3"
  local node_b_ip="$4"
  local label="$5"

  [[ -z "$subnet_a_id" || -z "$subnet_b_id" ]] && return 0

  if [[ "$subnet_a_id" == "$subnet_b_id" ]]; then
    echo "[AZ-GUARD] ERROR: ${label} subnets must be different for HA."
    exit 1
  fi

  read -r AZ_A CIDR_A AZ_B CIDR_B < <(aws ec2 describe-subnets \
    --region "$REGION" \
    --subnet-ids "$subnet_a_id" "$subnet_b_id" \
    --query "join(' ', [Subnets[?SubnetId=='$subnet_a_id']|[0].AvailabilityZone, Subnets[?SubnetId=='$subnet_a_id']|[0].CidrBlock, Subnets[?SubnetId=='$subnet_b_id']|[0].AvailabilityZone, Subnets[?SubnetId=='$subnet_b_id']|[0].CidrBlock])" \
    --output text)

  if [[ -z "${AZ_A:-}" || -z "${AZ_B:-}" ]]; then
    echo "[AZ-GUARD] ERROR: Unable to resolve AZs for ${label} subnets $subnet_a_id and $subnet_b_id"
    exit 1
  fi

  if [[ "$AZ_A" == "$AZ_B" ]]; then
    echo "[AZ-GUARD] ERROR: ${label} subnets $subnet_a_id and $subnet_b_id are both in $AZ_A."
    exit 1
  fi

  validate_ip_in_subnet "$node_a_ip" "$CIDR_A" "${label} node A IP"
  validate_ip_in_subnet "$node_b_ip" "$CIDR_B" "${label} node B IP"

  echo "[AZ-GUARD] OK: ${label} => $subnet_a_id ($AZ_A) / $subnet_b_id ($AZ_B)"
}

validate_subnet_pair \
  "${PARAM_MAP[SubnetAId]:-}" \
  "${PARAM_MAP[SubnetBId]:-}" \
  "${PARAM_MAP[NodeAPrivateIp]:-}" \
  "${PARAM_MAP[NodeBPrivateIp]:-}" \
  "primary"

validate_subnet_pair \
  "${PARAM_MAP[HaSyncSubnetAId]:-}" \
  "${PARAM_MAP[HaSyncSubnetBId]:-}" \
  "${PARAM_MAP[NodeAHaSyncIp]:-}" \
  "${PARAM_MAP[NodeBHaSyncIp]:-}" \
  "ha-sync"

validate_subnet_pair \
  "${PARAM_MAP[CoreSubnetAId]:-}" \
  "${PARAM_MAP[CoreSubnetBId]:-}" \
  "${PARAM_MAP[NodeACoreIp]:-}" \
  "${PARAM_MAP[NodeBCoreIp]:-}" \
  "core"

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$(host_path "$TEMPLATE_FILE")" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${PARAM_OVERRIDES[@]}"

echo "CloudFormation deploy complete: $STACK_NAME ($REGION)"
