#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PREFIX="$DUOFORGE_SETUP_ROOT/envs/rfantibody"
SOURCE_ROOT="$DUOFORGE_SETUP_ROOT/sources/RFantibody"
if environment_is_complete "$PREFIX"; then
    printf 'reuse environment=rfantibody prefix=%s\n' "$PREFIX"
    exit 0
fi
printf 'install environment=rfantibody prefix=%s\n' "$PREFIX"
create_base_environment "$PREFIX" "3.10"
run_command env \
    "UV_CACHE_DIR=$DUOFORGE_SETUP_ROOT/cache/uv" \
    "UV_LINK_MODE=hardlink" \
    "UV_PROJECT_ENVIRONMENT=$PREFIX" \
    "$DUOFORGE_UV" sync --frozen --no-dev --project "$SOURCE_ROOT" \
    --python "$PREFIX/bin/python"
mark_environment_complete "$PREFIX"
