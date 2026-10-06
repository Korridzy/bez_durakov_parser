# Release deployment

## Overview

Delivery is pull-based. GitHub tests and publishes images; the operator runs the deployment command on the server. Publishing a stable GitHub Release is approval to deploy that version, not an automatic rollout. GitHub never connects to the server.

CI runs the complete root `make test` for pull requests and pushes to `main` on disposable runners. Only passing `main` pushes publish the tested backend, data collector and frontend candidates to GHCR, tagged `sha-<commit>`. Release promotion adds a version tag to those same digests without rebuilding.

This guide covers the bundled MySQL deployment with one backend replica. The executor doesn't support `DATASET`: deploy and rollback refuse it with exit 2. It remains a development mode.

## Server setup once

Use a deploy-only clone, separate from a development checkout. Keep tracked files clean and leave the clone detached at the release tag:

```bash
git fetch --tags origin
git checkout --detach v0.1.0
make setup
```

Use Linux, Python 3.11 with Poetry, Docker, Docker Compose 2.24.4 or newer, Git, Bash, `flock` and `jq`. The release images are built for Linux amd64. Don't run `make test`, `make rebuild` or the local rehearsal on the server.

Create `bd_shared/config.local.toml` from the example and set private values there, not in tracked `config.toml`. The production overlay bind-mounts this exact file into backend and collector, so it must exist as a file even when there are no other overrides:

```bash
cp bd_shared/config.local.toml.example bd_shared/config.local.toml
chmod 600 bd_shared/config.local.toml
```

Include this setting, along with your private database, model and allowed-origin settings:

```toml
[webreport]
reload = false
```

Production Compose also forces backend reload and debug off. Generated `.env*` and LiteLLM settings stay private and are regenerated from the configuration.

`BD_VM_DIR` defaults to the repository's `vm/` directory, which Compose sees as `../vm` from `webreport/`. If you override it, use the same absolute path for setup, deployment and administration. MySQL lives in `vm/mysql/mysql_data`; the three SQLite stores live in `vm/backend/checkpoints`. Don't point a new checkout at an empty directory when updating an existing installation.

Traefik joins `webreport_webreport-network` for the default project and routes to `http://frontend:8501`. For another Compose project, the network is `<project>_webreport-network`. Keep this attachment across infrastructure changes.

Set all three GHCR packages to Public and confirm their repository link. The server uses anonymous image pulls and the anonymous GitHub API; it needs no registry token.

Add a GitHub ruleset for `v*` tags that restricts creation, updates and deletion to the owner. Never move an approved release tag.

### Infrastructure procedure

MySQL and LiteLLM must already be running on the exact third-party digest pins of the intended release. To apply the initial loopback MySQL binding, or a later infrastructure digest bump, check out the intended code, generate the environment, then run from `webreport/`:

```bash
make generate-env
docker compose pull mysql litellm && docker compose up -d mysql litellm
```

This can interrupt those two services. Existing MySQL data stays in its bind mount. Keep the same Compose project and persistent paths, and retain Traefik's network attachment. Don't use the whole-stack stop or rebuild commands.

The executor refuses deployment if either infrastructure container is absent or its image differs from the release pin. It won't recreate MySQL or LiteLLM for you. Every runtime third-party digest bump needs this procedure before the next deploy; Dockerfile base-image bumps instead take effect in CI-built application images.

The LiteLLM digest pin deliberately selects the August 22, 2026 `main-stable` build used by the developer stack. Newer `main-stable` builds refuse to start without a LiteLLM master key. Before bumping this pin, decide how to set that master key and the matching backend client key. Then follow the infrastructure procedure above before the next deploy.

## Cutting a release

Choose a `main` commit whose CI and candidate publication passed. Tag that commit `vMAJOR.MINOR.PATCH`, such as `v0.1.0`, and publish a GitHub Release that isn't a draft or prerelease.

The promotion workflow checks the tag's ancestry on `main`, the successful CI run and its candidate-push step, and the candidates' source labels. It refuses an existing version tag or metadata asset that points elsewhere. It can also be dispatched manually for an existing stable release after correcting a promotion failure.

Wait for `release-metadata.json` and its sha256 marker in the release body before deploying. The metadata records the version, source commit, CI run ID and attempt, candidate tag, the three application `repo@sha256` references and a concrete Alembic revision. Read it to confirm you're approving the intended commit and schema. Infrastructure pins come from that tag's Compose file, not the metadata asset.

## Deploying

Run from the repository root on the server:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
```

`--llm-smoke` is mandatory for production rollouts, even though the CLI makes it optional. It makes a real model request and checks saved-report replay.

The stages are:

1. Acquire the deployment lock, fetch tags, require a clean tracked checkout and detach at the requested tag.
2. Fetch the stable release and validate the metadata asset, checksum marker, schema, tag commit, image source labels and the release image's single Alembic head. Pull application images by digest and cache the metadata and five-service pin file.
3. Generate environment files, check Compose and persistent paths, compare running infrastructure image IDs with the pins, check free space and run knowledge and tool preflights in the release backend image. Free space must be at least twice the measured MySQL and SQLite data size.
4. Read the live revision and compute pending migrations. An unversioned nonempty database is refused. Approve any pending revisions before services are stopped.
5. Stop collector and backend, then take a consistent MySQL dump and snapshots of the three SQLite stores with checksums and a manifest.
6. If needed, durably record `migration_started`, upgrade to the literal release revision and verify it. A failed migration retains the marker and leaves application services stopped.
7. Recreate missing or changed application containers. Both image IDs and Compose configuration hashes count as changes. Start an unchanged backend, wait up to 180 seconds for healthy readiness, then handle frontend and collector. MySQL and LiteLLM aren't recreated.
8. Run the smoke sequence, publish the successful state, then append the terminal audit event.

For pending migrations the TTY prompt is `Apply these migrations? [y/N]`. Only `y` approves. Without a TTY, pass explicit approval:

```bash
make deploy VERSION=v0.1.0 DEPLOY_ARGS="--approve-migration --llm-smoke"
```

`--yes` doesn't approve migrations. It acknowledges the collector fetch-window warning, which otherwise refuses the run near the scheduled fetch, and approves an explicit destructive restore. Don't add it by habit.

### State, logs and backups

The default server-local directory is `vm/deploy/`:

| Path | Contents |
| --- | --- |
| `logs/<timestamp>-<tag-or-cli>.log` | CLI output, smoke results and errors |
| `releases/<tag>/metadata.json` | Cached validated metadata |
| `releases/<tag>/compose.release.yml` | Generated five-service digest pins |
| `backups/<backup-id>/` | `mysql.sql`, present SQLite snapshots and `manifest.json` |
| `current.json` | Attempt, last successful release, migration marker and unaudited committed outcomes |
| `history.jsonl` | Append-only attempt and terminal audit events |
| `lock` | Shared deployment lock |

`current.json` is the commit point: success is committed only after smoke passes and that state file is durably replaced. `history.jsonl` is the audit trail, so an audit append failure after the commit is a warning, not a failed deployment.

Before a new deploy or rollback, reconciliation appends missing success events from committed outcomes, removes those recovery records only after durable audit writes, and marks unmatched started attempts as interrupted failures. It doesn't undo a deployment, restore data or clear a dirty migration marker.

Backups keep the newest five complete sets, plus protected sets including the latest schema-changing deploy backup. They're not copied off the box. Arrange a private off-box backup process as a follow-up; local snapshots alone don't protect against loss of the server.

`make deploy-status` prints a read-only report: the last successful release, the current attempt, the migration marker, the number of unaudited outcomes, the last 10 history events, each backup with its schema revision and age, and the cached release tags. Add `DEPLOY_ARGS=--json` for machine-readable output. It takes no lock and writes nothing, so it's safe to run during a deploy. A missing state directory is reported as a first install and exits 0. A corrupt `current.json`, history line or backup manifest gives an `E_STATE` (23) error and nothing is repaired.

### Exit codes and scripted use

**Make returns 2 on any recipe failure.** The real executor code is in the JSON error line on stderr, for example `{"exit_code":38,"error":"E_SMOKE","message":"..."}`. Isolation verification is an exception: it returns 1 with a `RESULT: FAIL` report rather than a JSON deployment error.

For scripts, call the wrapper directly so the executor's exit code passes through:

```bash
deploy/deploy.sh deploy v0.1.0 --approve-migration --llm-smoke
deploy/deploy.sh rollback v0.1.0 --llm-smoke
deploy/deploy.sh smoke --llm-smoke
deploy/deploy.sh verify-db-isolation
```

Use `poetry run python deploy/deploy.py --help` and each subcommand's `--help` for CLI syntax. The Python-only `select` command validates and caches a release without deploying it; it still pulls images and runs an image check. `resolve-rollback-target` prints a target tag. Use the shell wrapper for real deployments so checkout and locking happen before execution.

| Code | Error | Meaning |
| --- | --- | --- |
| 0 | Success | Requested operation passed |
| 1 | Isolation failure | Isolation report has a failed check |
| 2 | `E_USAGE` | Invalid arguments, unsupported DATASET or no rollback target |
| 3 | `E_LOCKED` | Another operation holds the lock |
| 4 | `E_PREFLIGHT` | Bootstrap or operational preflight failed |
| 10 | `E_RELEASE_NOT_FOUND` | Release not found |
| 11 | `E_RELEASE_NOT_STABLE` | Draft or prerelease |
| 12 | `E_RELEASE_ASSET` | Metadata asset missing or not unique |
| 13 | `E_METADATA_MARKER` | Marker or checksum invalid |
| 14 | `E_METADATA_SCHEMA` | Metadata contract invalid |
| 15 | `E_TAG_COMMIT` | Tag, repository or source commit mismatch |
| 16 | `E_RELEASE_FETCH` | Fetch, URL or response limit failed |
| 17 | `E_RELEASE_COMPOSE` | Release Compose or infrastructure pins invalid |
| 18 | `E_IMAGE_PULL` | Application image pull failed |
| 19 | `E_IMAGE_REVISION` | Image data or source revision label invalid |
| 20 | `E_IMAGE_INSPECT` | Image inspection failed |
| 21 | `E_ALEMBIC_HEAD` | Image head differs from metadata |
| 22 | `E_METADATA_CHANGED` | Cached metadata differs from release asset |
| 23 | `E_STATE` | State or local file I/O failed |
| 24 | `E_RELEASE_RESPONSE` | Release response shape invalid |
| 30 | `E_DEPLOY_FAILED` | Reserved general deployment failure |
| 31 | `E_MIGRATION_PLAN` | Revision query or migration ancestry failed |
| 32 | `E_MIGRATION_APPROVAL_REQUIRED` | Pending migrations without noninteractive approval |
| 33 | `E_MIGRATION_DECLINED` | Operator declined migrations |
| 34 | `E_QUIESCE` | Stopping application services failed |
| 35 | `E_BACKUP` | Consistent backup failed |
| 36 | `E_MIGRATION_FAILED` | Migration failed, inspect the retained marker |
| 37 | `E_RECREATE` | Application recreate or restart failed |
| 38 | `E_SMOKE` | Readiness, smoke or smoke cleanup failed |
| 39 | `E_ROLLBACK_SCHEMA` | Target and live schemas differ |
| 40 | `E_RESTORE` | Backup validation, approval or restore failed |
| 41 | `E_DEPLOYMENT_DIRTY` | Dirty migration marker requires explicit restore |
| 42 | `E_NOT_IMPLEMENTED` | Reserved for an accepted command without a handler; no command returns it now |

## Rollback and restore

Use `make rollback` to choose the previous successful release. After a failed attempt it chooses the last successful record; after a successful rollout it finds the preceding distinct successful tag in history. You can choose a tag explicitly:

```bash
make rollback VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
```

Rollback uses cached digest pins and metadata when available, checks image source labels, and runs preflight and smoke. It refuses a schema mismatch or dirty migration marker unless you explicitly name a matching backup:

```bash
make rollback VERSION=v0.1.0 DEPLOY_ARGS="--restore-backup <backup-id> --llm-smoke"
```

Replace `<backup-id>` with the directory name under `vm/deploy/backups/`. The backup's pre-deploy revision must equal the target release revision. Every file and checksum is validated before restore.

Restore stops collector and backend, states the backup timestamp, and asks `Restore this backup? Type yes:`. All MySQL and SQLite writes after that timestamp will be discarded. For an explicitly approved noninteractive restore, add `--yes`. A pre-restore safety copy is taken first. Refusal or failure can leave the application services stopped; read the recovery output before retrying.

There is no automatic rollback, downgrade or restore, including after failed smoke. Manual MySQL restore is destructive and must also be an explicit operator action. Never run `alembic downgrade` as a recovery shortcut.

## Smoke sequence

Deploy and rollback run S1-S7; `--llm-smoke` adds S8. To repeat the sequence locally on the server:

```bash
make deploy-smoke DEPLOY_ARGS="--llm-smoke"
```

| Step | Required result |
| --- | --- |
| S1 | Backend `/health` returns 200, `status=healthy`, with database, agents and llm_proxy all true |
| S2 | Live Alembic revision equals the release revision |
| S3 | Frontend HTML and all referenced script/link assets return 200 from the same origin |
| S4 | Frontend `/health` returns 200 with body `ok` |
| S5 | Frontend `/api/chats?limit=1` returns a JSON list envelope with `items` and `next_cursor` |
| S6 | MySQL and LiteLLM container IDs haven't changed during the operation |
| S7 | Collector is running |
| S8 | Canned chat succeeds, produces a report, saves and reloads it, Update advances its version, and the saved listing includes it |

S8 unsaves the report and removes its smoke chat; failure to clean up also fails smoke. It doesn't prove the public route or the survival of your older records. Do those manual checks in the first-rollout checklist.

Without release state, manual smoke uses the development Compose path and compares the live revision with the backend image head. Running smoke doesn't publish a successful deployment.

## Verifying isolation

On the server:

```bash
make deploy-verify-isolation
make deploy-verify-isolation DEPLOY_ARGS=--container-probe
```

The check inspects effective Compose bindings, running container bindings and listening sockets. With successful release state it requires MySQL, backend and frontend to bind only to `127.0.0.1`; in development mode only MySQL is required, and app-port rows are informational. The optional container probe requires connection refusal through a host gateway. Timeout isn't proof.

Require `RESULT: PASS`, inspect any SKIP rows, and perform the printed off-host recipe from another machine. With default ports:

```bash
nc -4 -z -w 3 <public-ipv4> 3306
nc -4 -z -w 3 <public-ipv4> 28000
nc -4 -z -w 3 <public-ipv4> 28501
nc -4 -z -w 3 <public-ipv4> 443
nc -6 -z -w 3 <public-ipv6> 3306
nc -6 -z -w 3 <public-ipv6> 28000
nc -6 -z -w 3 <public-ipv6> 28501
nc -6 -z -w 3 <public-ipv6> 443
```

Use configured ports if they differ; probe IPv6 only when assigned. The three private ports must refuse connections and the public control port must connect. A successful private connection is FAIL; a timeout is filtered or inconclusive, not PASS. Keep actual addresses and results private.

Host parser and Alembic administration can still use MySQL over loopback. For a remote MySQL client, open a private tunnel:

```bash
ssh -L 3306:127.0.0.1:3306 <server>
```

Connect the client to `127.0.0.1:3306` on your workstation while the tunnel is open. That local port must be free.

## Privacy rules

Never put a server name, public address, credential or private directory name in tracked files, issues, shared logs, release notes, assets or image labels. Don't share expanded commands containing them. Keep `config.local.toml`, `secret/`, generated environment files and runtime stores out of Git and image build contexts.

Deployment logs, backups, state and smoke evidence stay server-local under `vm/deploy/`. GitHub needs no server credentials, SSH deployment job or self-hosted server runner. Share only a completion statement, not server output.

## Dev vs prod matrix

| Area | Development | Production |
| --- | --- | --- |
| Start/update | `make start` from `webreport/` | `make deploy VERSION=vX.Y.Z DEPLOY_ARGS="--llm-smoke"` from root |
| Images | Local builds, source mounts for backend and collector | CI-tested application digests, no application source mounts |
| Configuration | Tracked defaults plus optional local overlay | Required `bd_shared/config.local.toml` bind mount |
| Reload/debug | Config-driven backend settings | Both forced off |
| Ports | MySQL loopback; app ports may be published on all interfaces | MySQL and app ports loopback only |
| Tests | Root `make test`, disposable CI suite and local rehearsal | No tests or rebuilds on the server |
| DATASET | Supported start mode | Executor refuses deploy and rollback |
| Data | Default `../vm` from Compose, overridable | Same persistent path across all releases |

## Container names

Fixed container names have been removed. Compose names containers `<project>-<service>-1`, for example `webreport-backend-1`. The dev Compose project name is the directory name, normally `webreport`, unless you set `COMPOSE_PROJECT_NAME` or an explicit project option. Keep the existing project name during rollout.

Use `docker compose ps` to discover names and service-based commands such as `docker compose logs backend`. Service DNS is unchanged.

## First rollout

This checklist is for the operator. The agent only checks command resolution locally; it never contacts the production server.

1. Merge the work to `main`. Confirm CI passed and all three `sha-<merge-commit>` candidate images exist. Open each GHCR package, set visibility to Public, and confirm its repository link. First pushes with the workflow token can default to private.
2. Add the owner-only `v*` tag ruleset for create, update and delete.
3. On the server, take a manual backup before changing anything. Quiesce backend and collector so SQLite files are stable, stop MySQL, archive `vm/mysql/mysql_data` and `vm/backend/checkpoints`, then restart those services:

   ```bash
   cd webreport
   docker compose stop backend data_collector mysql
   cd ..
   tar -czf <private-backup-path>/first-rollout.tar.gz vm/mysql/mysql_data vm/backend/checkpoints
   cd webreport
   docker compose start mysql backend data_collector
   cd ..
   ```

   Replace the backup placeholder with a private location outside `vm/`; use your actual `BD_VM_DIR` if overridden. Verify the archive before proceeding. Move hand-edited tracked config values into `bd_shared/config.local.toml`, set `[webreport] reload=false`, and restore tracked defaults only after preserving those edits. Run `git fetch origin` and use the merged `main` checkout for the next step. Confirm Traefik is attached to `webreport_webreport-network` and routes to `http://frontend:8501`; keep that attachment after the infrastructure recreate.
4. Apply the one-time infrastructure procedure from the merged checkout, not a whole-stack stop:

   ```bash
   make -C webreport generate-env
   cd webreport
   docker compose pull mysql litellm && docker compose up -d mysql litellm
   cd ..
   make deploy-verify-isolation
   ```

   This applies loopback MySQL publication and both digest pins. The executor refuses when running infrastructure images differ from its pins. Before release state exists, the isolation check requires only MySQL, so repeat it after deployment. Every runtime third-party digest bump needs this infrastructure procedure first.
5. Create tag `v0.1.0` on the merge commit, create and publish the stable GitHub Release, and wait for promotion to attach `release-metadata.json` and its checksum marker.
6. Deploy from root:

   ```bash
   make deploy VERSION=v0.1.0 DEPLOY_ARGS="--llm-smoke"
   ```

   Approve the migration prompt if shown. No migration is expected when both live and release revisions are `b1c2d3e4f5g6`; trust the actual computed plan rather than that expectation.
7. Run isolation verification again:

   ```bash
   make deploy-verify-isolation DEPLOY_ARGS=--container-probe
   ```

   Run the off-host `nc` commands in [Verifying isolation](#verifying-isolation) from another machine, for IPv4 and IPv6 if assigned. Require refused private ports and a connecting public control.
8. Open the UI through Traefik. Ask one real question that produces a report, save it, reload the page and reopen the saved report. This manual check covers the public route.
9. Confirm chats and saved reports recorded before rollout are still listed and readable. Keep local evidence under `vm/deploy/`, then report only `rollout done` in the planning session.

If `--llm-smoke` fails, the executor exits 38; Make reports 2. When there is a previous successful record, recovery output suggests `make rollback VERSION=<previous>`. The first rollout has no previous record, so fix forward or explicitly restore the manual backup from step 3. No automatic recovery runs.
