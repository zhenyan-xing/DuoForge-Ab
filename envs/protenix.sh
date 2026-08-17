#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/protenix"
SOURCE_ROOT="$DUOFORGE_SETUP_ROOT/sources/Protenix"
if environment_is_complete "$PREFIX"; then
    printf 'reuse environment=protenix prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=protenix prefix=%s\n' "$PREFIX"
create_base_environment "$PREFIX" "3.11"
uv_command pip install --python "$PREFIX/bin/python" --editable "$SOURCE_ROOT"
mark_environment_complete "$PREFIX"
