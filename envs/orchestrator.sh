#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/orchestrator"
if environment_is_complete "$PREFIX"; then
    printf 'reuse environment=orchestrator prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=orchestrator prefix=%s\n' "$PREFIX"
create_base_environment "$PREFIX" "3.11"
uv_command pip install --python "$PREFIX/bin/python" --editable "$REPO_ROOT"
mark_environment_complete "$PREFIX"
