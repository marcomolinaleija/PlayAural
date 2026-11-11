import sys
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from unfocused_audio import (
    audio_category,
    chat_category,
    migrate_client_audio_options,
    should_silence_unfocused,
    speak_category,
)


def test_legacy_switch_silences_every_category_until_categories_exist():
    audio = {"limit_unfocused_audio_and_tts": True}
    migrate_client_audio_options(audio, had_explicit_categories=False)
    assert audio["limit_unfocused_audio_and_tts"] is False
    assert audio["unfocused_silence"] == {
        "game": True,
        "table": True,
        "invitations": True,
        "system": True,
        "private": True,
    }

    selective = {
        "limit_unfocused_audio_and_tts": True,
        "unfocused_silence": {"game": False, "private": True},
    }
    migrate_client_audio_options(selective, had_explicit_categories=True)
    assert selective["unfocused_silence"]["game"] is False
    assert selective["unfocused_silence"]["private"] is True
    assert selective["unfocused_silence"]["table"] is False


def test_categories_only_silence_while_the_window_is_unfocused():
    audio = {"unfocused_silence": {"private": True, "game": False}}
    assert should_silence_unfocused(audio, "private", window_active=False) is True
    assert should_silence_unfocused(audio, "private", window_active=True) is False
    assert should_silence_unfocused(audio, "game", window_active=False) is False
    assert should_silence_unfocused(audio, "", window_active=False) is False


def test_speech_chat_and_audio_use_separate_categories():
    assert speak_category("game", "game-score") == "game"
    assert speak_category("system", "table-invite-received") == "invitations"
    assert speak_category("system", "admin-broadcast") == "system"
    assert speak_category("private") == "private"

    assert chat_category("local") == "table"
    assert chat_category("private") == "private"
    assert chat_category("announcement") == "system"
    assert chat_category("global") == ""

    assert audio_category({"command": "play", "asset": "game_pig/roll.ogg"}) == "game"
    assert audio_category({"command": "play", "asset": "typing_return.ogg"}) == "game"
    assert audio_category({"command": "stop", "asset": "turn.ogg"}) == ""
    assert audio_category({"command": "play", "asset": "table_invite.ogg"}) == "invitations"
    assert audio_category({"command": "play", "asset": "pm.ogg"}) == "private"
    assert audio_category({"command": "play", "asset": "chatlocal.ogg"}) == "table"
    assert audio_category({"command": "play", "asset": "chat.ogg"}) == ""
    assert audio_category({"command": "play", "family": "notify"}) == "system"
    assert audio_category({"command": "play", "asset": "server_alert_warning.ogg"}) == "system"


def test_your_turn_alert_stays_audible_when_the_game_is_silenced():
    audio = {"unfocused_silence": {"game": True}}
    turn_speech = (
        "game-turn-start-you",
        "snakes-turn-start-you",
        "battle-turn-start-you",
    )
    for key in turn_speech:
        assert speak_category("game", key) == ""
        assert should_silence_unfocused(audio, speak_category("game", key), window_active=False) is False
    assert speak_category("game", "game-turn-start-player") == "game"
    assert should_silence_unfocused(
        audio, speak_category("game", "game-turn-start-player"), window_active=False
    ) is True

    for asset in ("turn.ogg", "game_pig/turn.ogg", "game_squares/begin turn.ogg"):
        category = audio_category({"command": "play", "asset": asset, "buffer": "game"})
        assert category == ""
        assert should_silence_unfocused(audio, category, window_active=False) is False
    assert should_silence_unfocused(
        audio,
        audio_category({"command": "play", "asset": "game_pig/roll.ogg", "buffer": "game"}),
        window_active=False,
    ) is True
