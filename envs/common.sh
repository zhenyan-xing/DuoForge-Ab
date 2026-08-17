#!/usr/bin/env bash

set -euo pipefail

: "${DUOFORGE_SETUP_ROOT:?DUOFORGE_SETUP_ROOT is required}"
: "${DUOFORGE_MAMBA:?DUOFORGE_MAMBA is required}"
: "${DUOFORGE_UV:?DUOFORGE_UV is required}"
: "${DUOFORGE_SETUP_DRY_RUN:=0}"

print_command() {
    printf '  +'
    printf ' %q' "$@"
    printf '\n'
}

run_command() {
    if [[ "$DUOFORGE_SETUP_DRY_RUN" == "1" ]]; then
        print_command "$@"
    else
        "$@"
    fi
}

run_in_directory() {
    local directory="$1"
    shift
    if [[ "$DUOFORGE_SETUP_DRY_RUN" == "1" ]]; then
        printf '  + cd %q &&' "$directory"
        printf ' %q' "$@"
        printf '\n'
    else
        (
            cd "$directory"
            "$@"
        )
    fi
}

environment_is_complete() {
    local prefix="$1"
    [[ "$DUOFORGE_SETUP_DRY_RUN" != "1" \
        && -x "$prefix/bin/python" \
        && -f "$prefix/.duoforge-install-complete" ]]
}

mark_environment_complete() {
    run_command touch "$1/.duoforge-install-complete"
}

create_base_environment() {
    local prefix="$1"
    local python_version="$2"
    if [[ -x "$prefix/bin/python" ]]; then
        printf 'reuse environment=%s\n' "$prefix"
        return
    fi
    run_command env \
        "CONDA_PKGS_DIRS=$DUOFORGE_SETUP_ROOT/cache/conda" \
        "$DUOFORGE_MAMBA" create --yes --prefix "$prefix" \
        "python=$python_version" pip --channel conda-forge
}

create_environment_from_file() {
    local prefix="$1"
    local definition="$2"
    if [[ -x "$prefix/bin/python" ]]; then
        run_command env \
            "CONDA_PKGS_DIRS=$DUOFORGE_SETUP_ROOT/cache/conda" \
            "$DUOFORGE_MAMBA" env update --yes --prefix "$prefix" --file "$definition"
        return
    fi
    run_command env \
        "CONDA_PKGS_DIRS=$DUOFORGE_SETUP_ROOT/cache/conda" \
        "$DUOFORGE_MAMBA" env create --yes --prefix "$prefix" --file "$definition"
}

uv_command() {
    run_command env \
        "UV_CACHE_DIR=$DUOFORGE_SETUP_ROOT/cache/uv" \
        "UV_LINK_MODE=hardlink" \
        "$DUOFORGE_UV" "$@"
}
