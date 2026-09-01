#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."
python3 deploy/install.py "$@"
