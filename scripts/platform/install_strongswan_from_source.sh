#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-${STRONGSWAN_VERSION:-6.0.4}}"
PREFIX="${STRONGSWAN_PREFIX:-/opt/strongswan}"
BUILD_ROOT="${STRONGSWAN_BUILD_ROOT:-/usr/local/src}"
ARCHIVE_URI="${STRONGSWAN_ARCHIVE_URI:-}"

if command -v swanctl >/dev/null 2>&1; then
  exit 0
fi

dnf install -y \
  gcc \
  make \
  autoconf \
  automake \
  libtool \
  pkgconf-pkg-config \
  bison \
  flex \
  gmp-devel \
  iptables-devel \
  openssl-devel \
  systemd-devel \
  tar \
  gzip \
  bzip2

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download strongSwan sources" >&2
  exit 1
fi

mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"

archive_path=""
if [[ -n "$ARCHIVE_URI" ]]; then
  archive_name="$(basename "$ARCHIVE_URI")"
  archive_path="$BUILD_ROOT/$archive_name"
  case "$ARCHIVE_URI" in
    s3://*)
      if ! command -v aws >/dev/null 2>&1; then
        echo "aws CLI is required to fetch strongSwan archive from S3" >&2
        exit 1
      fi
      aws s3 cp "$ARCHIVE_URI" "$archive_path"
      ;;
    http://*|https://*)
      curl -fsSL "$ARCHIVE_URI" -o "$archive_path"
      ;;
    *)
      if [[ ! -f "$ARCHIVE_URI" ]]; then
        echo "Specified strongSwan archive does not exist: $ARCHIVE_URI" >&2
        exit 1
      fi
      cp "$ARCHIVE_URI" "$archive_path"
      ;;
  esac
else
  for ext in tar.bz2 tar.gz; do
    archive="strongswan-${VERSION}.${ext}"
    url="https://download.strongswan.org/${archive}"
    if curl -fsI "$url" >/dev/null 2>&1; then
      curl -fsSL "$url" -o "$archive"
      archive_path="$BUILD_ROOT/$archive"
      break
    fi
  done
fi

if [[ -z "$archive_path" ]]; then
  echo "Unable to download strongSwan ${VERSION} from official source" >&2
  exit 1
fi

rm -rf "$BUILD_ROOT/strongswan-${VERSION}"
tar -xf "$archive_path"
cd "$BUILD_ROOT/strongswan-${VERSION}"

./configure \
  --prefix="$PREFIX" \
  --sysconfdir=/etc \
  --with-swanctldir=/etc/swanctl \
  --with-systemdsystemunitdir=/etc/systemd/system \
  --disable-stroke \
  --enable-systemd \
  --enable-swanctl \
  --enable-vici \
  --enable-connmark

make -j"$(nproc)"
make install

install -d /etc/ld.so.conf.d /usr/local/sbin
{
  echo "${PREFIX}/lib"
  echo "${PREFIX}/lib64"
} >/etc/ld.so.conf.d/strongswan.conf
ldconfig

if [[ -x "${PREFIX}/sbin/swanctl" ]]; then
  ln -sfn "${PREFIX}/sbin/swanctl" /usr/local/sbin/swanctl
elif [[ -x "${PREFIX}/bin/swanctl" ]]; then
  ln -sfn "${PREFIX}/bin/swanctl" /usr/local/sbin/swanctl
fi

cat >/etc/systemd/system/strongswan.service <<EOF
[Unit]
Description=strongSwan IPsec IKEv1/IKEv2 daemon using swanctl
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=${PREFIX}/sbin/charon-systemd
ExecReload=${PREFIX}/sbin/swanctl --reload
Restart=on-abnormal

[Install]
WantedBy=multi-user.target
Alias=strongswan-swanctl.service
EOF

systemctl daemon-reload
