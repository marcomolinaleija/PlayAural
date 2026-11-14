"""Debounced draft previews without altering any keyboard bindings."""

import wx


class TranslationDraft:
    def __init__(self, window):
        self.window = window
        self.context = None
        self.timer = None

    def close(self):
        if self.timer is not None:
            self.timer.Stop()
        self.timer = None
        self.context = None

    def open(self, packet):
        self.close()
        draft = packet.get('translation_draft')
        if not isinstance(draft, dict) or not draft.get('token') or packet.get('read_only'):
            return
        self.context = {'token': draft['token'], 'input_id': packet['input_id'], 'sequence': 0,
                        'value': packet.get('default_value', ''), 'original': draft.get('original', ''),
                        'prompt': packet.get('prompt', '')}
        self.window.edit_label.SetLabel(self.context['prompt'] + '\n' + self.context['original'])

    def change(self, event):
        event.Skip()
        if not self.context or self.window.current_mode != 'edit':
            return
        if self.timer is not None:
            self.timer.Stop()
        context = self.context
        control = self.window.edit_input_multiline if self.window.current_edit_multiline else self.window.edit_input
        value = control.GetValue()
        self.timer = wx.CallLater(600, self.flush, context, value)

    def flush(self, context, value):
        self.timer = None
        if self.context is not context or value == context['value'] or not self.window.connected:
            return
        context['value'] = value
        context['sequence'] += 1
        self.window.network.send_packet({'type': 'translation_draft', 'input_id': context['input_id'],
                                         'token': context['token'], 'sequence': context['sequence'], 'text': value})

    def receive(self, packet):
        context = self.context
        if (not context or packet.get('token') != context['token'] or packet.get('input_id') != context['input_id']
                or packet.get('sequence') != context['sequence']):
            return
        preview = packet.get('error') or packet.get('preview', '')
        # The input's accessible name stays unchanged; do not repeatedly speak
        # previews or move the caret while the author is writing.
        self.window.edit_label.SetLabel(context['prompt'] + '\n' + context['original'] + '\n' + preview)
        self.window._layout_main_panel()
