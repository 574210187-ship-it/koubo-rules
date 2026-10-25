#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ $# -lt 1 ]; then echo 'Usage: ./RUN_REFERENCE_MAC_LINUX.sh reference.mp4'; exit 2; fi
python3 -m clipflow.cli doctor
python3 -m clipflow.cli reference --input "$1" --out "./output_$(basename "$1" .mp4)"
