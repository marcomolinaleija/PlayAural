"""Native attachment viewer/player with bottom actions and focus restoration."""

from io import BytesIO
import math
import threading

import wx
import wx.media

from forum_media_transport import NativeMediaRelay, content_bytes
from forum_media_transport import caption_bytes
from forum_captions import captions_at, parse_captions


class ForumMediaDialog(wx.Dialog):
    def __init__(self, parent, packet, *, on_playback, on_save):
        super().__init__(parent, title=packet['attachment']['name'], size=(760, 570),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.packet, self.labels = packet, packet['labels']
        self.on_playback, self.on_save = on_playback, on_save
        self.relay = None
        self.player = None
        self.image = None
        self.closed = False
        self.zoom = 1.0
        self.caption_cues = []
        self.caption_visible = False
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.tick, self.timer)
        self.Bind(wx.EVT_CLOSE, self.finish)
        root = wx.BoxSizer(wx.VERTICAL)
        self.root = root
        self.status = wx.StaticText(self, label='')
        self.actions = wx.BoxSizer(wx.HORIZONTAL)
        attachment = packet['attachment']
        if attachment['kind'] == 'image':
            self.viewport = wx.ScrolledWindow(self)
            self.viewport.SetName(attachment['description'] or attachment['name'])
            self.viewport.SetScrollRate(12, 12)
            self.bitmap = wx.StaticBitmap(self.viewport)
            self.bitmap.SetName(attachment['description'] or attachment['name'])
            root.Add(self.viewport, 1, wx.EXPAND | wx.ALL, 8)
            self.button('zoom_in', lambda _: self.resize_image(1.25))
            self.button('zoom_out', lambda _: self.resize_image(0.8))
            threading.Thread(target=self.load_image, daemon=True).start()
        else:
            self.player = wx.media.MediaCtrl()
            backend = wx.media.MEDIABACKEND_WMP10 if wx.Platform == '__WXMSW__' else ''
            if not self.player.Create(self, style=wx.media.MC_NO_AUTORESIZE, szBackend=backend):
                self.status.SetLabel(self.labels['error'])
                self.player = None
            else:
                self.player.SetName(attachment['name'])
                root.Add(self.player, 1 if attachment['kind'] == 'video' else 0, wx.EXPAND | wx.ALL, 8)
                self.player.Bind(wx.media.EVT_MEDIA_LOADED, self.loaded)
                self.player.Bind(wx.media.EVT_MEDIA_PLAY, lambda _: self.play_state(True))
                self.player.Bind(wx.media.EVT_MEDIA_PAUSE, lambda _: self.play_state(False))
                self.player.Bind(wx.media.EVT_MEDIA_FINISHED, lambda _: self.play_state(False))
                self.play_button = self.button('play', self.toggle)
                self.play_button.Disable()
                self.seek = wx.Slider(self, minValue=0, maxValue=1, name=self.labels['position'])
                self.seek.Bind(wx.EVT_SLIDER, self.seek_to)
                root.Add(self.seek, 0, wx.EXPAND | wx.ALL, 8)
                self.position_text = wx.StaticText(self, label='0:00 / 0:00')
                root.Add(self.position_text, 0, wx.LEFT | wx.RIGHT, 8)
                self.speed = wx.Choice(self, choices=['0.5×', '0.75×', '1×', '1.25×', '1.5×', '2×'], name=self.labels['speed'])
                self.speed.SetSelection(2)
                self.speed.Bind(wx.EVT_CHOICE, self.change_speed)
                self.actions.Add(self.speed, 0, wx.ALL, 4)
                volume = wx.Slider(self, value=80, minValue=0, maxValue=100, name=self.labels['volume'])
                volume.Bind(wx.EVT_SLIDER, lambda _: self.player.SetVolume(volume.GetValue() / 100))
                self.actions.Add(volume, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)
                if attachment['kind'] == 'video':
                    self.button('fullscreen', lambda _: self.ShowFullScreen(not self.IsFullScreen()))
                self.relay = NativeMediaRelay(packet)
                wx.CallAfter(self.load_player)
        if attachment['description'] and attachment['kind'] != 'image':
            description = wx.StaticText(self, label=attachment['description'])
            description.Wrap(700)
            root.Add(description, 0, wx.EXPAND | wx.ALL, 8)
        if self.player and packet.get('captions_url'):
            self.caption = wx.StaticText(self, style=wx.ST_NO_AUTORESIZE)
            self.caption.SetMinSize((-1, 70))
            self.caption.SetName(self.labels['captions'])
            root.Add(self.caption, 0, wx.EXPAND | wx.ALL, 8)
            self.caption.Hide()
            self.caption_button = self.button('captions_on', self.toggle_captions)
            self.caption_button.Disable()
            threading.Thread(target=self.load_captions, daemon=True).start()
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        self.button('download', lambda _: self.on_save(self.packet))
        close = wx.Button(self, wx.ID_CANCEL, self.labels['close'])
        close.Bind(wx.EVT_BUTTON, self.finish)
        self.actions.Add(close, 0, wx.ALL, 4)
        self.SetEscapeId(wx.ID_CANCEL)
        root.Add(self.actions, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(root)
        self.SetMinSize((480, 300))

    def button(self, key, callback):
        button = wx.Button(self, label=self.labels[key])
        button.Bind(wx.EVT_BUTTON, callback)
        self.actions.Add(button, 0, wx.ALL, 4)
        return button

    def load_player(self):
        if not self.closed and self.player and not self.player.LoadURI(self.relay.url):
            self.status.SetLabel(self.labels['error'])

    def loaded(self, _):
        if self.closed:
            return
        self.player.SetVolume(0.8)
        self.seek.SetMax(max(1, self.player.Length() // 1000))
        self.play_button.Enable()
        if wx.Window.FindFocus() in {self, self.player, self.play_button}:
            self.play_button.SetFocus()
        self.timer.Start(400)

    def play_state(self, playing):
        if not self.closed:
            self.play_button.SetLabel(self.labels['pause' if playing else 'play'])
            self.on_playback(playing)

    def toggle(self, _):
        if self.player.GetState() == wx.media.MEDIASTATE_PLAYING:
            self.player.Pause()
        elif not self.player.Play():
            self.status.SetLabel(self.labels['error'])

    def change_speed(self, _):
        if not self.player.SetPlaybackRate((0.5, 0.75, 1, 1.25, 1.5, 2)[self.speed.GetSelection()]):
            self.speed.SetSelection(2)
            self.status.SetLabel(self.labels['error'])

    def seek_to(self, _):
        playing = self.player.GetState() == wx.media.MEDIASTATE_PLAYING
        self.player.Seek(self.seek.GetValue() * 1000)
        if playing:
            self.player.Play()

    def tick(self, _):
        if self.player and not self.closed:
            position, duration = max(0, self.player.Tell() // 1000), max(0, self.player.Length() // 1000)
            if not self.seek.HasCapture() and not self.seek.HasFocus():
                self.seek.SetValue(position)
            text = f'{position // 60}:{position % 60:02} / {duration // 60}:{duration % 60:02}'
            if text != self.position_text.GetLabel():
                self.position_text.SetLabel(text)
            if self.caption_visible:
                caption = captions_at(self.caption_cues, self.player.Tell() / 1000)
                if self.caption.GetLabelText() != caption:
                    self.caption.SetLabelText(caption)
                    self.caption.Wrap(max(200, self.GetClientSize().width - 32))

    def load_captions(self):
        try:
            cues = parse_captions(caption_bytes(self.packet))
            wx.CallAfter(self.captions_loaded, cues)
        except Exception:
            wx.CallAfter(self.captions_error)

    def captions_loaded(self, cues):
        if not self.closed:
            self.caption_cues = cues
            self.caption_button.Enable(bool(cues))

    def captions_error(self):
        if not self.closed:
            self.status.SetLabel(self.labels['captions_error'])

    def toggle_captions(self, _):
        self.caption_visible = not self.caption_visible
        self.caption.Show(self.caption_visible)
        self.caption_button.SetLabel(self.labels['captions_off' if self.caption_visible else 'captions_on'])
        self.Layout()

    def load_image(self):
        try:
            content = content_bytes(self.packet)
            wx.CallAfter(self.show_image, content)
        except Exception:
            wx.CallAfter(self.image_error)

    def image_error(self):
        if not self.closed:
            self.status.SetLabel(self.labels['error'])

    def show_image(self, content):
        if self.closed:
            return
        self.image = wx.Image(BytesIO(content))
        if not self.image.IsOk():
            self.image_error()
            return
        self.zoom = min(1.0, 680 / self.image.GetWidth(), 420 / self.image.GetHeight())
        self.resize_image(1)
        if wx.Window.FindFocus() in {self, self.viewport, None}:
            self.viewport.SetFocus()

    def resize_image(self, factor):
        if self.image:
            max_zoom = min(4, math.sqrt(16_000_000 / (self.image.GetWidth() * self.image.GetHeight())))
            self.zoom = min(max_zoom, max(0.1, self.zoom * factor))
            width, height = max(1, round(self.image.GetWidth() * self.zoom)), max(1, round(self.image.GetHeight() * self.zoom))
            self.bitmap.SetBitmap(wx.Bitmap(self.image.Scale(width, height, wx.IMAGE_QUALITY_HIGH)))
            self.bitmap.SetSize((width, height))
            self.viewport.SetVirtualSize((width, height))

    def finish(self, _=None):
        if self.closed:
            return
        self.closed = True
        self.timer.Stop()
        if self.player:
            self.player.Stop()
        self.on_playback(False)
        if self.relay:
            threading.Thread(target=self.relay.close, daemon=True).start()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Hide()
