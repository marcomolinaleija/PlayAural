"""Create a consistent, private SQLite backup without interrupting players."""
import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path("/home/marco/apps/playaural"))
args = parser.parse_args()
root = args.root.resolve()
source_path = root / "data/PlayAural.db"
if not source_path.is_file():
    raise SystemExit("Production database is missing; refusing to create an empty backup")
os.umask(0o077)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
destination = root / "backups" / ("daily-" + stamp)
destination.mkdir(mode=0o700)
try:
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=30) as source:
        with sqlite3.connect(destination / "PlayAural.db") as backup:
            source.backup(backup)
            assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    for path, name in ((root / "current.env", "previous.env"),
                       (root / "config/releases.json", "releases.json")):
        shutil.copy2(path, destination / name)
        (destination / name).chmod(0o600)
    (destination / "PlayAural.db").chmod(0o600)
    (destination / "metadata.json").write_text(json.dumps({
        "created_utc": stamp,
        "scope": "SQLite durable data; active in-memory matches are checkpointed separately by the server",
        "verified": "PRAGMA quick_check=ok",
    }, indent=2))
except BaseException:
    (destination / "INCOMPLETE").write_text("Backup did not finish; do not restore this directory.")
    raise
print("Verified private SQLite backup: " + str(destination))
