#!/usr/bin/env bash
set -euo pipefail

readonly SEMVER_RE='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
readonly DATASET_MESSAGE="DATASET deployments are not supported by the executor; DATASET remains a \`make start\` development mode"

fail() {
    local exit_code="$1"
    local error="$2"
    local message="$3"
    printf '{"exit_code":%s,"error":"%s","message":"%s"}\n' \
        "$exit_code" "$error" "$message" >&2
    exit "$exit_code"
}

usage_error() {
    printf 'Usage: deploy.sh <subcommand> [args]\n' >&2
    fail 2 E_USAGE 'invalid command or arguments; use --help'
}

invalid_tag() {
    fail 2 E_USAGE 'tag must be vMAJOR.MINOR.PATCH'
}

valid_tag() {
    local tag="${1-}"
    [[ ${#tag} -le 128 && "$tag" != *$'\n'* && "$tag" =~ $SEMVER_RE ]]
}

require_tag() {
    valid_tag "${1-}" || invalid_tag
}

refuse_dataset() {
    if [[ -n "${DATASET:-}" ]]; then
        printf '%s\n' "$DATASET_MESSAGE" >&2
        fail 2 E_USAGE "$DATASET_MESSAGE"
    fi
}

acquire_lock() {
    mkdir -p -- "$STATE_DIR"
    if ! chmod 700 -- "$STATE_DIR"; then
        fail 4 E_PREFLIGHT 'could not secure deployment state directory'
    fi
    umask 077
    exec 9>"$STATE_DIR/lock"
    if ! chmod 600 -- "$STATE_DIR/lock"; then
        fail 4 E_PREFLIGHT 'could not secure deployment lock'
    fi
    if ! flock -n 9; then
        fail 3 E_LOCKED 'deployment lock is held'
    fi
    export BD_DEPLOY_LOCK_FD=9
}

fetch_tags() {
    if ! git -C "$ROOT" fetch --tags --quiet origin; then
        fail 4 E_PREFLIGHT 'could not fetch release tags from origin'
    fi
}

require_clean_checkout() {
    local changes
    changes="$(git -C "$ROOT" status --porcelain --untracked-files=no --)"
    if [[ -n "$changes" ]]; then
        fail 4 E_PREFLIGHT 'server checkout must be clean'
    fi
}

checkout_tag() {
    local tag="$1"
    if ! git -C "$ROOT" rev-parse --verify --quiet --end-of-options "refs/tags/${tag}^{commit}" >/dev/null; then
        fail 4 E_PREFLIGHT 'release tag does not exist'
    fi
    if ! git -C "$ROOT" checkout --detach --quiet "refs/tags/$tag"; then
        fail 4 E_PREFLIGHT 'could not check out release tag'
    fi
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$ROOT"

VM_DIR="${BD_VM_DIR:-$ROOT/vm}"
STATE_DIR="${BD_DEPLOY_STATE_DIR:-$VM_DIR/deploy}"
SUBCOMMAND="${1-}"
if (($# > 0)); then
    shift
fi

case "$SUBCOMMAND" in
    deploy)
        (($# > 0)) || usage_error
        tag="$1"
        shift
        require_tag "$tag"
        refuse_dataset
        acquire_lock
        fetch_tags
        require_clean_checkout
        checkout_tag "$tag"
        exec poetry run python deploy/deploy.py deploy "$tag" "$@"
        ;;
    rollback)
        refuse_dataset
        requested_tag=''
        if (($# > 0)); then
            case "$1" in
                --yes|--llm-smoke|--restore-backup|--restore-backup=*)
                    ;;
                --*)
                    usage_error
                    ;;
                *)
                    requested_tag="$1"
                    shift
                    require_tag "$requested_tag"
                    ;;
            esac
        fi

        # The target is resolved under the same lock as checkout and execution, so a deployment
        # cannot finish in between and make the default target stale. The resolver inherits
        # BD_DEPLOY_LOCK_FD and does not lock again.
        acquire_lock
        if [[ -n "$requested_tag" ]]; then
            if target="$(poetry run python deploy/deploy.py resolve-rollback-target "$requested_tag")"; then
                :
            else
                exit "$?"
            fi
        else
            if target="$(poetry run python deploy/deploy.py resolve-rollback-target)"; then
                :
            else
                exit "$?"
            fi
        fi
        require_tag "$target"
        fetch_tags
        require_clean_checkout
        checkout_tag "$target"
        exec poetry run python deploy/deploy.py rollback "$target" "$@"
        ;;
    status|smoke|verify-db-isolation)
        exec poetry run python deploy/deploy.py "$SUBCOMMAND" "$@"
        ;;
    *)
        usage_error
        ;;
esac
