#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_ROOT="${DUOFORGE_HOME:-$DEFAULT_DATA_HOME/duoforge-ab}"
PROFILE="standard"
MIN_FREE_GIB="${DUOFORGE_MIN_FREE_GIB:-70}"
DRY_RUN=0
SKIP_DISK_CHECK=0

usage() {
    cat <<'EOF'
Usage: ./setup.sh [OPTIONS]

Install pinned source code and isolated environments. This script never
downloads model checkpoints.

Options:
  --root DIR             Installation root (default: $DUOFORGE_HOME or XDG data dir)
  --profile NAME         standard (all environments) or bootstrap (orchestrator only)
  --min-free-gib N       Required free space for standard (default: 70 GiB)
  --skip-disk-check      Print a warning instead of enforcing the free-space check
  --dry-run              Print the exact plan without creating or downloading anything
  -h, --help             Show this help
EOF
}

die() {
    printf 'error: %s\n' "$1" >&2
    exit 2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

print_command() {
    printf '  +'
    printf ' %q' "$@"
    printf '\n'
}

run_command() {
    if [[ "$DRY_RUN" == "1" ]]; then
        print_command "$@"
    else
        "$@"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            [[ $# -ge 2 ]] || die "--root requires a directory"
            INSTALL_ROOT="$2"
            shift 2
            ;;
        --profile)
            [[ $# -ge 2 ]] || die "--profile requires a name"
            PROFILE="$2"
            shift 2
            ;;
        --min-free-gib)
            [[ $# -ge 2 ]] || die "--min-free-gib requires an integer"
            MIN_FREE_GIB="$2"
            shift 2
            ;;
        --skip-disk-check)
            SKIP_DISK_CHECK=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

[[ "$PROFILE" == "standard" || "$PROFILE" == "bootstrap" ]] \
    || die "--profile must be standard or bootstrap"
[[ "$MIN_FREE_GIB" =~ ^[0-9]+$ ]] || die "--min-free-gib must be an integer"
[[ "$(uname -s)" == "Linux" ]] || die "only Linux is supported"
[[ "$(uname -m)" == "x86_64" ]] || die "only Linux x86-64 is supported"
require_command realpath
require_command git
require_command df
require_command awk
INSTALL_ROOT="$(realpath -m "$INSTALL_ROOT")"

if command -v mamba >/dev/null 2>&1; then
    MAMBA_BIN="$(command -v mamba)"
elif command -v micromamba >/dev/null 2>&1; then
    MAMBA_BIN="$(command -v micromamba)"
elif command -v conda >/dev/null 2>&1; then
    MAMBA_BIN="$(command -v conda)"
elif [[ "$DRY_RUN" == "1" ]]; then
    MAMBA_BIN="mamba"
else
    die "mamba, micromamba, or conda is required"
fi

printf 'DuoForge-Ab setup\n'
printf 'root=%s\n' "$INSTALL_ROOT"
printf 'profile=%s\n' "$PROFILE"
if [[ "$PROFILE" == "standard" ]]; then
    printf 'required_free_gib=%s\n' "$MIN_FREE_GIB"
else
    printf 'required_free_gib=0\n'
fi
printf 'package_manager=%s\n' "$MAMBA_BIN"

if [[ "$PROFILE" == "standard" && "$DRY_RUN" != "1" ]]; then
    existing="$INSTALL_ROOT"
    while [[ ! -e "$existing" ]]; do
        existing="$(dirname "$existing")"
    done
    available_kib="$(df -Pk "$existing" | awk 'NR==2 {print $4}')"
    required_kib=$((MIN_FREE_GIB * 1024 * 1024))
    if (( available_kib < required_kib )); then
        available_gib=$((available_kib / 1024 / 1024))
        if [[ "$SKIP_DISK_CHECK" == "1" ]]; then
            printf 'warning: only %s GiB free; standard recommends %s GiB\n' \
                "$available_gib" "$MIN_FREE_GIB" >&2
        else
            die "only ${available_gib} GiB free; standard requires ${MIN_FREE_GIB} GiB (override with --min-free-gib or --skip-disk-check)"
        fi
    fi
fi

run_command mkdir -p \
    "$INSTALL_ROOT/cache/conda" \
    "$INSTALL_ROOT/cache/uv" \
    "$INSTALL_ROOT/envs" \
    "$INSTALL_ROOT/sources"

INSTALLER_PREFIX="$INSTALL_ROOT/envs/installer"
UV_BIN="$INSTALLER_PREFIX/bin/uv"
ZSTD_BIN="$INSTALLER_PREFIX/bin/zstd"
if [[ "$DRY_RUN" == "1" || ! -x "$UV_BIN" || ! -x "$ZSTD_BIN" ]]; then
    if [[ "$DRY_RUN" != "1" && -x "$INSTALLER_PREFIX/bin/python" ]]; then
        run_command env "CONDA_PKGS_DIRS=$INSTALL_ROOT/cache/conda" \
            "$MAMBA_BIN" install --yes --prefix "$INSTALLER_PREFIX" \
            python=3.11 pip zstd --channel conda-forge
    else
        run_command env "CONDA_PKGS_DIRS=$INSTALL_ROOT/cache/conda" \
            "$MAMBA_BIN" create --yes --prefix "$INSTALLER_PREFIX" \
            python=3.11 pip zstd --channel conda-forge
    fi
    run_command "$INSTALLER_PREFIX/bin/python" -m pip install "uv>=0.8,<1"
else
    printf 'reuse installer=%s\n' "$UV_BIN"
fi

install_environment() {
    local name="$1"
    env \
        "DUOFORGE_SETUP_ROOT=$INSTALL_ROOT" \
        "DUOFORGE_MAMBA=$MAMBA_BIN" \
        "DUOFORGE_UV=$UV_BIN" \
        "DUOFORGE_SETUP_DRY_RUN=$DRY_RUN" \
        bash "$SCRIPT_DIR/envs/$name.sh"
}

install_environment orchestrator

clone_pinned() {
    local name="$1"
    local repository="$2"
    local revision="$3"
    local destination="$INSTALL_ROOT/sources/$name"
    printf 'source=%s repository=%s revision=%s\n' "$name" "$repository" "$revision"
    if [[ "$DRY_RUN" != "1" && -d "$destination/.git" ]]; then
        current="$(git -C "$destination" rev-parse HEAD)"
        [[ "$current" == "$revision" ]] \
            || die "$destination is at $current, expected $revision; move it aside or choose another --root"
        printf 'reuse source=%s\n' "$destination"
        return
    fi
    run_command git clone --filter=blob:none --no-checkout --depth 1 \
        "$repository" "$destination"
    run_command git -C "$destination" fetch --depth 1 origin "$revision"
    run_command git -C "$destination" checkout --detach "$revision"
}

if [[ "$PROFILE" == "standard" ]]; then
    clone_pinned RFantibody https://github.com/RosettaCommons/RFantibody \
        8fe311415754e0276d1a39c87c57e69c88927a2d
    clone_pinned igdesign https://github.com/AbSciBio/igdesign \
        70431eef0afaf0496d7d84e22dfdc1980ec9e70e
    clone_pinned AntiFold https://github.com/oxpig/AntiFold \
        789d46786624c01eb44f177ef4c0deeeb6e77469
    clone_pinned Protenix https://github.com/bytedance/Protenix \
        2475421477ab414b571149ad4a875c390ff8a35d
    clone_pinned OpenDDE https://github.com/aurekaresearch/OpenDDE \
        5028caae7f4a3c36b7eee848cab84c4c05492204
    clone_pinned ANARCI https://github.com/oxpig/ANARCI \
        79f6c575056dedef86cb8f405ebb039197923eec

    for environment in rfantibody igdesign antifold protenix opendde; do
        install_environment "$environment"
    done
fi

if [[ "$DRY_RUN" == "1" ]]; then
    printf '  + write %q\n' "$INSTALL_ROOT/env.sh"
else
    {
        printf '# Generated by DuoForge-Ab setup.sh\n'
        printf 'export DUOFORGE_HOME=%q\n' "$INSTALL_ROOT"
        printf 'export PATH=%q:$PATH\n' "$INSTALL_ROOT/envs/orchestrator/bin"
    } >"$INSTALL_ROOT/env.sh"
    "$INSTALL_ROOT/envs/orchestrator/bin/duoforge-ab" --help >/dev/null
fi

printf '\nCode/environment installation plan complete.\n'
if [[ "$PROFILE" == "standard" ]]; then
    printf 'No model checkpoint was downloaded. Next: ./fetch_assets.sh --root %q\n' "$INSTALL_ROOT"
    printf 'After assets are ready: source %q\n' "$INSTALL_ROOT/env.sh"
else
    printf 'Activate the orchestrator with: source %q\n' "$INSTALL_ROOT/env.sh"
    printf 'Bootstrap is orchestrator-only. Rerun with --profile standard before fetching model assets.\n'
fi
