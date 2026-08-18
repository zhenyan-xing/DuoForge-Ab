#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="/tmp/duoforge-ab-smoke"
CONFIG="$SCRIPT_DIR/configs/smoke_8ucd_crop_8gb.yaml"
STAGE="all"
EXECUTE=0
CLEANUP_ON_SUCCESS=0

usage() {
    cat <<'EOF'
Usage: ./run_smoke.sh [OPTIONS]

Explicit, serial, low-disk real smoke workflow. The default is a read-only plan.

Options:
  --root DIR             Dedicated smoke installation root
  --config FILE          Smoke YAML (default: configs/smoke_8ucd_crop_8gb.yaml)
  --stage NAME           all, backbone, sequence-design, or fold
  --execute              Install/fetch/run instead of printing the plan
  --cleanup-on-success   Delete that stage's allowlisted assets after validation
  --dry-run              Print the plan (default)
  -h, --help             Show this help
EOF
}

die() {
    printf 'error: %s\n' "$1" >&2
    exit 2
}

print_command() {
    printf '  +'
    printf ' %q' "$@"
    printf '\n'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) [[ $# -ge 2 ]] || die "--root requires a directory"; ROOT="$2"; shift 2 ;;
        --config) [[ $# -ge 2 ]] || die "--config requires a file"; CONFIG="$2"; shift 2 ;;
        --stage) [[ $# -ge 2 ]] || die "--stage requires a name"; STAGE="$2"; shift 2 ;;
        --execute) EXECUTE=1; shift ;;
        --cleanup-on-success) CLEANUP_ON_SUCCESS=1; shift ;;
        --dry-run) EXECUTE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

command -v realpath >/dev/null 2>&1 || die "realpath is required"
ROOT="$(realpath -m "$ROOT")"
CONFIG="$(realpath -m "$CONFIG")"
[[ -f "$CONFIG" ]] || die "config does not exist: $CONFIG"
case "$STAGE" in all|backbone|sequence-design|fold) ;; *) die "unknown stage: $STAGE" ;; esac
case "$ROOT" in /|"$(realpath -m "$HOME")"|"$SCRIPT_DIR") die "refusing unsafe smoke root: $ROOT" ;; esac

printf 'DuoForge-Ab real smoke workflow\n'
printf 'root=%s\nconfig=%s\nstage=%s\nmode=%s\ncleanup_on_success=%s\n' \
    "$ROOT" "$CONFIG" "$STAGE" \
    "$([[ "$EXECUTE" == "1" ]] && printf execute || printf dry-run)" \
    "$CLEANUP_ON_SUCCESS"

if [[ "$EXECUTE" != "1" ]]; then
    print_command "$SCRIPT_DIR/setup.sh" --root "$ROOT"
    for planned_stage in backbone sequence-design fold; do
        [[ "$STAGE" == "all" || "$STAGE" == "$planned_stage" ]] || continue
        fetch=("$SCRIPT_DIR/fetch_assets.sh" --stage "$planned_stage" --root "$ROOT")
        if [[ "$planned_stage" == "fold" && -n "${PROTENIX_V2_CHECKPOINT:-}" ]]; then
            fetch+=(--protenix-checkpoint "$PROTENIX_V2_CHECKPOINT")
        fi
        print_command "${fetch[@]}"
        print_command "$ROOT/envs/orchestrator/bin/duoforge-ab" "$planned_stage" --config "$CONFIG" --execute --resume
        if [[ "$CLEANUP_ON_SUCCESS" == "1" ]]; then
            print_command "$SCRIPT_DIR/cleanup_assets.sh" --stage "$planned_stage" --root "$ROOT" --execute
        fi
    done
    exit 0
fi

mkdir -p "$ROOT/logs/smoke"
EVENTS="$ROOT/logs/smoke/events.tsv"
printf 'component\tstatus\texit_code\telapsed_seconds\tlog\n' >"$EVENTS"

run_logged() {
    local component="$1"
    shift
    local log="$ROOT/logs/smoke/${component}.log"
    local started ended rc status
    started="$(date +%s)"
    print_command "$@"
    "$@" >"$log" 2>&1
    rc=$?
    ended="$(date +%s)"
    status=complete
    [[ "$rc" == "0" ]] || status=failed
    printf '%s\t%s\t%s\t%s\t%s\n' "$component" "$status" "$rc" "$((ended - started))" "$log" >>"$EVENTS"
    return "$rc"
}

if [[ ! -f "$ROOT/env.sh" ]]; then
    run_logged setup "$SCRIPT_DIR/setup.sh" --root "$ROOT" || die "setup failed; see $ROOT/logs/smoke/setup.log"
fi
source "$ROOT/env.sh"
export DUOFORGE_GPU_TELEMETRY=1

{
    printf 'timestamp='; date --iso-8601=seconds
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader 2>&1 || true
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>&1 || true
} >"$ROOT/logs/smoke/hardware_before.log"

RUN_DIR="$("$ROOT/envs/orchestrator/bin/python" -c \
    'import sys; from antibody_design.config import load_config; print(load_config(sys.argv[1]).run.output_dir)' \
    "$CONFIG")" || die "could not resolve run.output_dir"
run_logged validate duoforge-ab validate --config "$CONFIG" || die "configuration validation failed"
run_logged dry_run duoforge-ab run --config "$CONFIG" --dry-run || die "pipeline dry-run failed"

overall=complete
for current_stage in backbone sequence-design fold; do
    [[ "$STAGE" == "all" || "$STAGE" == "$current_stage" ]] || continue
    fetch=("$SCRIPT_DIR/fetch_assets.sh" --stage "$current_stage" --root "$ROOT")
    if [[ "$current_stage" == "fold" && -n "${PROTENIX_V2_CHECKPOINT:-}" ]]; then
        fetch+=(--protenix-checkpoint "$PROTENIX_V2_CHECKPOINT")
    fi
    run_logged "fetch_${current_stage}" "${fetch[@]}"
    fetch_rc=$?
    du -sk "$ROOT/checkpoints" "$ROOT/runtime" 2>/dev/null \
        >"$ROOT/logs/smoke/${current_stage}_asset_du_kib.log" || true

    if [[ "$current_stage" == "sequence-design" && -f "$ROOT/checkpoints/igdesign/igdesign_acvr2b_holdout.ckpt" ]]; then
        run_logged igdesign_preflight \
            "$ROOT/envs/igdesign/bin/python" "$SCRIPT_DIR/scripts/check_igdesign_resource.py" \
            --checkpoint "$ROOT/checkpoints/igdesign/igdesign_acvr2b_holdout.ckpt" \
            --output "$ROOT/logs/smoke/igdesign_resource.json"
        preflight_rc=$?
        [[ "$preflight_rc" == "0" ]] || overall=partial_smoke
    fi

    if [[ "$fetch_rc" != "0" && "$current_stage" != "fold" ]]; then
        overall=partial_failure
        continue
    fi
    run_logged "execute_${current_stage}" duoforge-ab "$current_stage" --config "$CONFIG" --execute --resume
    execute_rc=$?
    run_logged "validate_${current_stage}" \
        "$ROOT/envs/orchestrator/bin/python" "$SCRIPT_DIR/scripts/validate_smoke_outputs.py" \
        --stage "$current_stage" --output-dir "$RUN_DIR" \
        --report "$ROOT/logs/smoke/${current_stage}_validation.json"
    validation_rc=$?
    if [[ "$execute_rc" != "0" || "$validation_rc" != "0" ]]; then
        [[ "$overall" == "partial_failure" ]] || overall=partial_smoke
    fi
    if [[ "$CLEANUP_ON_SUCCESS" == "1" && "$execute_rc" == "0" && "$validation_rc" == "0" ]]; then
        run_logged "cleanup_${current_stage}" \
            "$SCRIPT_DIR/cleanup_assets.sh" --stage "$current_stage" --root "$ROOT" --execute
    fi
done

du -sk "$ROOT/envs" "$ROOT/cache" "$ROOT/sources" 2>/dev/null \
    >"$ROOT/logs/smoke/install_du_kib.log" || true
printf '{"status":"%s","events":"%s","run_dir":"%s"}\n' \
    "$overall" "$EVENTS" "$RUN_DIR" >"$ROOT/logs/smoke/summary.json"
printf 'smoke_status=%s\nsummary=%s\n' "$overall" "$ROOT/logs/smoke/summary.json"
[[ "$overall" == "complete" ]] && exit 0
exit 3

