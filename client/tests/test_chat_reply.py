import sys
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from chat_reply import (
    REPLY_QUOTE_LIMIT,
    chat_alert_sound,
    metadata_from_chat_packet,
    metadata_from_speak_packet,
    outgoing_chat_packet,
    reply_format_key,
)


def test_chat_and_private_messages_keep_a_reply_target():
    table = metadata_from_chat_packet(
        {"convo": "local", "sender": "Rayo", "message": "hola"}
    )
    assert table == {
        "kind": "chat",
        "convo": "table",
        "sender": "Rayo",
        "message": "hola",
    }
    assert metadata_from_chat_packet(
        {"convo": "announcement", "sender": "Sistema", "message": "hola"}
    ) is None
    private = metadata_from_speak_packet(
        {
            "key": "pm-received",
            "params": {"username": "Rayo", "message": "hola"},
        }
    )
    assert private["convo"] == "private"
    assert private["sender"] == "Rayo"


def test_outgoing_reply_stays_on_the_source_channel_and_clips_the_quote():
    quote = "á" * (REPLY_QUOTE_LIMIT + 50)
    table = outgoing_chat_packet("yo también", {
        "convo": "table",
        "sender": "Rayo",
        "message": quote,
    })
    assert table["convo"] == "table"
    assert table["message"] == "yo también"
    assert table["reply_to"]["sender"] == "Rayo"
    assert table["reply_to"]["message"] == "á" * REPLY_QUOTE_LIMIT

    private = outgoing_chat_packet("voy", {
        "convo": "private",
        "sender": "Nguyễn Văn An",
        "message": "hola",
    })
    assert private == {
        "type": "chat",
        "convo": "local",
        "message": "@Nguyễn Văn An voy",
        "reply_to": {"sender": "Nguyễn Văn An", "message": "hola"},
    }
    assert outgoing_chat_packet("hola", None) == {
        "type": "chat",
        "convo": "local",
        "message": "hola",
    }


def test_table_reply_uses_the_table_sound_and_reply_line():
    for convo in ("local", "table", "game"):
        assert chat_alert_sound(convo) == "chatlocal.ogg"
        assert reply_format_key(convo) == "chat-local-reply"
    assert chat_alert_sound("global") == "chat.ogg"
    assert reply_format_key("global") == "chat-global-reply"
    assert chat_alert_sound("private") == "pm.ogg"
