#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/igdesign"
IGDESIGN_ROOT="$DUOFORGE_SETUP_ROOT/sources/igdesign"
ANARCI_ROOT="$DUOFORGE_SETUP_ROOT/sources/ANARCI"
ANARCI_BUILD_BIN="$PREFIX/libexec/duoforge-anarci"

anarci_is_complete() {
    [[ -x "$PREFIX/bin/ANARCI" ]] || return 1
    compgen -G "$PREFIX/lib/python*/site-packages/anarci/dat/HMMs/ALL.hmm" >/dev/null \
        || return 1
    compgen -G "$PREFIX/lib/python*/site-packages/anarci/germlines.py" >/dev/null
}

if environment_is_complete "$PREFIX" && anarci_is_complete; then
    printf 'reuse environment=igdesign+anarci prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=igdesign+anarci prefix=%s\n' "$PREFIX"
create_environment_from_file "$PREFIX" "$SCRIPT_DIR/igdesign.yaml"
run_command "$PREFIX/bin/python" -m pip install --no-deps --editable "$IGDESIGN_ROOT"
if [[ "$DUOFORGE_SETUP_DRY_RUN" == "1" ]] || ! anarci_is_complete; then
    run_command mkdir -p "$ANARCI_BUILD_BIN"
    run_command cp "$PREFIX/bin/muscle" "$ANARCI_BUILD_BIN/muscle"
    if [[ "$DUOFORGE_SETUP_DRY_RUN" == "1" ]]; then
        run_in_directory "$ANARCI_ROOT" env \
            "PATH=$ANARCI_BUILD_BIN:$PREFIX/bin:$PATH" \
            "$PREFIX/bin/python" setup.py install
        run_command cp "$ANARCI_BUILD_BIN/muscle" "$PREFIX/bin/muscle"
    else
        set +e
        run_in_directory "$ANARCI_ROOT" env \
            "PATH=$ANARCI_BUILD_BIN:$PREFIX/bin:$PATH" \
            "$PREFIX/bin/python" setup.py install
        anarci_status=$?
        set -e
        run_command cp "$ANARCI_BUILD_BIN/muscle" "$PREFIX/bin/muscle"
        [[ "$anarci_status" == "0" ]] || exit "$anarci_status"
    fi
else
    printf 'reuse executable=%s\n' "$PREFIX/bin/ANARCI"
fi
if [[ "$DUOFORGE_SETUP_DRY_RUN" != "1" ]] && ! anarci_is_complete; then
    printf 'error: ANARCI executable/HMM/germline installation is incomplete\n' >&2
    exit 2
fi
mark_environment_complete "$PREFIX"
