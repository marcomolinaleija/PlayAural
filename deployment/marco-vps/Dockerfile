FROM ghcr.io/astral-sh/uv@sha256:08477888ac23d6cfbeb8c7dc6fc70cf297fd38b7bf35522be33ce832750ca242
WORKDIR /app
COPY server /app/server
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
RUN uv sync --project server --locked --extra dev --python 3.13 && chown -R 1000:1000 /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /data
CMD ["/app/server/.venv/bin/python", "-m", "server", "--host", "0.0.0.0", "--port", "8000", "--database-backup-dir", "/backups"]
