#!/usr/bin/env bash
# Promote immutable candidates, then publish the shared metadata contract.
set -euo pipefail

repo=${GITHUB_REPOSITORY:-Korridzy/bez_durakov_parser}
tag=${BD_RELEASE_TAG:-}
api=${BD_RELEASE_API_BASE:-https://api.github.com}
gh_bin=${BD_RELEASE_GH_BIN:-gh}
event=${GITHUB_EVENT_PATH:-}
while (($#)); do
    case "$1" in
        --repo) repo=$2; shift 2 ;;
        --tag) tag=$2; shift 2 ;;
        --api-base) api=$2; shift 2 ;;
        --gh-bin) gh_bin=$2; shift 2 ;;
        --event) event=$2; shift 2 ;;
        *) printf 'E_USAGE: unknown option %s\n' "$1" >&2; exit 2 ;;
    esac
done
fail() { printf '%s: %s\n' "$1" "$2" >&2; exit 1; }
valid_tag() { [[ $1 =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; }

# Validate the decoded JSON string before Bash can discard NUL or newline bytes.
if [[ -n $event ]] && jq -e 'has("release")' "$event" >/dev/null; then
    event_tag=$(jq -er '.release.tag_name | select(type == "string") |
        select(test("\\Av(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\z"))' "$event") ||
        fail E_INVALID_TAG 'expected vMAJOR.MINOR.PATCH'
    [[ -z $tag || $tag == "$event_tag" ]] || fail E_INVALID_TAG 'event and requested tag differ'
    tag=$event_tag
    if jq -e '.release.draft == true or .release.prerelease == true' "$event" >/dev/null; then
        printf 'SKIP: draft or prerelease\n'
        exit 0
    fi
fi
valid_tag "$tag" || fail E_INVALID_TAG 'expected vMAJOR.MINOR.PATCH'
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail E_USAGE 'invalid repository'

cd "$(dirname "${BASH_SOURCE[0]}")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
api=${api%/}
"$gh_bin" api "$api/repos/$repo/releases/tags/$tag" >"$tmp/release.json"
jq -e --arg tag "$tag" '.tag_name == $tag and (.draft | type == "boolean") and
    (.prerelease | type == "boolean")' "$tmp/release.json" >/dev/null ||
    fail E_RELEASE_INVALID 'release tag or flags are invalid'
if jq -e '.draft or .prerelease' "$tmp/release.json" >/dev/null; then
    printf 'SKIP: draft or prerelease\n'
    exit 0
fi

commit=$(git rev-parse --verify "${tag}^{commit}")
[[ $commit =~ ^[0-9a-f]{40}$ ]] || fail E_INVALID_COMMIT 'tag must resolve to a commit'
[[ $(git rev-parse HEAD) == "$commit" ]] || fail E_SOURCE_COMMIT 'checkout must match the release tag'
[[ -z $(git status --porcelain --untracked-files=all) ]] ||
    fail E_SOURCE_DIRTY 'release checkout must be clean'
git merge-base --is-ancestor "$commit" origin/main ||
    fail E_CI_NOT_APPROVED 'tag commit is not on main'
"$gh_bin" api "$api/repos/$repo/actions/workflows/ci.yml/runs?head_sha=$commit&branch=main&event=push&status=success&per_page=10" >"$tmp/runs.json"
run=$(jq -cer --arg commit "$commit" '[.workflow_runs[] |
    select(.head_sha == $commit and .head_branch == "main" and .event == "push" and
        .status == "completed" and .conclusion == "success")] |
    sort_by(.created_at, .id) | last | select(. != null)' "$tmp/runs.json") ||
    fail E_CI_NOT_APPROVED 'no successful main push CI run'
run_id=$(jq -er '.id | select(type == "number" and . > 0 and . == floor)' <<<"$run")
attempt=$(jq -er '.run_attempt | select(type == "number" and . > 0 and . == floor)' <<<"$run")
"$gh_bin" api --paginate --slurp "$api/repos/$repo/actions/runs/$run_id/attempts/$attempt/jobs?per_page=100" >"$tmp/jobs.json"
jq -e '[.[] | .jobs[] | select(.name == "suite")] |
    length == 1 and .[0].conclusion == "success" and
    ([.[0].steps[] | select(.name == "Push candidate images")] |
        length == 1 and .[0].conclusion == "success")' "$tmp/jobs.json" >/dev/null ||
    fail E_CI_NOT_APPROVED 'suite or Push candidate images did not succeed'

prefix=${BD_RELEASE_IMAGE_PREFIX:-ghcr.io/korridzy/bez_durakov_parser}
components=(backend data_collector frontend)
names=(backend data-collector frontend)
declare -a digests create
for i in "${!components[@]}"; do
    image=$prefix/${names[$i]}
    digest=$(docker buildx imagetools inspect "$image:sha-$commit" --format '{{json .Manifest.Digest}}' |
        jq -er 'select(test("^sha256:[0-9a-f]{64}$"))') ||
        fail E_CANDIDATE_MISSING "${components[$i]} candidate is missing or unreadable"
    digests[i]=$digest
    docker pull "$image@$digest" >/dev/null
    revision=$(docker image inspect "$image@$digest" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
    [[ $revision == "$commit" ]] || fail E_CANDIDATE_REVISION "${components[$i]} revision differs from tag commit"
    if destination=$(docker buildx imagetools inspect "$image:$tag" --format '{{json .Manifest.Digest}}' 2>"$tmp/inspect.err"); then
        [[ $(jq -er . <<<"$destination") == "$digest" ]] ||
            fail E_PROMOTION_CONFLICT "${components[$i]} destination points to another digest"
        create[i]=false
    else
        # A transport/auth failure must not be mistaken for an absent tag.
        grep -Eqi 'not found|manifest unknown|404' "$tmp/inspect.err" ||
            fail E_REGISTRY_UNAVAILABLE "${components[$i]} destination cannot be checked"
        create[i]=true
    fi
done

poetry install --no-root
heads=$(poetry run alembic heads)
[[ $heads =~ ^([A-Za-z0-9_]{1,32})[[:space:]]+\(head\)$ ]] ||
    fail E_ALEMBIC_HEAD 'expected exactly one concrete Alembic head'
revision=${BASH_REMATCH[1]}
poetry run python -c '
import json, sys
from pathlib import Path
from deploy import release_metadata as r
root, repo, tag, commit, run, attempt, revision, prefix, *digests = sys.argv[1:]
meta = r.ReleaseMetadata(
    schema_version=r.SCHEMA_VERSION, repository=repo, version=tag, source_commit=commit,
    ci_run_id=int(run), ci_run_attempt=int(attempt), built_from_candidate_tag="sha-" + commit,
    images=dict(zip(("backend", "data_collector", "frontend"),
                    (prefix + "/" + name + "@" + digest for name, digest in
                     zip(("backend", "data-collector", "frontend"), digests)))),
    alembic_revision=revision,
)
data = r.dumps(meta)
Path(root, r.ASSET_NAME).write_bytes(data)
body = json.loads(Path(root, "release.json").read_text())["body"] or ""
marker = r.format_marker(r.sha256_hex(data))
if r.MARKER_RE.search(body.replace("\r\n", "\n")):
    try:
        previous = r.parse_marker(body)
    except r.MetadataError as error:
        sys.exit("E_PROMOTION_CONFLICT: " + str(error))
    if previous != r.sha256_hex(data):
        sys.exit("E_PROMOTION_CONFLICT: release marker differs")
    Path(root, "edit").write_text("false")
else:
    body = body + ("\n" if body and not body.endswith("\n") else "") + marker + "\n"
    Path(root, "edit").write_text("true")
Path(root, "notes").write_text(body)
' "$tmp" "$repo" "$tag" "$commit" "$run_id" "$attempt" "$revision" "$prefix" "${digests[@]}"

asset_count=$(jq '[.assets[] | select(.name == "release-metadata.json")] | length' "$tmp/release.json")
[[ $asset_count -le 1 ]] || fail E_PROMOTION_CONFLICT 'multiple metadata assets'
if [[ $asset_count == 1 ]]; then
    asset_id=$(jq -er '.assets[] | select(.name == "release-metadata.json") | .id' "$tmp/release.json")
    "$gh_bin" api "$api/repos/$repo/releases/assets/$asset_id" -H 'Accept: application/octet-stream' >"$tmp/existing.json"
    cmp -s "$tmp/existing.json" "$tmp/release-metadata.json" ||
        fail E_PROMOTION_CONFLICT 'metadata asset differs'
fi

# Every component and release-side conflict has been checked before any mutation.
for i in "${!components[@]}"; do
    image=$prefix/${names[$i]}
    if [[ ${create[$i]} == true ]]; then
        docker buildx imagetools create --prefer-index=false --tag "$image:$tag" "$image@${digests[$i]}"
    fi
    promoted=$(docker buildx imagetools inspect "$image:$tag" --format '{{json .Manifest.Digest}}' | jq -er .)
    [[ $promoted == "${digests[$i]}" ]] || fail E_PROMOTION_DIGEST "${components[$i]} promoted digest differs"
done
if [[ $asset_count == 0 ]]; then
    "$gh_bin" release upload "$tag" "$tmp/release-metadata.json" --repo "$repo"
fi
if [[ $(<"$tmp/edit") == true ]]; then
    "$gh_bin" release edit "$tag" --notes-file "$tmp/notes" --repo "$repo"
fi
printf 'PROMOTED: %s commit=%s ci=%s attempt=%s\n' "$tag" "$commit" "$run_id" "$attempt"
