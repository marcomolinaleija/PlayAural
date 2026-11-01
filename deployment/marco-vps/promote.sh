#!/usr/bin/env bash
set -euo pipefail
umask 077
root=/home/marco/apps/playaural
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
commit=${1:?Usage: promote.sh FULL_COMMIT MANIFEST_JSON}
manifest=$(realpath "${2:?Supply the approved release manifest}")
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || exit 64
exec 9>"$root/promotion.lock"
flock -n 9 || { echo 'Another promotion is running' >&2; exit 1; }
git -C "$root/source" fetch origin
git -C "$root/source" cat-file -e "$commit^{commit}"
git -C "$root/source" merge-base --is-ancestor "$commit" origin/main
python3 - "$manifest" "$commit" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
assert manifest['source_commit'] == sys.argv[2], 'Manifest must describe this exact source commit'
PY
target="$root/releases/$commit"
test ! -L "$target"
if ! test -d "$target"; then
  mkdir "$target"
  git -C "$root/source" archive "$commit" | tar --same-permissions -x -C "$target"
fi
python3 "$script_dir/prepare_public_web_source.py" "$target"
export PLAYAURAL_HOME="$root" CODE_ROOT="$target" RELEASE_ID="$commit"
compose=(docker compose -f "$target/deployment/marco-vps/compose.yaml")
"${compose[@]}" build
docker run --rm -v "$manifest:/approved.json:ro" -e PLAYAURAL_RELEASE_MANIFEST=/approved.json \
  "playaural-game:$commit" /app/server/.venv/bin/python -c 'from server.core.server import VERSION; print(VERSION)'
# Test the complete source tree, not only the files copied into the runtime image.
docker run --rm --user 1000:1000 -v "$target:/workspace" -w /workspace -e UV_CACHE_DIR=/tmp/uv \
  ghcr.io/astral-sh/uv@sha256:08477888ac23d6cfbeb8c7dc6fc70cf297fd38b7bf35522be33ce832750ca242 \
  uv run --project server --locked --extra dev --python 3.13 python -m pytest server/tests -q -n 4
if test "${PLAYAURAL_AUTOMATED_DEPLOYMENT:-0}" = 1; then
  python3 "$root/ops/autoupdate/deployment_gate.py" "$root"
fi
backup="$root/backups/$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:8}"
mkdir "$backup"
cp "$root/current.env" "$backup/previous.env"
cp "$root/config/releases.json" "$backup/releases.json"
old_code=$(sed -n 's/^CODE_ROOT=//p' "$root/current.env")
backup_ready=0
recover() {
  if test "$backup_ready" = 1; then
    "$target/deployment/marco-vps/rollback.sh" "$backup"
  else
    env -u PLAYAURAL_HOME -u CODE_ROOT -u RELEASE_ID docker compose --env-file "$root/current.env" -f "$old_code/deployment/marco-vps/compose.yaml" up -d --no-build
  fi
}
trap recover ERR
env -u PLAYAURAL_HOME -u CODE_ROOT -u RELEASE_ID docker compose --env-file "$root/current.env" -f "$old_code/deployment/marco-vps/compose.yaml" stop web game
python3 "$target/deployment/marco-vps/storage_preflight.py"
python3 - "$root/data/PlayAural.db" "$backup/PlayAural.db" "$target/deployment/marco-vps" <<'PY'
import sys
sys.path.insert(0, sys.argv[3])
from backup_database import backup_sqlite
backup_sqlite(sys.argv[1], sys.argv[2])
PY
backup_ready=1
cp "$manifest" "$root/config/releases.json"
printf 'PLAYAURAL_HOME=%s\nCODE_ROOT=%s\nRELEASE_ID=%s\n' "$root" "$target" "$commit" > "$root/current.env"
"${compose[@]}" up -d --no-build
healthy=0
for attempt in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:3048/health >/dev/null && \
     docker exec playaural-game-1 /app/server/.venv/bin/python -c "import socket; socket.create_connection(('127.0.0.1',8000),2).close()"; then
    healthy=1; break
  fi
  sleep 1
done
test "$healthy" = 1
docker exec -i playaural-game-1 /app/server/.venv/bin/python - < "$script_dir/auth_release_probe.py"
ln -sfn "$target" "$root/current"
cp "$backup/previous.env" "$root/previous.env"
printf '%s\n' "$backup" > "$root/last-backup"
trap - ERR
echo "Promoted $commit; verified database backup: $backup"
