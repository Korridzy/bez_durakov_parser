"""Prove that private files never reach a Docker build context or an image layer.

The check copies the working tree, plants a random canary into every kind of private file the
build must exclude, builds the three application images (plus a probe image that holds the whole
build context), saves them with `docker save` and scans every layer for the canary. Exit 0 means
no canary was found and `bd_shared/config.toml` is still in the context; exit 1 lists the leaks.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import IO

CHUNK_SIZE = 1024 * 1024
BUILD_TIMEOUT_SECONDS = 1800
SAVE_TIMEOUT_SECONDS = 900
GIT_TIMEOUT_SECONDS = 120

PLANTED_FILES = (
    ".env",
    ".env.canary",
    "bd_shared/config.local.toml",
    "bd_shared/config.local.toml.backup",
    "webreport/.env.backend",
    "webreport/litellm_settings.generated.yaml",
    "vm/canary",
    "secret/canary",
    "range/canary",
    "xlsm_archive/canary",
    "data_to_parse/canary",
    "webreport/backend/private.db",
)

PROBE_DOCKERFILE = "FROM scratch\nCOPY . /context\n"
PROBE_REQUIRED_PATH = "context/bd_shared/config.toml"


def _contains(stream: IO[bytes], needle: bytes) -> bool:
    """Stream the file in chunks, keeping a tail so a needle split across chunks is still found."""
    tail = b""
    while chunk := stream.read(CHUNK_SIZE):
        window = tail + chunk
        if needle in window:
            return True
        tail = window[-(len(needle) - 1) :] if len(needle) > 1 else b""
    return False


def _layer_members(saved_tar: Path) -> Iterator[tuple[str, str, IO[bytes] | None]]:
    """Yield (path, link target, content stream) for every member of every layer of a `docker save` tarball.

    Any regular file of the outer tarball that opens as a tar archive (plain or compressed) is a
    layer. Layers are read one by one without applying whiteouts, so a file deleted by a later
    layer is still seen in the layer that added it. Directories, symlinks and hardlinks are
    yielded too, with no content stream.
    """
    with tarfile.open(saved_tar, "r:") as outer:
        for entry in outer:
            if not entry.isfile():
                continue
            blob = outer.extractfile(entry)
            if blob is None:
                continue
            try:
                layer = tarfile.open(fileobj=blob, mode="r:*")
            except tarfile.TarError:
                continue
            with layer:
                for member in layer:
                    stream = layer.extractfile(member) if member.isfile() else None
                    yield member.name.removeprefix("./"), member.linkname, stream


def scan_saved_images(tar_path: Path, needle: str) -> list[str]:
    """Return the sorted layer member paths whose path, link target or content contains the needle."""
    encoded = needle.encode()
    found = {
        path
        for path, linkname, stream in _layer_members(tar_path)
        if needle in path or needle in linkname or (stream is not None and _contains(stream, encoded))
    }
    return sorted(found)


def _saved_paths(tar_path: Path) -> set[str]:
    return {path for path, _, _ in _layer_members(tar_path)}


def _run(command: list[str], *, cwd: Path, timeout: int, stdin: str | None = None) -> None:
    subprocess.run(command, cwd=cwd, input=stdin, text=True, timeout=timeout, check=True)


def copy_working_tree(repo_root: Path, destination: Path) -> None:
    """Copy tracked and untracked-but-not-ignored files, uncommitted edits included."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
    ).stdout
    for raw in filter(None, listing.split(b"\0")):
        relative = os.fsdecode(raw)
        source = repo_root / relative
        if source.is_dir() and not source.is_symlink():
            continue
        if not os.path.lexists(source):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def plant_canary(context: Path, canary: str) -> None:
    for relative in PLANTED_FILES:
        target = context / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {canary}\n")


def _build(context: Path, tag: str, dockerfile: str, target: str | None = None) -> None:
    command = ["docker", "build", "--no-cache", "-f", dockerfile, "-t", tag]
    if target:
        command += ["--target", target]
    _run([*command, str(context)], cwd=context, timeout=BUILD_TIMEOUT_SECONDS)


def _build_probe(context: Path, tag: str) -> None:
    command = ["docker", "build", "--no-cache", "-f", "-", "-t", tag, str(context)]
    _run(command, cwd=context, timeout=BUILD_TIMEOUT_SECONDS, stdin=PROBE_DOCKERFILE)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Docker build contexts and image layers for planted private-file canaries.")
    parser.add_argument(
        "--scan-existing",
        nargs="+",
        metavar="TAG",
        help="scan these prebuilt images instead of building the three application images",
    )
    parser.add_argument("--tag-prefix", default="bd-canary", help="prefix of the images this check builds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parent.parent
    canary = f"CANARY-{uuid.uuid4().hex}"
    probe_tag = f"{args.tag_prefix}-context-probe"
    built: list[str] = []
    images: list[str]
    scratch = Path(tempfile.mkdtemp(prefix="bd-canary-"))
    context = scratch / "context"
    leaks: list[str] = []
    try:
        copy_working_tree(repo_root, context)
        plant_canary(context, canary)
        if args.scan_existing:
            images = list(args.scan_existing)
        else:
            images = []
            for name, dockerfile, target in (
                ("backend", "webreport/Dockerfile.backend", None),
                ("data-collector", "webreport/Dockerfile.data_collector", None),
                ("frontend", "webreport/Dockerfile.frontend", None),
                ("frontend-build", "webreport/Dockerfile.frontend", "build"),
            ):
                tag = f"{args.tag_prefix}-{name}"
                built.append(tag)
                _build(context, tag, dockerfile, target)
                images.append(tag)
        built.append(probe_tag)
        _build_probe(context, probe_tag)
        images.append(probe_tag)

        for image in images:
            saved = scratch / "image.tar"
            _run(["docker", "save", "-o", str(saved), image], cwd=repo_root, timeout=SAVE_TIMEOUT_SECONDS)
            hits = scan_saved_images(saved, canary)
            if image == probe_tag and PROBE_REQUIRED_PATH not in _saved_paths(saved):
                leaks.append(f"{image}: bd_shared/config.toml is missing from the build context")
            saved.unlink()
            leaks.extend(f"{image}: {path}" for path in hits)
            print(f"scanned {image}: {len(hits)} canary hit(s)", flush=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"check could not complete: {error}", file=sys.stderr)
        return 2
    finally:
        for tag in built:
            subprocess.run(["docker", "rmi", tag], capture_output=True, check=False, timeout=GIT_TIMEOUT_SECONDS)
        shutil.rmtree(scratch, ignore_errors=True)

    if leaks:
        print("build context leak:", file=sys.stderr)
        for leak in leaks:
            print(f"  {leak}", file=sys.stderr)
        return 1
    print("build context clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
