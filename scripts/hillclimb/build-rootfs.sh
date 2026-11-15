#!/bin/bash
# Builds the stand-in CI guest root disk: Ubuntu 24.04 + fio + PostgreSQL 16 on
# ext4 (prod CI guests boot ext4). Output: <out>/base.raw (40 GiB sparse).
set -euo pipefail
out=${1:?usage: build-rootfs.sh <out-dir>}
mkdir -p "$out"; cd "$out"
curl -fsSL -o root.tar.xz https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64-root.tar.xz
truncate -s 40G base.raw
mkfs.ext4 -F -q -L rootfs base.raw
mkdir -p r && mount -o loop base.raw r
tar -xJf root.tar.xz -C r --numeric-owner && rm root.tar.xz
rm -f r/etc/resolv.conf && cp /etc/resolv.conf r/etc/resolv.conf
printf '#!/bin/sh\nexit 101\n' > r/usr/sbin/policy-rc.d && chmod +x r/usr/sbin/policy-rc.d
mount --bind /dev r/dev; mount -t proc proc r/proc; mount -t sysfs sys r/sys
chroot r env DEBIAN_FRONTEND=noninteractive apt-get update -qq
chroot r env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  fio postgresql-16 postgresql-contrib-16 python3 jq procps >/dev/null
chroot r apt-get clean
rm -f r/usr/sbin/policy-rc.d
umount r/dev r/proc r/sys r && rmdir r
echo "rootfs ready: $(du -h --apparent-size base.raw | cut -f1) apparent, $(du -h base.raw | cut -f1) used"
