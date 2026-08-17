#!/usr/bin/env bash

set -euo pipefail

DEFAULT_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_ROOT="${DUOFORGE_HOME:-$DEFAULT_DATA_HOME/duoforge-ab}"
DRY_RUN=0
WITH_TEMPLATE_DB=0
FORCE=0
MIN_FREE_GIB="${DUOFORGE_ASSET_MIN_FREE_GIB:-20}"
SKIP_DISK_CHECK=0
PROTENIX_CHECKPOINT=""

OPENDDE_REVISION="eddd563ce96571f784012edd8f045181c8f8627d"
OPENDDE_ROOT="https://huggingface.co/aurekaresearch/OpenDDE/resolve/$OPENDDE_REVISION"
PROTENIX_ROOT="https://protenix.tos-cn-beijing.volces.com"

usage() {
    cat <<'EOF'
Usage: ./fetch_assets.sh [OPTIONS]

Download only checkpoints and common inference files required by DuoForge-Ab.
Code/environment installation remains the separate setup.sh step.

Options:
  --root DIR                    Installation root
  --protenix-checkpoint FILE    Install an already obtained official protenix-v2.pt
  --with-template-db            Also install the ~220 MB protein template search DB
  --min-free-gib N              Required free space (default: 20 GiB)
  --skip-disk-check             Do not enforce the free-space check
  --force                       Replace completed assets
  --dry-run                     Print the plan without creating or downloading anything
  -h, --help                    Show this help

The Protenix-v2 CDN may return HTTP 403 outside its supported region. In that
case obtain the official file separately and pass --protenix-checkpoint FILE.
No v1 checkpoint is ever substituted.
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
        --protenix-checkpoint)
            [[ $# -ge 2 ]] || die "--protenix-checkpoint requires a file"
            PROTENIX_CHECKPOINT="$2"
            shift 2
            ;;
        --with-template-db)
            WITH_TEMPLATE_DB=1
            shift
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
        --force)
            FORCE=1
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

[[ "$MIN_FREE_GIB" =~ ^[0-9]+$ ]] || die "--min-free-gib must be an integer"
[[ "$(uname -s)" == "Linux" ]] || die "only Linux is supported"
require_command realpath
if [[ "$DRY_RUN" != "1" ]]; then
    for command_name in curl stat sha256sum head df awk; do
        require_command "$command_name"
    done
fi
INSTALL_ROOT="$(realpath -m "$INSTALL_ROOT")"

printf 'DuoForge-Ab asset fetch\n'
printf 'root=%s\n' "$INSTALL_ROOT"
printf 'required_free_gib=%s\n' "$MIN_FREE_GIB"
printf 'known_checkpoint_bytes=15188759772\n'
printf 'protenix_checkpoint_size=unknown-until-official-access-is-restored\n'
printf 'template_database=%s\n' "$([[ "$WITH_TEMPLATE_DB" == "1" ]] && printf enabled || printf disabled)"

if [[ "$DRY_RUN" != "1" ]]; then
    existing="$INSTALL_ROOT"
    while [[ ! -e "$existing" ]]; do
        existing="$(dirname "$existing")"
    done
    available_kib="$(df -Pk "$existing" | awk 'NR==2 {print $4}')"
    required_kib=$((MIN_FREE_GIB * 1024 * 1024))
    if (( available_kib < required_kib )); then
        available_gib=$((available_kib / 1024 / 1024))
        if [[ "$SKIP_DISK_CHECK" == "1" ]]; then
            printf 'warning: only %s GiB free; assets recommend %s GiB\n' \
                "$available_gib" "$MIN_FREE_GIB" >&2
        else
            die "only ${available_gib} GiB free; assets require ${MIN_FREE_GIB} GiB (override with --min-free-gib or --skip-disk-check)"
        fi
    fi
fi

run_command mkdir -p \
    "$INSTALL_ROOT/checkpoints/rfantibody" \
    "$INSTALL_ROOT/checkpoints/igdesign" \
    "$INSTALL_ROOT/checkpoints/antifold" \
    "$INSTALL_ROOT/runtime/protenix/checkpoint" \
    "$INSTALL_ROOT/runtime/protenix/common" \
    "$INSTALL_ROOT/runtime/opendde/checkpoint" \
    "$INSTALL_ROOT/runtime/opendde/common"

verify_file() {
    local path="$1"
    local expected_size="$2"
    local expected_sha256="$3"
    [[ -f "$path" ]] || return 1
    if [[ "$expected_size" != "0" ]]; then
        [[ "$(stat -c '%s' "$path")" == "$expected_size" ]] || return 1
    else
        [[ -s "$path" ]] || return 1
    fi
    if [[ -n "$expected_sha256" ]]; then
        [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_sha256" ]] || return 1
    fi
}

fetch_file() {
    local label="$1"
    local url="$2"
    local destination="$3"
    local expected_size="$4"
    local expected_sha256="$5"
    printf 'asset=%s destination=%s' "$label" "$destination"
    if [[ "$expected_size" != "0" ]]; then
        printf ' bytes=%s' "$expected_size"
    else
        printf ' bytes=unpublished'
    fi
    printf '\n'
    if [[ "$DRY_RUN" == "1" ]]; then
        print_command curl --fail --location --retry 5 --continue-at - \
            --output "$destination.part" "$url"
        return
    fi
    if [[ "$FORCE" != "1" ]] && verify_file "$destination" "$expected_size" "$expected_sha256"; then
        printf 'reuse asset=%s\n' "$destination"
        return
    fi
    mkdir -p "$(dirname "$destination")"
    if ! curl --fail --location --retry 5 --continue-at - \
        --output "$destination.part" "$url"; then
        printf 'error: download failed for %s; partial file kept at %s\n' \
            "$label" "$destination.part" >&2
        if [[ "$label" == "protenix-v2.pt" ]]; then
            printf 'error: the official Protenix-v2 CDN currently returns 403 in some regions; rerun with --protenix-checkpoint /path/to/official/protenix-v2.pt\n' >&2
        fi
        return 2
    fi
    verify_file "$destination.part" "$expected_size" "$expected_sha256" \
        || die "downloaded file failed size/checksum validation: $destination.part"
    mv -f "$destination.part" "$destination"
}

install_local_file() {
    local source="$1"
    local destination="$2"
    [[ "$DRY_RUN" == "1" || -f "$source" ]] \
        || die "Protenix checkpoint is not a regular file: $source"
    printf 'asset=protenix-v2.pt source=%s destination=%s bytes=user-supplied\n' \
        "$source" "$destination"
    if [[ "$DRY_RUN" == "1" ]]; then
        print_command cp --reflink=auto "$source" "$destination"
    else
        if [[ "$FORCE" != "1" ]] && plausible_protenix_checkpoint "$destination"; then
            printf 'reuse asset=%s\n' "$destination"
            return
        fi
        mkdir -p "$(dirname "$destination")"
        cp --reflink=auto "$source" "$destination.part"
        verify_protenix_checkpoint "$destination.part"
        mv -f "$destination.part" "$destination"
    fi
}

plausible_protenix_checkpoint() {
    local path="$1"
    [[ -f "$path" && "$(stat -c '%s' "$path")" -ge 1000000000 ]] \
        && [[ "$(head -c 2 "$path")" == "PK" ]]
}

verify_protenix_checkpoint() {
    local path="$1"
    plausible_protenix_checkpoint "$path" \
        || die "Protenix-v2 checkpoint must be a PyTorch ZIP of at least 1,000,000,000 bytes: $path"
    printf 'warning: Protenix-v2 has no published size/SHA-256; identity cannot be fully verified yet\n' >&2
}

fetch_file RFdiffusion_Ab.pt \
    https://files.ipd.uw.edu/pub/RFantibody/RFdiffusion_Ab.pt \
    "$INSTALL_ROOT/checkpoints/rfantibody/RFdiffusion_Ab.pt" \
    483452922 ""
fetch_file igmpnn_acvr2b_holdout.ckpt \
    https://absci-prod-ai-public-data.s3.us-west-2.amazonaws.com/igmpnn_acvr2b_holdout.ckpt \
    "$INSTALL_ROOT/checkpoints/igdesign/igmpnn_acvr2b_holdout.ckpt" \
    6774680 ""
fetch_file igdesign_acvr2b_holdout.ckpt \
    https://absci-prod-ai-public-data.s3.us-west-2.amazonaws.com/igdesign_acvr2b_holdout.ckpt \
    "$INSTALL_ROOT/checkpoints/igdesign/igdesign_acvr2b_holdout.ckpt" \
    11506422598 ""
fetch_file model.pt \
    https://opig.stats.ox.ac.uk/data/downloads/AntiFold/models/model.pt \
    "$INSTALL_ROOT/checkpoints/antifold/model.pt" \
    566838063 ""

fetch_file opendde_abag.pt \
    "$OPENDDE_ROOT/opendde_abag.pt?download=true" \
    "$INSTALL_ROOT/runtime/opendde/checkpoint/opendde_abag.pt" \
    2625271509 5cf37441ddef2a2f148b81dd4a218ad274f996fecaf17dec901ab6cf1351713d

for filename in components.cif components.cif.rdkit_mol.pkl clusters-by-entity-40.txt obsolete_release_date.csv; do
    fetch_file "protenix-common/$filename" \
        "$PROTENIX_ROOT/common/$filename" \
        "$INSTALL_ROOT/runtime/protenix/common/$filename" 0 ""
done

fetch_file opendde-common/components.cif \
    "$OPENDDE_ROOT/common/components.cif?download=true" \
    "$INSTALL_ROOT/runtime/opendde/common/components.cif" \
    490777362 bb31ae5cf6c8bc669924313077cb4231ee5ffefd3a20118cd14f3ec89f8bb6a5
fetch_file opendde-common/components.cif.rdkit_mol.pkl \
    "$OPENDDE_ROOT/common/components.cif.rdkit_mol.pkl?download=true" \
    "$INSTALL_ROOT/runtime/opendde/common/components.cif.rdkit_mol.pkl" \
    142498117 d1cfb71f5993a3ebea7c47877022d7f597bbfbaf86e28a4770e957da6c50cd35
fetch_file opendde-common/obsolete_to_successor.json \
    "$OPENDDE_ROOT/common/obsolete_to_successor.json?download=true" \
    "$INSTALL_ROOT/runtime/opendde/common/obsolete_to_successor.json" \
    86882 2bc08348d0efba438c109bb27be6fa25b611d371c60b8a8da3de387a4a0698ad
fetch_file opendde-common/release_date_cache.json \
    "$OPENDDE_ROOT/common/release_date_cache.json?download=true" \
    "$INSTALL_ROOT/runtime/opendde/common/release_date_cache.json" \
    12754898 8b1ef12ddc01a0d5eb2d388c77ded91aa906eebce7440726c57b6f8d1a3ec142

if [[ "$WITH_TEMPLATE_DB" == "1" ]]; then
    TEMPLATE_DIR="$INSTALL_ROOT/runtime/shared/search_database"
    TEMPLATE_ARCHIVE="$TEMPLATE_DIR/pdb_seqres_2022_09_28.fasta.zst"
    TEMPLATE_FASTA="$TEMPLATE_DIR/pdb_seqres_2022_09_28.fasta"
    if [[ "$DRY_RUN" != "1" && "$FORCE" != "1" && -s "$TEMPLATE_FASTA" ]]; then
        printf 'reuse asset=%s\n' "$TEMPLATE_FASTA"
    else
        run_command mkdir -p "$TEMPLATE_DIR"
        fetch_file pdb_seqres_2022_09_28.fasta.zst \
            https://storage.googleapis.com/alphafold-databases/v3.0/pdb_seqres_2022_09_28.fasta.zst \
            "$TEMPLATE_ARCHIVE" 0 ""
        ZSTD_BIN="$INSTALL_ROOT/envs/installer/bin/zstd"
        if [[ "$DRY_RUN" != "1" && ! -x "$ZSTD_BIN" ]]; then
            ZSTD_BIN="$(command -v zstd || true)"
            [[ -n "$ZSTD_BIN" ]] || die "zstd is required; rerun setup.sh first"
        fi
        run_command "$ZSTD_BIN" --decompress --force --rm \
            --output "$TEMPLATE_FASTA" "$TEMPLATE_ARCHIVE"
    fi
fi

PROTENIX_DESTINATION="$INSTALL_ROOT/runtime/protenix/checkpoint/protenix-v2.pt"
if [[ -n "$PROTENIX_CHECKPOINT" ]]; then
    install_local_file "$(realpath -m "$PROTENIX_CHECKPOINT")" "$PROTENIX_DESTINATION"
else
    fetch_file protenix-v2.pt \
        "$PROTENIX_ROOT/checkpoint/protenix-v2.pt" \
        "$PROTENIX_DESTINATION" 0 ""
    if [[ "$DRY_RUN" != "1" ]]; then
        verify_protenix_checkpoint "$PROTENIX_DESTINATION"
    fi
fi

printf '\nAsset plan complete. Normal pipeline execution will not access the network.\n'
printf 'Run source %q before using my_run.yaml.\n' "$INSTALL_ROOT/env.sh"
