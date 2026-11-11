#!/bin/bash
# Healthcheck script for systemd or container monitoring
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

python3 -m pickle_tg.cli supervisor-check
