"""Layer scanner cases for the build-context canary check.

The scanner reads a `docker save` tarball, so these cases build small tarballs in a temporary
directory and need no Docker daemon.
"""

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

# Runnable both as `poetry run python deploy/test_check_build_context.py` and through the root
# Makefile, so the repository root is put on the path the same way bd_shared tests do it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deploy import check_build_context  # noqa: E402

NEEDLE = "CANARY-0123456789abcdef"


def _add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def _layer(files: dict[str, bytes], *entries: tarfile.TarInfo) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as layer:
        for name, data in files.items():
            _add(layer, name, data)
        for entry in entries:
            layer.addfile(entry)
    return buffer.getvalue()


def _entry(name: str, kind: bytes, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info


def _saved_image(path: Path, layers: list[bytes]) -> None:
    """Write a docker-save shaped tarball: a manifest plus one nested layer tar per layer."""
    with tarfile.open(path, "w") as outer:
        manifest = [{"Config": "config.json", "Layers": [f"layer{i}/layer.tar" for i in range(len(layers))]}]
        _add(outer, "manifest.json", json.dumps(manifest).encode())
        _add(outer, "config.json", b"{}")
        for i, layer in enumerate(layers):
            _add(outer, f"layer{i}/layer.tar", layer)


class ScanSavedImagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tar_path = Path(tmp.name) / "image.tar"

    def test_a_needle_in_a_nested_layer_tar_is_reported(self):
        """Given a canary inside a layer, When scanned, Then that member path is returned."""
        _saved_image(
            self.tar_path,
            [
                _layer({"app/ok.txt": b"fine"}),
                _layer({"app/config.local.toml": f"# {NEEDLE}\n".encode(), "app/other.txt": b"fine"}),
            ],
        )

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), ["app/config.local.toml"])

    def test_a_file_deleted_by_a_later_layer_is_still_reported(self):
        """Given a canary file removed by a whiteout layer, When scanned, Then it is still found."""
        _saved_image(
            self.tar_path,
            [
                _layer({"app/secret.env": f"# {NEEDLE}\n".encode()}),
                _layer({"app/.wh.secret.env": b""}),
            ],
        )

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), ["app/secret.env"])

    def test_a_clean_tarball_returns_nothing(self):
        """Given layers without the canary, When scanned, Then the result is empty."""
        _saved_image(self.tar_path, [_layer({"app/a.txt": b"one"}), _layer({"app/b.txt": b"two"})])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), [])

    def test_a_needle_in_a_directory_name_is_reported(self):
        """Given a canary-named directory, When scanned, Then the directory path is returned."""
        _saved_image(self.tar_path, [_layer({}, _entry(f"app/{NEEDLE}-dir", tarfile.DIRTYPE))])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), [f"app/{NEEDLE}-dir"])

    def test_a_needle_in_a_symlink_name_is_reported(self):
        """Given a canary-named symlink, When scanned, Then the symlink path is returned."""
        _saved_image(self.tar_path, [_layer({}, _entry(f"app/{NEEDLE}-link", tarfile.SYMTYPE, "target"))])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), [f"app/{NEEDLE}-link"])

    def test_a_needle_in_a_symlink_target_is_reported(self):
        """Given a symlink pointing at a canary path, When scanned, Then the symlink path is returned."""
        _saved_image(self.tar_path, [_layer({}, _entry("app/link", tarfile.SYMTYPE, f"/srv/{NEEDLE}"))])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), ["app/link"])

    def test_a_needle_in_a_hardlink_name_is_reported(self):
        """Given a canary-named hardlink, When scanned, Then the hardlink path is returned."""
        layer = _layer({"app/real": b"fine"}, _entry(f"app/{NEEDLE}-hard", tarfile.LNKTYPE, "app/real"))
        _saved_image(self.tar_path, [layer])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), [f"app/{NEEDLE}-hard"])

    def test_a_needle_in_a_hardlink_target_is_reported(self):
        """Given a hardlink to a canary path, When scanned, Then the hardlink path is returned."""
        layer = _layer({}, _entry("app/hard", tarfile.LNKTYPE, f"app/{NEEDLE}-real"))
        _saved_image(self.tar_path, [layer])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), ["app/hard"])

    def test_a_needle_in_a_whiteout_name_is_reported(self):
        """Given a whiteout of a canary-named path, When scanned, Then the whiteout path is returned."""
        whiteout = _entry(f"app/.wh.{NEEDLE}-gone", tarfile.REGTYPE)
        _saved_image(self.tar_path, [_layer({}, whiteout)])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), [f"app/.wh.{NEEDLE}-gone"])

    def test_a_needle_straddling_a_read_chunk_is_reported(self):
        """Given a canary split across two read chunks, When scanned, Then it is still found."""
        chunk = check_build_context.CHUNK_SIZE
        padding = b"x" * (chunk - len(NEEDLE) // 2)
        _saved_image(self.tar_path, [_layer({"big.bin": padding + NEEDLE.encode() + b"y" * chunk})])

        self.assertEqual(check_build_context.scan_saved_images(self.tar_path, NEEDLE), ["big.bin"])


if __name__ == "__main__":
    unittest.main()
