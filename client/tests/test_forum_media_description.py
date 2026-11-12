"""Descriptions are real focusable read-only native text, including images."""

import wx

from ui.forum_media_dialog import ForumMediaDialog


def test_native_description_is_visible_copyable_multiline_and_preserves_full_text():
    app = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None)
    try:
        frame.labels = {'description':'Descripción'}
        frame.root = wx.BoxSizer(wx.VERTICAL)
        text = 'Primera línea\n' + 'á' * 986
        description = ForumMediaDialog.add_description(frame, text)
        assert description.GetValue() == text
        assert description.GetName() == 'Descripción'
        assert not description.IsEditable()
        assert description.IsMultiLine()
        assert description.GetSelection() == (0, 0)
        assert frame.root.GetItemCount() == 1
        assert ForumMediaDialog.add_description(frame, '') is None
        assert frame.root.GetItemCount() == 1
    finally:
        frame.Destroy()
        app.ProcessPendingEvents()
