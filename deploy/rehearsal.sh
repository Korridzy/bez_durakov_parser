#!/usr/bin/env bash
# Agent/developer rehearsal only. Never run this on a server.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -n ${BD_REHEARSAL_LOG:-} ]]; then
    exec > >(tee --ignore-interrupts -a "$BD_REHEARSAL_LOG") 2>&1
fi
exec poetry run python deploy/rehearsal/run.py "$@"
