#!/usr/bin/env bash
# One-time setup of a warm Celesto computer for setup C: the equivalent of
# boxd's "set up a machine the way a job should find it, then save it".
#
# Run as root on a coding-agent computer, from a checkout of ci-benchmarks:
#   bash django-bench/warm-setup.sh <role> <shard or ->
# It installs Python, checks out Django, installs the dependencies, and does
# one warm-up run of the computer's own job so caches (__pycache__, black's
# cache) exist, as after a green run on main.
set -euo pipefail

role=$1
shard=$2
here=$(cd "$(dirname "$0")" && pwd)
source "$here/bench.env"

# Python and a virtualenv with pip, so installs use pip as on the runners.
uv python install -q "$PYTHON_VERSION"
uv venv -q --seed --python "$PYTHON_VERSION" /opt/venv
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
