#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/antifold"
SOURCE_ROOT="$DUOFORGE_SETUP_ROOT/sources/AntiFold"
if environment_is_complete "$PREFIX"; then
    printf 'reuse environment=antifold prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=antifold prefix=%s\n' "$PREFIX"
create_environment_from_file "$PREFIX" "$SCRIPT_DIR/antifold.yaml"
run_command "$PREFIX/bin/python" -m pip install --no-deps --editable "$SOURCE_ROOT"
mark_environment_complete "$PREFIX"
