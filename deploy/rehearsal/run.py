"""Real local release rehearsal. Run through bash deploy/rehearsal.sh.

Only the release API is faked; images, promotion, MySQL, SQLite, HTTP, bootstrap,
backups and restore use their shipped implementations. Scratch writes below
construct test releases, not changes to the operator's checkout.
"""
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import urllib.request

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from deploy.deploy import read_generated_env  # noqa: E402

WORK = Path("/tmp") / f"bd-rehearsal-{os.getuid()}"
REPO = WORK / "repo"
PROJECT = "bdrehearsal"
REGISTRY = f"bd-rehearsal-registry-{os.getuid()}"
OLD = "a1b2c3d4e5f6"
NEW = "b1c2d3e4f5g6"
PROTECTED = tuple("webreport-" + name for name in
                  ("frontend", "backend", "data-collector", "litellm", "mysql"))
ENV = {key: value for key, value in os.environ.items()
       if not key.startswith(("BD_", "WEBREPORT_", "COMPOSE_", "GITHUB_", "POETRY_"))
       and key not in ("DATASET", "DATASET_DIR", "VIRTUAL_ENV", "PYTHONPATH", "MAKEFLAGS",
                       "RELEASE_COMPOSE", "TEST_IMAGE_COMPOSE")}
ENV.update(COMPOSE_PROJECT_NAME=PROJECT, BD_VM_DIR=str(WORK / "vm"),
           BD_XLSM_ARCHIVE_DIR=str(WORK / "archive"), BD_MYSQL_HOST_PORT="33406",
           POETRY_VIRTUALENVS_IN_PROJECT="true", PYTHONUNBUFFERED="1",
           BD_DEPLOY_REPO="Korridzy/bez_durakov_parser")


def command(args, *, cwd=REPO, env=None, expected=0, seconds=120, show=False, input=None):
    allocates = args[:2] in (["docker", "build"], ["docker", "push"], ["poetry", "install"]) or (
        args[:2] == ["bash", "deploy/deploy.sh"] and args[2] in ("deploy", "rollback"))
    if allocates:
        free = shutil.disk_usage("/tmp").free
        print(f"DISK free_bytes={free}; minimum={5 * 1024**3}", flush=True)
        assert free >= 5 * 1024**3, "STOP: less than 5 GiB free; do not retry before freeing space"
    print("$ " + shlex.join(map(str, args)), flush=True)
    result = subprocess.run(args, cwd=cwd, env=env or ENV, text=True, input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=seconds)
    print(f"EXIT={result.returncode} expected={expected}", flush=True)
    if show or result.returncode != expected:
        print(result.stdout, end="", flush=True)
    assert result.returncode == expected, (args, result.returncode, expected)
    return result.stdout


def compose(*args, **kwargs):
    return command(["docker", "compose", "-p", PROJECT, "--project-directory", str(REPO / "webreport"),
                    "-f", str(REPO / "webreport/docker-compose.yml"), *args], **kwargs)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def read_json(path):
    return json.loads(path.read_text())


def snapshot():
    raw = command(["docker", "ps", "--format", "{{.Names}} {{.ID}} {{.Status}}"], cwd=SOURCE)
    rows = {line.split()[0]: line for line in raw.splitlines() if line.split()[0] in PROTECTED}
    assert set(rows) == set(PROTECTED), "all five developer containers must already be up"
    print("Protected stack:\n" + "\n".join(rows.values()), flush=True)
    return {name: row.split()[1] for name, row in rows.items()}


def free_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return sock.getsockname()[1]


def cleanup():
    """Only remove resources whose ownership is recorded by this rehearsal."""
    ids = command(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT],
                  cwd=SOURCE).split()
    if ids:
        for identifier in ids:
            directory = command(["docker", "inspect", identifier, "--format",
                                 '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'],
                                cwd=SOURCE).strip()
            assert directory == str(REPO / "webreport"), "refusing a foreign bdrehearsal stack"
        compose("down", "-v", "--timeout", "20", seconds=90)
    registries = command(["docker", "ps", "-aq", "--filter", "name=^/" + REGISTRY + "$"], cwd=SOURCE).split()
    for identifier in registries:
        owner = command(["docker", "inspect", identifier, "--format",
                         '{{index .Config.Labels "bd.rehearsal.owner"}}'], cwd=SOURCE).strip()
        assert owner == str(WORK), "refusing a foreign registry"
        command(["docker", "rm", "-fv", identifier], cwd=SOURCE)
    ownership = WORK / "images.json"
    if ownership.exists():
        for ref in reversed(read_json(ownership)):
            assert ref.startswith("127.0.0.1:") and "/bd-rehearsal/" in ref
            found = command(["docker", "image", "ls", "-q", ref], cwd=SOURCE).strip()
            if found:
                command(["docker", "image", "rm", ref], cwd=SOURCE)
        # Pulled digest references can keep image storage alive after removing tags.
        prefix = read_json(WORK / "registry.json")["prefix"]
        refs = command(["docker", "image", "ls", "--digests", "--format",
                        "{{.Repository}}@{{.Digest}}"], cwd=SOURCE).splitlines()
        for ref in set(refs):
            if ref.startswith(prefix + "/") and "@sha256:" in ref:
                command(["docker", "image", "rm", ref], cwd=SOURCE)
    if WORK.exists():
        # Container-owned MySQL files are not writable by the host user.
        vm = WORK / "vm"
        if vm.exists():
            mysql = (REPO / "webreport/docker-compose.yml").read_text().split("image: ", 1)[1].split()[0]
            command(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                     "-v", str(WORK) + ":/cleanup", mysql, "-c",
                     "rm -rf /cleanup/vm /cleanup/archive"], cwd=SOURCE)
        shutil.rmtree(WORK)
    assert not command(["docker", "ps", "-aq", "--filter",
                        "label=com.docker.compose.project=" + PROJECT], cwd=SOURCE).strip()
    for port in (28400, 28401, 33406):
        free_port(port)
    print("CLEANUP PASS: owned containers, registry, images, scratch paths and ports removed", flush=True)


def sql(query):
    # Fixture credentials are generated locally, never printed or placed in argv.
    values = read_generated_env(REPO / "webreport/.env.mysql")
    env = dict(ENV, MYSQL_PWD=values["MYSQL_ROOT_PASSWORD"])
    return compose("exec", "-T", "-e", "MYSQL_PWD", "mysql", "mysql", "-uroot",
                   "-h127.0.0.1", "-N", values["MYSQL_DATABASE"], "-e", query, env=env).strip()


def http(method, path, body=None, expected=200):
    url = "http://127.0.0.1:28401" + path
    print(f"HTTP {method} {url} body={json.dumps(body)} expected={expected}", flush=True)
    request = urllib.request.Request(url, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode()
        print(f"HTTP/{response.version} {response.status}\n{response.headers}\n{data}", flush=True)
        assert response.status == expected
        return json.loads(data) if data else {}


def current():
    return read_json(WORK / "vm/deploy/current.json")


def history():
    return [json.loads(line) for line in (WORK / "vm/deploy/history.jsonl").read_text().splitlines()]


def container_ids():
    return {name: compose("ps", "-aq", name).strip() for name in
            ("mysql", "litellm", "backend", "frontend", "data_collector")}


def verify(revision, tag, infra, chat=None):
    assert sql("SELECT version_num FROM alembic_version") == revision
    teams = sql("SELECT team_id,team_name FROM teams ORDER BY team_id")
    assert teams.splitlines() == ["17001\trehearsal alpha", "17002\trehearsal beta"], teams
    state = current()
    assert state["last_successful"]["tag"] == tag and "stage" not in state
    ids = container_ids()
    assert all(ids[name] == identifier for name, identifier in infra.items())
    assert all(ids.values())
    if chat:
        assert chat in [item["id"] for item in http("GET", "/api/chats")["items"]]
    print(f"PASS revision={revision} committed={tag}; teams 17001/17002 restored; "
          f"chat={chat}; unchanged infra={json.dumps(infra)}", flush=True)


def deploy(args, tag, expected=0, error=None, make=False):
    env = dict(ENV, BD_DEPLOY_RELEASE_FILE=str(WORK / tag / "release.json"))
    argv = ["make", "deploy", "VERSION=" + tag, "DEPLOY_ARGS=--yes"] if make else ["bash", "deploy/deploy.sh", *args]
    output = command(argv, env=env, expected=expected, seconds=1800, show=True, input="")
    if expected:
        records = [json.loads(line) for line in output.splitlines() if line.startswith('{"exit_code"')]
        assert any(record["exit_code"] == (32 if make else expected) and record["error"] == error
                   for record in records), "missing structured error line"
    else:
        assert all(f"S{i} PASS" in output for i in range(1, 8))
    return output


def commit(message):
    command(["git", "add", "-A"])
    command(["git", "-c", "user.name=Rehearsal", "-c", "user.email=rehearsal@localhost",
             "commit", "-m", message])
    return command(["git", "rev-parse", "HEAD"]).strip()


def main():
    before = snapshot()
    cleanup()
    WORK.mkdir(mode=0o700)
    write_json(WORK / "images.json", [])
    for port in (28400, 28401, 33406):
        free_port(port)
    try:
        registry_port = free_port(5000)
    except OSError:
        registry_port = free_port(0)
    prefix = f"127.0.0.1:{registry_port}/bd-rehearsal"
    write_json(WORK / "registry.json", {"prefix": prefix})
    ENV["BD_RELEASE_IMAGE_PREFIX"] = prefix
    try:
        command(["git", "clone", "--bare", str(SOURCE), str(WORK / "origin.git")], cwd=SOURCE)
        command(["git", "clone", str(WORK / "origin.git"), str(REPO)], cwd=SOURCE)
        # Include uncommitted lane changes in the disposable fixture, never in origin/main.
        for name in ("deploy", "webreport", "Makefile"):
            paths = command(["git", "ls-files", "--cached", "--others", "--exclude-standard", name],
                            cwd=SOURCE).splitlines()
            for path in paths:
                target = REPO / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE / path, target)
        command(["git", "checkout", "-B", "main"])
        shutil.copy2(SOURCE / "deploy/rehearsal/mock.yaml", REPO / "webreport/litellm_config.yaml")
        commit("test: configure isolated mock for rehearsal")
        overlay = """[database]
url = "mysql+pymysql://durak:devpass@127.0.0.1:33406/bez_durakov"
docker_url = "mysql+pymysql://durak:devpass@mysql:3306/bez_durakov"
[webreport]
backend_port = 28400
frontend_port = 28401
reload = false
agent_model = "rehearsal-mock"
archive_enabled = true
[xlsm_fetch]
start_time = "12:00"
"""
        (REPO / "bd_shared/config.local.toml").write_text(overlay)
        migration = REPO / "migrations/versions/b1c2d3e4f5g6_add_goal_column_to_pref.py"
        migration_source = migration.read_text()
        migration.unlink()
        commits = {"v0.1.0": commit("test: rehearsal old schema")}
        command(["git", "tag", "v0.1.0"])
        migration.write_text(migration_source)
        prod = REPO / "webreport/docker-compose.prod.yml"
        prod.write_text(prod.read_text().replace('      WEBREPORT_RELOAD: "false"',
                                                '      BD_REHEARSAL_MARKER: "v2"\n      WEBREPORT_RELOAD: "false"'))
        commits["v0.2.0"] = commit("test: rehearsal migration and config")
        command(["git", "tag", "v0.2.0"])
        backend = REPO / "webreport/Dockerfile.backend"
        original = backend.read_text()
        assert 'CMD ["python", "start.py"]' in original
        backend.write_text(original.replace('CMD ["python", "start.py"]', 'CMD ["false"]'))
        commits["v0.3.0"] = commit("test: rehearsal failed backend")
        command(["git", "tag", "v0.3.0"])
        command(["git", "push", "origin", "main", "--tags"])
        command(["git", "fetch", "origin"])
        command(["poetry", "install", "--no-root"], seconds=600)
        command(["git", "checkout", "--detach", "v0.1.0"])
        command(["make", "-s", "--no-print-directory", "-C", "webreport", "generate-env"])
        compose("up", "-d", "mysql", "litellm", seconds=180)
        # Docker's health wait is bounded; MySQL needs TCP (not its temporary init socket).
        compose("up", "-d", "--wait", "--wait-timeout", "180", "litellm", seconds=200)
        probe = ('import json,urllib.request; r=urllib.request.urlopen('
                 '"http://127.0.0.1:4000/health?model=rehearsal-mock",timeout=20); '
                 'd=json.load(r); print(r.status,dict(r.headers),json.dumps(d)); '
                 'assert r.status==200 and d["healthy_count"]==1 and d["unhealthy_count"]==0')
        compose("exec", "-T", "litellm", "python", "-c", probe, show=True)
        # Authenticated TCP connection retries are confined to the bounded readiness command.
        compose("exec", "-T", "mysql", "sh", "-c",
                'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; '
                'timeout 120 sh -c \'until mysql -h127.0.0.1 -uroot "$MYSQL_DATABASE" -N -e "SELECT 1" '
                '2>/dev/null; do :; done\'', seconds=130)
        command(["poetry", "run", "alembic", "upgrade", OLD], show=True)
        sql("INSERT INTO teams(team_id,team_name) VALUES(17001,'rehearsal alpha'),(17002,'rehearsal beta')")
        infra = {name: compose("ps", "-q", name).strip() for name in ("mysql", "litellm")}
        command(["docker", "run", "-d", "--name", REGISTRY, "--label", "bd.rehearsal.owner=" + str(WORK),
                 "-p", f"127.0.0.1:{registry_port}:5000", "registry:2"])
        command(["curl", "--fail", "--silent", "--retry", "10", "--retry-connrefused",
                 "--retry-max-time", "20", f"http://127.0.0.1:{registry_port}/v2/"])
        owned = []
        for tag, sha in commits.items():
            command(["git", "checkout", "--detach", tag])
            for component, dockerfile in (("backend", "backend"), ("data-collector", "data_collector"),
                                          ("frontend", "frontend")):
                ref = f"{prefix}/{component}:sha-{sha}"
                owned += [ref, f"{prefix}/{component}:{tag}"]
                write_json(WORK / "images.json", owned)
                command(["docker", "build", "-f", f"webreport/Dockerfile.{dockerfile}",
                         "--build-arg", "SOURCE_COMMIT=" + sha, "-t", ref, "."], seconds=1800)
                label = command(["docker", "image", "inspect", ref, "--format",
                                 '{{index .Config.Labels "org.opencontainers.image.revision"}}']).strip()
                assert label == sha
                command(["docker", "push", ref], seconds=600)
            fixture = WORK / tag
            fixture.mkdir()
            release = {"tag_name": tag, "draft": False, "prerelease": False, "body": "Local rehearsal", "assets": []}
            write_json(fixture / "release.json", release)
            write_json(fixture / "event.json", {"release": release})
            write_json(fixture / "runs.json", {"workflow_runs": [
                {"id": 77, "run_attempt": 1, "head_sha": sha, "head_branch": "main", "event": "push",
                 "status": "completed", "conclusion": "success", "created_at": "2026-10-06T00:00:00Z"}]})
            write_json(fixture / "jobs.json", {"jobs": [{"name": "suite", "conclusion": "success",
                       "steps": [{"name": "Push candidate images", "conclusion": "success"}]}]})
            command(["bash", "deploy/promote.sh", "--event", str(fixture / "event.json"),
                     "--api-base", f"http://127.0.0.1:{registry_port}",
                     "--gh-bin", str(SOURCE / "deploy/rehearsal/gh")],
                    env=dict(ENV, SHIM_STATE=str(fixture)), seconds=600, show=True)
            meta = read_json(fixture / "asset.json")
            assert meta["source_commit"] == sha
            for component, ref in meta["images"].items():
                image = component.replace("_", "-")
                digest = json.loads(command(["docker", "buildx", "imagetools", "inspect",
                                             f"{prefix}/{image}:{tag}", "--format", "{{json .Manifest.Digest}}"]))
                assert ref == f"{prefix}/{image}@{digest}"
            print("PASS promotion digest continuity " + tag, flush=True)
        deploy(["deploy", "v0.1.0", "--yes", "--approve-migration"], "v0.1.0")
        chat = http("POST", "/api/chats", {"title": "Rehearsal restore fixture"}, 201)["id"]
        verify(OLD, "v0.1.0", infra, chat)
        # Dirty checkout must refuse without changing containers, DB or deployment state.
        state_before = current()
        tracked = REPO / "deploy/smoke_question.txt"
        saved = tracked.read_bytes()
        tracked.write_bytes(saved + b"\n")
        deploy(["deploy", "v0.2.0", "--yes"], "v0.2.0", 4, "E_PREFLIGHT")
        tracked.write_bytes(saved)
        assert current() == state_before
        verify(OLD, "v0.1.0", infra, chat)
        deploy(["deploy", "v0.2.0", "--yes"], "v0.2.0", 32, "E_MIGRATION_APPROVAL_REQUIRED")
        verify(OLD, "v0.1.0", infra, chat)
        deploy(["deploy", "v0.2.0", "--yes", "--approve-migration"], "v0.2.0")
        verify(NEW, "v0.2.0", infra, chat)
        assert [e["event"] for e in history()] == ["started", "success", "started", "success"]
        backend_id = container_ids()["backend"]
        assert "BD_REHEARSAL_MARKER=v2" in json.loads(command(
            ["docker", "inspect", backend_id, "--format", "{{json .Config.Env}}"]))
        backup = current()["last_successful"]["backup_id"]
        manifest = read_json(WORK / "vm/deploy/backups" / backup / "manifest.json")
        assert manifest["db_revision_before"] == OLD
        assert manifest["files"]["mysql.sql"]["present"] and manifest["files"]["chats.db"]["present"]
        deploy(["rollback", "v0.1.0", "--yes"], "v0.1.0", 39, "E_ROLLBACK_SCHEMA")
        # Change both real stores after the snapshot: their restoration cannot pass as a no-op.
        sql("DELETE FROM teams WHERE team_id IN (17001,17002)")
        http("DELETE", "/api/chats/" + chat, expected=204)
        assert sql("SELECT COUNT(*) FROM teams WHERE team_id IN (17001,17002)") == "0"
        assert chat not in [item["id"] for item in http("GET", "/api/chats")["items"]]
        print("PASS before restore: both fixture teams absent, backed-up chat absent", flush=True)
        deploy(["rollback", "v0.1.0", "--yes", "--restore-backup", backup], "v0.1.0")
        verify(OLD, "v0.1.0", infra, chat)
        assert command(["git", "rev-parse", "HEAD"]).strip() == commits["v0.1.0"]
        assert not any(value.startswith("BD_REHEARSAL_MARKER=") for value in json.loads(command(
            ["docker", "inspect", container_ids()["backend"], "--format", "{{json .Config.Env}}"])))
        print("PASS real MySQL teams and SQLite chats replacement; target Compose context restored", flush=True)
        deploy(["deploy", "v0.2.0", "--yes", "--approve-migration"], "v0.2.0")
        verify(NEW, "v0.2.0", infra, chat)
        dirty = current()
        backup = dirty["last_successful"]["backup_id"]
        assert read_json(WORK / "vm/deploy/backups" / backup / "manifest.json")["db_revision_before"] == OLD
        dirty["stage"] = "migration_started"
        write_json(WORK / "vm/deploy/current.json", dirty)
        ids = container_ids()
        deploy(["deploy", "v0.2.0", "--yes"], "v0.2.0", 41, "E_DEPLOYMENT_DIRTY")
        deploy(["rollback", "v0.1.0", "--yes"], "v0.1.0", 41, "E_DEPLOYMENT_DIRTY")
        assert current() == dirty and container_ids() == ids
        assert sql("SELECT version_num FROM alembic_version") == NEW
        deploy(["rollback", "v0.1.0", "--yes", "--restore-backup", backup], "v0.1.0")
        verify(OLD, "v0.1.0", infra, chat)
        deploy([], "v0.2.0", 2, "E_MIGRATION_APPROVAL_REQUIRED", make=True)
        verify(OLD, "v0.1.0", infra, chat)
        deploy(["deploy", "v0.2.0", "--yes", "--approve-migration"], "v0.2.0")
        verify(NEW, "v0.2.0", infra, chat)
        output = deploy(["deploy", "v0.3.0", "--yes"], "v0.3.0", 38, "E_SMOKE")
        assert "Recovery: make rollback VERSION=v0.2.0" in output
        assert [e["event"] for e in history() if e["tag"] == "v0.3.0"] == ["started", "failed"]
        assert current()["last_successful"]["tag"] == "v0.2.0"
        assert sql("SELECT version_num FROM alembic_version") == NEW
        assert all(container_ids()[name] == identifier for name, identifier in infra.items())
        deploy(["rollback", "--yes"], "v0.2.0")
        verify(NEW, "v0.2.0", infra, chat)
        output = command(["bash", "deploy/deploy.sh", "verify-db-isolation", "--container-probe"], show=True)
        assert "RESULT: PASS" in output and "FAIL" not in "\n".join(
            line for line in output.splitlines() if line.startswith("FAIL"))
        print("ALL REHEARSAL SCENARIOS PASS", flush=True)
    finally:
        cleanup()
        assert snapshot() == before, "developer stack container IDs changed"


if __name__ == "__main__":
    # Lock a stable directory inode: no stale lock file or unlink/reopen race.
    lock = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        main()
    finally:
        os.close(lock)
