import ast
from pathlib import Path
from types import SimpleNamespace


def _source() -> str:
    source_path = Path(__file__).resolve().parents[1] / "ui" / "main_window.py"
    return source_path.read_text(encoding="utf-8")


def test_modified_arrow_keys_are_routed_as_game_keybinds() -> None:
    source = _source()

    assert (
        "modified_arrow = event.ControlDown() or event.ShiftDown() or event.AltDown()"
        in source
    )
    for key in ("UP", "DOWN", "LEFT", "RIGHT"):
        block_start = source.index(f"key_code == wx.WXK_{key}")
        block = source[block_start : block_start + 250]
        assert "or modified_arrow" in block


def test_ctrl_backspace_is_not_normalized_to_escape() -> None:
    source = _source()

    ctrl_backspace = source.index("elif key_code == wx.WXK_BACK and event.ControlDown()")
    escape_or_back = source.index("elif key_code == wx.WXK_ESCAPE or key_code == wx.WXK_BACK")

    assert ctrl_backspace < escape_or_back
    assert 'key_name = "backspace"' in source[ctrl_backspace:escape_or_back]


def test_table_shortcuts_dispatch_from_the_real_desktop_key_handler():
    module = ast.parse(_source())
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    handler = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "on_char_hook")
    wx_names = {n.attr for n in ast.walk(handler) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "wx"}
    wx = SimpleNamespace(**{name: 1000 + i for i, name in enumerate(sorted(wx_names))})
    wx.MOD_CONTROL, wx.MOD_ALT, wx.MOD_SHIFT = 1, 2, 4
    wx.TextCtrl = type("TextCtrl", (), {})
    menu = SimpleNamespace(GetSelection=lambda: 0, GetCount=lambda: 1)
    wx.Window = SimpleNamespace(FindFocus=lambda: menu)
    scope = {"wx": wx, "MENU_DESCRIPTION_KEY_CODE": -99}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "<desktop-key-handler>", "exec"), scope)
    sent = []
    window = SimpleNamespace(
        menu_list=menu, current_mode="list", connected=True, multiletter_enabled=False,
        current_menu_id="turn_menu", current_menu_item_ids=["whos_at_table"],
        current_menu_item_read_only=[False], network=SimpleNamespace(send_packet=sent.append),
    )
    for key, control, alt in (("W", False, False), ("W", True, False), ("U", True, False), ("W", False, True)):
        event = SimpleNamespace(
            GetKeyCode=lambda: ord(key),
            GetModifiers=lambda: (wx.MOD_CONTROL if control else 0) | (wx.MOD_ALT if alt else 0),
            ControlDown=lambda: control, AltDown=lambda: alt, ShiftDown=lambda: False,
            Skip=lambda: None,
        )
        scope["on_char_hook"](window, event)
        packet = sent[-1]
        assert packet["key"] == key.lower()
        assert packet["control"] is control and packet["alt"] is alt
        assert packet["menu_id"] == "turn_menu"
    assert len(sent) == 4
    # Typing W in a text field remains ordinary text entry.
    window.current_mode = "edit"
    scope["on_char_hook"](window, event)
    assert len(sent) == 4
