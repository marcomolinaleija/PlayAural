import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


CLIENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from localization import Localization


@pytest.mark.parametrize("locale", sorted(path.name for path in (CLIENT_DIR / "locales").iterdir() if path.is_dir()))
@pytest.mark.parametrize("convo", ("local", "global", "private", "announcement"))
def test_received_chat_retains_message_in_every_desktop_locale(locale, convo):
    """Exercise the real packet handler without requiring a wx display in CI."""
    source_path = CLIENT_DIR / "ui" / "main_window.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    window = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    handler = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == "on_receive_chat")
    namespace = {"Localization": Localization}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source_path), "exec"), namespace)
    history = []
    alerts = []
    fake_window = SimpleNamespace(
        buffer_system=SimpleNamespace(is_effectively_muted=lambda name: False),
        sound_manager=SimpleNamespace(play=alerts.append, play_family=alerts.append),
        add_history=lambda *args: history.append(args),
    )
    content = "Hola, ¿se lee? ñ العربية { $message } <texto>"
    try:
        Localization.init(locale=locale)
        namespace["on_receive_chat"](fake_window, {
            "convo": convo, "sender": "PruebaMarco", "message": content,
        })
        assert len(history) == 1
        text, buffer_name, speak_aloud = history[0]
        assert content in text
        if convo != "announcement":
            assert "PruebaMarco" in text
        assert buffer_name == ("private" if convo == "private" else "chat")
        assert speak_aloud is True
        assert len(alerts) == 1
    finally:
        Localization.init(locale="en")


def test_set_locale_reloads_client_bundle_without_restart(tmp_path):
    en_dir = tmp_path / "en"
    vi_dir = tmp_path / "vi"
    en_dir.mkdir()
    vi_dir.mkdir()
    (en_dir / "client.ftl").write_text(
        "dynamic-label = English label\nfallback-only = Fallback value\n",
        encoding="utf-8",
    )
    (vi_dir / "client.ftl").write_text(
        "dynamic-label = Nhãn tiếng Việt\n",
        encoding="utf-8",
    )

    Localization.init(locales_dir=tmp_path, locale="en")
    assert Localization.get("dynamic-label") == "English label"

    changed = Localization.set_locale("vi")

    assert changed is True
    assert Localization.current_locale() == "vi"
    assert Localization.get("dynamic-label") == "Nhãn tiếng Việt"
    assert Localization.get("fallback-only") == "Fallback value"


def test_desktop_buffer_terminology_matches_mobile_catalogs():
    project_dir = CLIENT_DIR.parent
    desktop_locales = CLIENT_DIR / "locales"
    keys = (
        "buffer-all",
        "buffer-chat",
        "buffer-private",
        "buffer-game",
        "buffer-system",
        "buffer-misc",
        "buffer-name-all",
        "buffer-name-chat",
        "buffer-name-private",
        "buffer-name-game",
        "buffer-name-system",
        "buffer-name-misc",
        "main-status-muted-suffix",
        "main-buffer-status",
        "main-buffer-info",
        "history-buffer-current",
        "history-buffer-muted-name",
        "history-buffer-muted-by-all",
        "history-buffer-muted-empty",
    )

    for locale in ("en", "pt", "vi"):
        mobile_catalog = json.loads(
            (project_dir / "mobile_client" / "locales" / locale / "client.json").read_text(
                encoding="utf-8"
            )
        )
        Localization.init(locales_dir=desktop_locales, locale=locale)
        for key in keys:
            expected = (
                mobile_catalog[key]
                .replace("{name}", "game")
                .replace("{status}", "muted")
                .replace("{count}", "3")
            )
            assert Localization.get(key, name="game", status="muted", count=3) == expected

    Localization.init(locales_dir=desktop_locales, locale="en")
