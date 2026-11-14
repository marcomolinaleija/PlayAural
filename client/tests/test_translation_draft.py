"""Draft timers never send text from a closed or replacement native input."""

from types import SimpleNamespace
from unittest.mock import Mock

from ui.translation_draft import TranslationDraft


def window():
    return SimpleNamespace(connected=True, current_mode='edit', current_edit_multiline=True,
                           edit_input=Mock(), edit_input_multiline=Mock(), edit_label=Mock(),
                           network=SimpleNamespace(send_packet=Mock()), _layout_main_panel=Mock())


def test_current_native_draft_is_sent_and_preview_preserves_keyboard_focus(monkeypatch):
    native = window()
    native.edit_input_multiline.GetValue.return_value = 'Bonjour'
    draft = TranslationDraft(native)
    draft.open({'input_id': 'translation_text_input', 'translation_draft': {'token': 'one', 'original': 'Hola'}})
    callbacks = []
    monkeypatch.setattr('ui.translation_draft.wx.CallLater', lambda _ms, callback, *args: callbacks.append((callback, args)) or Mock())
    draft.change(Mock())
    callback, args = callbacks.pop()
    callback(*args)
    packet = native.network.send_packet.call_args.args[0]
    assert packet['text'] == 'Bonjour' and packet['token'] == 'one' and packet['sequence'] == 1
    draft.receive({'input_id': 'translation_text_input', 'token': 'one', 'sequence': 1, 'preview': 'Bonjour, Alex.'})
    assert 'Bonjour, Alex.' in native.edit_label.SetLabel.call_args.args[0]
    native.edit_input_multiline.SetFocus.assert_not_called()


def test_retired_callbacks_and_packets_do_not_affect_another_input():
    native = window()
    draft = TranslationDraft(native)
    draft.open({'input_id': 'translation_text_input', 'translation_draft': {'token': 'old'}})
    retired = draft.context
    draft.open({'input_id': 'translation_text_input', 'translation_draft': {'token': 'new'}})
    draft.flush(retired, 'Late')
    native.network.send_packet.assert_not_called()
    native.edit_label.SetLabel.reset_mock()
    draft.receive({'input_id': 'translation_text_input', 'token': 'old', 'sequence': 1, 'preview': 'Late'})
    native.edit_label.SetLabel.assert_not_called()
    draft.close()
    draft.flush(retired, 'Closed')
    native.network.send_packet.assert_not_called()


def test_regular_inputs_do_not_enable_autosave():
    native = window()
    draft = TranslationDraft(native)
    draft.open({'input_id': 'ordinary', 'default_value': 'Private'})
    draft.change(Mock())
    native.network.send_packet.assert_not_called()
