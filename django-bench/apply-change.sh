#!/usr/bin/env bash
# Apply the change a benchmark run tests, inside a Django checkout.
#
# Usage: apply-change.sh <django_dir> <change>
#   none    No change: the commit boxd measured ("a commit with no code
#           change"). Nothing to do.
#   deps-N  A dependency change: add one new package to the requirements
#           file. Every setup then has to install something; on GitHub-style
#           caches the cache key (the file's hash) also changes. N picks a
#           different package per repeat so no run reuses another's work.
set -euo pipefail

django_dir=$1
change=$2
source "$(dirname "$0")/bench.env"

case "$change" in
  none) ;;
  deps-*)
    # Small pure-Python packages that Django's tests do not import, so the
    # change costs an install but cannot change test results.
    packages=(humanize tabulate python-slugify text-unidecode wcwidth)
    n=${change#deps-}
    pkg=${packages[$(( (n - 1) % ${#packages[@]} ))]}
    printf '%s\n' "$pkg" >> "$django_dir/$REQUIREMENTS"
    echo "dependency change: added $pkg to $REQUIREMENTS"
    ;;
  *) echo "unknown change: $change" >&2; exit 2 ;;
esac
