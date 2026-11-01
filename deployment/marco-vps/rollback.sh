#!/usr/bin/env bash
set -euo pipefail
umask 077
root=/home/marco/apps/playaural
unset PLAYAURAL_HOME CODE_ROOT RELEASE_ID
backup=$(realpath "${1:?Supply a backup directory}")
case "$backup" in "$root"/backups/*) ;; *) exit 64 ;; esac
test -f "$backup/previous.env" && test -f "$backup/releases.json" && test -f "$backup/PlayAural.db"
test ! -e "$backup/INCOMPLETE"
python3 - "$backup/PlayAural.db" "$(dirname "$0")" <<'PY'
import sqlite3, sys
sys.path.insert(0, sys.argv[2])
from backup_database import register_sqlite_functions
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as db:
    register_sqlite_functions(db)
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
PY
current_code=$(sed -n 's/^CODE_ROOT=//p' "$root/current.env")
docker compose --env-file "$root/current.env" -f "$current_code/deployment/marco-vps/compose.yaml" stop web game
cp "$backup/PlayAural.db" "$root/data/PlayAural.db"
# These are SQLite sidecars of the stopped deployment, never directories.
rm -f -- "$root/data/PlayAural.db-wal" "$root/data/PlayAural.db-shm" "$root/data/PlayAural.db-journal"
cp "$backup/releases.json" "$root/config/releases.json"
cp "$backup/previous.env" "$root/current.env"
previous_code=$(sed -n 's/^CODE_ROOT=//p' "$root/current.env")
python3 "$(dirname "$0")/storage_preflight.py"
docker compose --env-file "$root/current.env" -f "$previous_code/deployment/marco-vps/compose.yaml" up -d --no-build
ln -sfn "$previous_code" "$root/current"
echo "Restored previous images, release manifest and matching database from $backup"
