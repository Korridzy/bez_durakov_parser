"""Local release API fixture, adapted from the todo 10 rehearsal. No network."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

root = Path(os.environ["SHIM_STATE"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
release = json.loads((root / "release.json").read_text())
if args[0] == "api":
    url = next(arg for arg in args if arg.startswith("http"))
    assert urlsplit(url).hostname == "127.0.0.1"
    path = urlsplit(url).path
    if "/releases/tags/" in path:
        print(json.dumps(release))
    elif "/releases/assets/" in path:
        sys.stdout.buffer.write((root / "asset.json").read_bytes())
    elif "/actions/workflows/" in path:
        print((root / "runs.json").read_text())
    elif "/attempts/" in path:
        print("[" + (root / "jobs.json").read_text() + "]")
    else:
        sys.exit("unexpected local API path")
elif args[:2] == ["release", "upload"]:
    assert "--clobber" not in args and not release["assets"]
    (root / "asset.json").write_bytes(Path(args[3]).read_bytes())
    release["assets"] = [{"id": 42, "name": "release-metadata.json",
                          "browser_download_url": (root / "asset.json").as_uri()}]
    (root / "release.json").write_text(json.dumps(release))
elif args[:2] == ["release", "edit"]:
    release["body"] = Path(args[args.index("--notes-file") + 1]).read_text()
    (root / "release.json").write_text(json.dumps(release))
else:
    sys.exit("unexpected local gh command")
