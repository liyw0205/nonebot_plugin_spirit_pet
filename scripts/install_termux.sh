#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export SPIRIT_PET_PLATFORM=termux
if [[ ! -f "$SCRIPT_DIR/install.sh" ]]; then
    printf 'This entry is for a complete checkout. Download scripts/install.sh for standalone Termux installation.\n' >&2
    exit 1
fi
exec bash "$SCRIPT_DIR/install.sh" "$@"
