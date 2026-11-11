"""Device-local picker/player lifecycle; all file access remains server-authorized."""

from pathlib import Path
import re
import threading

import wx

from forum_media_transport import MediaUserError, media_endpoint, media_file_url, save_file, upload_file
from .forum_media_dialog import ForumMediaDialog


class NativeForumMedia:
    def __init__(self, window):
        self.window = window
        self.dialog = None
        self.generation = 0
        self.cancelled = threading.Event()
        self.workers = threading.Semaphore(2)

    def notify(self, message, generation):
        if generation == self.generation and self.window and not self.window.IsBeingDeleted():
            self.window.speaker.speak(message, interrupt=False)

    def playback(self, playing):
        if playing:
            self.window.speaker.speak('', interrupt=True)
        self.window.sound_manager.set_external_ducking('forum-media', {'music': 0.3, 'ambience': 0.3} if playing else None)

    def close(self):
        self.generation += 1
        self.cancelled.set()
        self.cancelled = threading.Event()
        if self.dialog:
            self.dialog.finish()
        self.playback(False)

    def run(self, operation, packet, *args, success):
        generation, cancelled = self.generation, self.cancelled
        def worker():
            with self.workers:
                if cancelled.is_set():
                    return
                try:
                    operation(packet, *args, cancelled)
                    if not cancelled.is_set():
                        wx.CallAfter(self.notify, success, generation)
                except Exception as error:
                    if not cancelled.is_set():
                        wx.CallAfter(self.notify, str(error) if isinstance(error, MediaUserError) else packet['labels']['error'], generation)
        threading.Thread(target=worker, daemon=True).start()

    def choose(self, packet):
        generation = self.generation
        try:
            media_endpoint(packet)
            extensions = [extension for extension in packet.get('accepted_extensions', [])
                          if isinstance(extension, str) and re.fullmatch(r'\.[a-z0-9]{1,10}', extension)]
            wildcard = wx.FileSelectorDefaultWildcardStr
            if extensions:
                wildcard = (packet['labels']['file_filter'] + '|' + ';'.join('*' + ext for ext in extensions)
                            + '|' + packet['labels']['all_files'] + '|*.*')
            with wx.FileDialog(self.window, message=packet['labels']['choose'],
                               wildcard=wildcard,
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                path = Path(dialog.GetPath())
            if generation != self.generation:
                return
            self.window.speaker.speak(' '.join(filter(None, (packet['labels'].get('selected'), packet['labels']['uploading']))), interrupt=False)
            self.run(upload_file, packet, path, success=packet['labels']['processing'])
        except Exception:
            self.notify(packet['labels']['error'], self.generation)

    def save(self, packet):
        generation = self.generation
        with wx.FileDialog(self.dialog or self.window, message=packet['labels']['download'],
                           defaultFile=packet['attachment']['name'], style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = Path(dialog.GetPath())
        if generation != self.generation:
            return
        self.run(save_file, packet, destination, success=packet['labels']['saved'])

    def open(self, packet):
        focused = wx.Window.FindFocus()
        generation = self.generation
        try:
            media_file_url(packet)
            if packet['attachment']['kind'] == 'file':
                self.save(packet)
                return
            if self.dialog:
                self.dialog.finish()
            dialog = ForumMediaDialog(self.window, packet, on_playback=self.playback, on_save=self.save)
            self.dialog = dialog
            try:
                dialog.ShowModal()
            finally:
                if self.dialog is dialog:
                    self.dialog = None
                dialog.Destroy()
        except Exception:
            self.notify(packet['labels']['error'], self.generation)
        finally:
            try:
                if generation == self.generation and focused and not focused.IsBeingDeleted():
                    focused.SetFocus()
            except RuntimeError:
                pass
