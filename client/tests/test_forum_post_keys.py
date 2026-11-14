"""Route post reading/context chords through the actual desktop handler."""

from types import SimpleNamespace

import pytest
import wx

from ui.main_window import MainWindow


def setup_key(code, *, shift=False, control=False, alt=False, meta=False, surface='forum_thread', item='post:7'):
    sent = []
    window = SimpleNamespace(connected=True, current_menu_id=surface, current_menu_item_ids=[item],
                             menu_list=SimpleNamespace(GetSelection=lambda:0),
                             network=SimpleNamespace(send_packet=sent.append))
    event = SimpleNamespace(GetKeyCode=lambda:code, ShiftDown=lambda:shift, ControlDown=lambda:control,
                            AltDown=lambda:alt, MetaDown=lambda:meta)
    return window, event, sent


@pytest.mark.parametrize('code,shift,key', [(wx.WXK_RIGHT,False,'right'), (wx.WXK_RETURN,False,'enter'),
    (wx.WXK_NUMPAD_ENTER,False,'enter'), (wx.WXK_RETURN,True,'enter'), (wx.WXK_F10,True,'f10'),
    (wx.WXK_MENU,False,'applications'), (wx.WXK_WINDOWS_MENU,False,'applications')])
def test_post_commands_keep_exact_focused_row_and_modifiers(code, shift, key):
    window, event, sent = setup_key(code, shift=shift)
    assert MainWindow._handle_forum_post_key(window, event)
    assert sent == [{'type':'keybind','key':key,'shift':shift,'control':False,'alt':False,'meta':False,
                     'menu_id':'forum_thread','menu_index':1,'menu_item_id':'post:7'}]


@pytest.mark.parametrize('changes', [{'surface':'turn_menu'}, {'item':'thread_poll'}, {'item':'reply'},
    {'control':True}, {'alt':True}, {'meta':True}, {'shift':True}])
def test_unrelated_rows_game_arrows_and_modified_arrows_keep_their_own_behavior(changes):
    window, event, sent = setup_key(wx.WXK_RIGHT, **changes)
    assert not MainWindow._handle_forum_post_key(window, event)
    assert not sent


@pytest.mark.parametrize('muted,unfocused', [(False,False), (True,False), (False,True)])
def test_full_manual_reading_interrupts_speech_without_storing_body_or_ignoring_mutes(muted, unfocused):
    body = 'Primera línea\n' + 'x' * 63986
    history_calls, spoken = [], []
    window = SimpleNamespace(_should_silence_unfocused=lambda category:unfocused,
        add_history=lambda *args, **kwargs:history_calls.append((args, kwargs)),
        buffer_system=SimpleNamespace(is_effectively_muted=lambda name:muted),
        speaker=SimpleNamespace(speak=lambda text, **kwargs:spoken.append((text, kwargs))))
    MainWindow.on_server_speak(window, {'text':body,'buffer':'misc','history':False,'interrupt':True})
    assert history_calls[0][0][0] == body
    assert history_calls[0][1]['store_in_history'] is False and history_calls[0][1]['speak_aloud'] is False
    assert spoken == ([(body, {'interrupt':True})] if not muted and not unfocused else [])
