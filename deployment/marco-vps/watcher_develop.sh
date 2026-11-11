#!/usr/bin/env bash
# Watcher script for PlayAural develop branch on VPS
# Checks origin/develop, builds images, warns connected players (60s countdown), and restarts.

set -euo pipefail

# Ensure single instance execution via lock file
LOCKFILE="/tmp/playaural-watcher.lock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    exit 0
fi

REPO_DIR="/opt/playaural/source"
COMPOSE_FILE="$REPO_DIR/deployment/marco-vps/compose.yaml"
ENV_FILE="/opt/playaural/.env"
DATA_DIR="/opt/playaural/data"
BRANCH="develop"

cd "$REPO_DIR" || exit 1

# Fetch latest refs silently
git fetch origin "$BRANCH" --quiet || exit 0

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$BRANCH")

# If no changes, exit quietly
if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    exit 0
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "Nuevos cambios detectados en origin/$BRANCH: $LOCAL_SHA -> $REMOTE_SHA"

# Pull changes
log "Actualizando código local con git pull..."
git pull origin "$BRANCH"

# Fix permissions if pulled by root
chown -R codex:docker "$REPO_DIR" 2>/dev/null || true

# Generate new release ID
NEW_RELEASE="develop-$(date +%Y%m%d-%H%M%S)"
log "Compilando imágenes Docker para RELEASE_ID=$NEW_RELEASE..."

if ! RELEASE_ID="$NEW_RELEASE" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build game web; then
    log "ERROR: Falló la compilación de imágenes Docker. Abortando actualización para mantener producción estable."
    exit 1
fi

log "Compilación exitosa. Notificando a los jugadores (aviso de 60 segundos)..."

# Write power command for native countdown, audio earcons, and table preservation
cat << 'EOF' > "$DATA_DIR/power-command.json"
{
  "action": "reboot",
  "delay_seconds": 60,
  "requested_by": "autoupdate",
  "reason_id": "update"
}
EOF
chown 1000:1000 "$DATA_DIR/power-command.json" 2>/dev/null || true

# Also trigger signal in case the container is listening
docker kill --signal=SIGUSR1 playaural-game-1 2>/dev/null || true

# Update RELEASE_ID in .env while countdown runs
sed -i "s/^RELEASE_ID=.*/RELEASE_ID=$NEW_RELEASE/" "$ENV_FILE"

log "Cuenta regresiva en curso (60s). Esperando 62 segundos para finalización limpia de partidas..."
sleep 62

log "Reiniciando stack con systemctl restart playaural..."
systemctl restart playaural

log "Despliegue automático a $NEW_RELEASE completado con éxito."
