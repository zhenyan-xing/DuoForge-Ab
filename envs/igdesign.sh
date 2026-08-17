#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/igdesign"
IGDESIGN_ROOT="$DUOFORGE_SETUP_ROOT/sources/igdesign"
ANARCI_ROOT="$DUOFORGE_SETUP_ROOT/sources/ANARCI"
if environment_is_complete "$PREFIX"; then
    printf 'reuse environment=igdesign+anarci prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=igdesign+anarci prefix=%s\n' "$PREFIX"
create_environment_from_file "$PREFIX" "$SCRIPT_DIR/igdesign.yaml"
run_command "$PREFIX/bin/python" -m pip install --no-deps --editable "$IGDESIGN_ROOT"
if [[ "$DUOFORGE_SETUP_DRY_RUN" == "1" || ! -x "$PREFIX/bin/ANARCI" ]]; then
    run_in_directory "$ANARCI_ROOT" "$PREFIX/bin/python" setup.py install
else
    printf 'reuse executable=%s\n' "$PREFIX/bin/ANARCI"
fi
mark_environment_complete "$PREFIX"
