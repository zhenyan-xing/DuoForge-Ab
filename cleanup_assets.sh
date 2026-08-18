#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_ROOT="${DUOFORGE_HOME:-$DEFAULT_DATA_HOME/duoforge-ab}"
STAGE=""
EXECUTE=0

usage() {
    cat <<'EOF'
Usage: ./cleanup_assets.sh --stage NAME [OPTIONS]

Delete only checkpoint/common files in the fixed allowlist for one smoke stage.
The default is a dry-run; pass --execute to perform the listed deletions.

Options:
  --root DIR       Installation/smoke root
  --stage NAME     backbone, sequence-design, or fold (required)
  --dry-run        Print the deletion plan (default)
  --execute        Delete the exact listed files and their .part/.partial files
  -h, --help       Show this help
EOF
}

die() {
    printf 'error: %s\n' "$1" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            [[ $# -ge 2 ]] || die "--root requires a directory"
            INSTALL_ROOT="$2"
            shift 2
            ;;
        --stage)
            [[ $# -ge 2 ]] || die "--stage requires a name"
            STAGE="$2"
            shift 2
            ;;
        --dry-run)
            EXECUTE=0
            shift
            ;;
        --execute)
            EXECUTE=1
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

[[ -n "$INSTALL_ROOT" ]] || die "root must not be empty"
command -v realpath >/dev/null 2>&1 || die "required command is missing: realpath"
INSTALL_ROOT="$(realpath -m "$INSTALL_ROOT")"
HOME_ROOT="$(realpath -m "$HOME")"
case "$STAGE" in
    backbone|sequence-design|fold) ;;
    "") die "--stage is required" ;;
    *) die "unknown stage: $STAGE" ;;
esac
case "$INSTALL_ROOT" in
    /|"$HOME_ROOT"|"$SCRIPT_DIR") die "refusing unsafe root: $INSTALL_ROOT" ;;
esac

case "$STAGE" in
    backbone)
        ASSETS=(checkpoints/rfantibody/RFdiffusion_Ab.pt)
        ;;
    sequence-design)
        ASSETS=(
            checkpoints/igdesign/igmpnn_acvr2b_holdout.ckpt
            checkpoints/igdesign/igdesign_acvr2b_holdout.ckpt
            checkpoints/antifold/model.pt
        )
        ;;
    fold)
        ASSETS=(
            runtime/protenix/checkpoint/protenix-v2.pt
            runtime/protenix/common/components.cif
            runtime/protenix/common/components.cif.rdkit_mol.pkl
            runtime/protenix/common/clusters-by-entity-40.txt
            runtime/protenix/common/obsolete_release_date.csv
            runtime/opendde/checkpoint/opendde_abag.pt
            runtime/opendde/common/components.cif
            runtime/opendde/common/components.cif.rdkit_mol.pkl
            runtime/opendde/common/obsolete_to_successor.json
            runtime/opendde/common/release_date_cache.json
        )
        ;;
esac

FILES=()
for relative_path in "${ASSETS[@]}"; do
    case "$relative_path" in
        checkpoints/*|runtime/*/checkpoint/*|runtime/*/common/*) ;;
        *) die "internal allowlist path is not a checkpoint/common file: $relative_path" ;;
    esac
    path="$(realpath -m "$INSTALL_ROOT/$relative_path")"
    [[ "$path" == "$INSTALL_ROOT/"* ]] \
        || die "allowlist path escapes root: $relative_path"
    FILES+=("$path" "$path.part" "$path.partial")
done

asset_bytes() {
    local total=0
    local path
    for path in "${FILES[@]}"; do
        if [[ -f "$path" ]]; then
            total=$((total + $(stat -c '%s' "$path")))
        fi
    done
    printf '%s\n' "$total"
}

printf 'DuoForge-Ab stage asset cleanup\n'
printf 'root=%s\n' "$INSTALL_ROOT"
printf 'stage=%s\n' "$STAGE"
printf 'mode=%s\n' "$([[ "$EXECUTE" == "1" ]] && printf execute || printf dry-run)"
printf 'asset_bytes_before=%s\n' "$(asset_bytes)"
for path in "${FILES[@]}"; do
    [[ -f "$path" ]] || continue
    printf 'delete=%s\n' "$path"
    if [[ "$EXECUTE" == "1" ]]; then
        rm -f -- "$path"
    fi
done
printf 'asset_bytes_after=%s\n' "$(asset_bytes)"

