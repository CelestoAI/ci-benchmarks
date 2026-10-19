#!/usr/bin/env bash
# One-time setup of a warm Celesto computer for setup C: the equivalent of
# boxd's "set up a machine the way a job should find it, then save it".
#
# Run as root (it switches to a non-root user) on a coding-agent computer, from a checkout of ci-benchmarks:
#   bash django-bench/warm-setup.sh <role> <shard or ->
# It installs Python, checks out Django, installs the dependencies, and does
# one warm-up run of the computer's own job so caches (__pycache__, black's
# cache) exist, as after a green run on main.
set -euo pipefail

role=$1
shard=$2
here=$(cd "$(dirname "$0")" && pwd)
source "$here/bench.env"

# Match a GitHub runner's environment: system time-zone data (Django's
# timezone tests need it) and a non-root user (as root, Django's "file is
# not writable" tests cannot fail the way they expect). The root part runs
# once, then the script re-runs itself as that user.
if [ "$(id -u)" = 0 ]; then
  # The image ships without an apt package index.
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tzdata >/dev/null
  # The coding-agent template's own non-root user, which already owns its
  # uv Python directory; create one only on images without it.
  user=ohm
  id "$user" >/dev/null 2>&1 || { user=bench; useradd -m -s /bin/bash "$user"; }
  echo "$user" > /opt/bench-user
  rm -rf /opt/venv /opt/django
  mkdir -p /opt/venv /opt/django
  chown -R "$user": /opt/venv /opt/django "$(dirname "$here")"
  # The image's shared uv Python directory belongs to that user; give back
  # anything a root run put there.
  if [ -n "${UV_PYTHON_INSTALL_DIR:-}" ] && [ -d "$UV_PYTHON_INSTALL_DIR" ]; then
    chown -R "$user": "$UV_PYTHON_INSTALL_DIR"
  fi
  # A login shell, so the user gets a clean HOME and the image's profile.
  exec runuser -l "$user" -c "bash '$here/warm-setup.sh' '$role' '$shard'"
fi

# Python and a virtualenv with pip, so installs use pip as on the runners.
uv python install -q "$PYTHON_VERSION"
uv venv -q --allow-existing --seed --python "$PYTHON_VERSION" /opt/venv
source /opt/venv/bin/activate

# Django at the pinned commit.
if [ ! -d /opt/django/.git ]; then
  git clone -q --filter=blob:none https://github.com/django/django.git /opt/django
fi
git -C /opt/django checkout -q -f "$DJANGO_SHA"

python -m pip install -q --upgrade pip wheel
python -m pip install -q -r "/opt/django/$REQUIREMENTS" -e /opt/django flake8 isort

# Warm-up run; its result is not recorded.
bash "$here/warm-run.sh" "$role" "$shard" none warmup
