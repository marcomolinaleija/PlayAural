"""Run a disposable loopback-only forum demo without touching real accounts.

From the repository root:
    uv run --project server --extra dev python -m scripts.run_forum_demo
"""

import asyncio
import json
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server.auth.auth import AuthManager
from server.core.server import Server


ROOT = Path(__file__).resolve().parents[1]
GAME_PORT = 18765
WEB_PORT = 18766
MEDIA_PORT = 18767
DEMO_PASSWORD = "ForumDemo123!"


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'web_client'), **kwargs)

    def translate_path(self, path):
        # Keep the public URL while limiting static files to the web client.
        return super().translate_path(path.removeprefix('/web_client'))

    def end_headers(self):
        # Local UI review must use the current source, including after reload.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        if not self.path.startswith('/web_client/'):
            self.send_error(404)
            return
        if self.path.split("?", 1)[0] == "/web_client/config.js":
            payload = "window.PLAYAURAL_WEB_CONFIG = " + json.dumps({"serverUrl": f"ws://127.0.0.1:{GAME_PORT}"}) + ";"
            body = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, format, *args):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="playaural-forum-demo-") as directory:
        server = Server(host="127.0.0.1", port=GAME_PORT, db_path=str(Path(directory) / "demo.db"),
                        forum_media_url=f'http://127.0.0.1:{MEDIA_PORT}', forum_media_port=MEDIA_PORT,
                        forum_media_dir=Path(directory) / 'media', forum_media_origins=(f'http://127.0.0.1:{WEB_PORT}',))
        await server.start()
        http = None
        try:
            auth = AuthManager(server.db)
            for username in ("ForumModerator", "ForumDesktop", "ForumWeb", "ForumMobile"):
                result = auth.register(username, DEMO_PASSWORD, locale="es", email=f"{username}@example.test")
                if result != "ok":
                    raise RuntimeError(f"Could not prepare demo account: {result}")
                server.db.approve_user(username)
                # Keep the bootstrap developer as the reviewer: the central
                # last-developer guard must also hold in the disposable demo.
                if username != 'ForumModerator':
                    server.db.update_user_trust_level(username, 1)
            author = server.db.get_user("ForumDesktop").uuid
            service = server.forum_manager.service
            topic, _ = service.create_topic(author, "general", "Bienvenidos a la comunidad",
                                             "Este es nuestro espacio para conversar.\nPuedes guardar un tema y continuar desde el primer mensaje sin leer.")
            service.reply(server.db.get_user("ForumMobile").uuid, topic,
                          "También podemos participar desde el móvil, usando la misma cuenta de PlayAural.")
            service.create_topic(author, "help", "¿Cómo inicio una conversación?",
                                 "Entra en una categoría y elige Iniciar una conversación. Escribe el título y el mensaje, revisa la vista previa y elige Publicar.")
            service.create_topic(author, "ideas", "Comparte tu próxima idea",
                                 "¿Qué te gustaría que construyéramos para la comunidad?")
            http = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), DemoHandler)
            threading.Thread(target=http.serve_forever, daemon=True).start()
            print(f"\nForum demo: http://127.0.0.1:{WEB_PORT}/web_client/", flush=True)
            print(f"Desktop/mobile server: ws://127.0.0.1:{GAME_PORT}", flush=True)
            print(f"Users: ForumDesktop / ForumWeb / ForumMobile / ForumModerator; password: {DEMO_PASSWORD}", flush=True)
            print("Disposable local data. Press Ctrl+C to stop. No production accounts are used.", flush=True)
            await asyncio.Event().wait()
        finally:
            if http:
                http.shutdown()
                http.server_close()
            await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
