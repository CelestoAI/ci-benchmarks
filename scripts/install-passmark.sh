#!/usr/bin/env bash
# Installs PassMark PerformanceTest for Linux (x86-64) to /tmp/PerformanceTest.
# The binary needs libncurses.so.5, which Ubuntu 24.04 does not ship.
set -euo pipefail

if ! ldconfig -p | grep -q 'libncurses.so.5'; then
  echo "deb http://security.ubuntu.com/ubuntu focal-security main universe" | sudo tee /etc/apt/sources.list.d/focal-security.list >/dev/null
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libncurses5 libtinfo5
fi

tmp=$(mktemp -d)
# passmark.com rejects curl's default user agent.
curl -fsSL -A "Mozilla/5.0 (X11; Linux x86_64)" -o "$tmp/pt.zip" https://www.passmark.com/downloads/PerformanceTest_Linux_x86-64.zip
unzip -q -o "$tmp/pt.zip" -d "$tmp"
mkdir -p /tmp/PerformanceTest
install -m 0755 "$tmp/PerformanceTest/PerformanceTest_Linux_x86-64" /tmp/PerformanceTest/pt_linux
rm -rf "$tmp"
