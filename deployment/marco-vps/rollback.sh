#!/usr/bin/env bash
set -euo pipefail
umask 077
root=/home/marco/apps/playaural
backup=$(realpath "${1:?Supply a backup directory}")
case "$backup" in "$root"/backups/*) ;; *) exit 64 ;; esac
test -f "$backup/previous.env" && test -f "$backup/releases.json" && test -f "$backup/PlayAural.db"
python3 - "$backup/PlayAural.db" <<'PY'
import sqlite3, sys
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
PY
current_code=$(sed -n 's/^CODE_ROOT=//p' "$root/current.env")
docker compose --env-file "$root/current.env" -f "$current_code/deployment/marco-vps/compose.yaml" stop web game
cp "$backup/PlayAural.db" "$root/data/PlayAural.db"
# These are SQLite sidecars of the stopped deployment, never directories.
rm -f -- "$root/data/PlayAural.db-wal" "$root/data/PlayAural.db-shm" "$root/data/PlayAural.db-journal"
cp "$backup/releases.json" "$root/config/releases.json"
cp "$backup/previous.env" "$root/current.env"
previous_code=$(sed -n 's/^CODE_ROOT=//p' "$root/current.env")
docker compose --env-file "$root/current.env" -f "$previous_code/deployment/marco-vps/compose.yaml" up -d --no-build
ln -sfn "$previous_code" "$root/current"
echo "Restored previous images, release manifest and matching database from $backup"
