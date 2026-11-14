import * as DocumentPicker from 'expo-document-picker';
import { Directory, File, Paths } from 'expo-file-system';
import { fetch } from 'expo/fetch';
import * as Sharing from 'expo-sharing';
import { Platform } from 'react-native';
import { MAX_FILE_BYTES, mediaBaseURL, mediaFileURL, uploadURL,
  type ForumFilePickerPacket, type ForumOpenMediaPacket } from './protocol';

export class ForumMediaUserError extends Error {}

async function failure(response: { json: () => Promise<unknown> }, fallback: string): Promise<ForumMediaUserError> {
  let message: unknown;
  try { message = (await response.json() as { message?: unknown }).message; } catch { /* A proxy may return a plain error page. */ }
  return new ForumMediaUserError(typeof message === 'string' && message && message.length <= 1024 ? message : fallback);
}

/** Per-session temporary downloads. Explicit Save hands a copy to the OS. */
export class ForumMediaTransport {
  private generation = 0;
  private abort = new AbortController();
  private playerGeneration = 0;
  private playerAbort = new AbortController();
  private directory: Directory | null = null;

  reset(): void {
    this.generation += 1;
    this.abort.abort();
    this.abort = new AbortController();
    this.closePlayer();
  }

  closePlayer(): void {
    this.playerGeneration += 1;
    this.playerAbort.abort();
    this.playerAbort = new AbortController();
    try { if (this.directory?.exists) this.directory.delete(); } catch { /* Active downloads clean up their own temporary files. */ }
    this.directory = null;
  }

  private cacheDirectory(): Directory {
    if (!this.directory) {
      this.directory = new Directory(Paths.cache, `forum-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      this.directory.create({ intermediates: true });
    }
    return this.directory;
  }

  async prepare(packet: ForumOpenMediaPacket): Promise<boolean> {
    const url = mediaFileURL(packet);
    const generation = this.playerGeneration;
    if (Platform.OS === 'web') {
      const response = await fetch(`${packet.base_url}/session`, { method: 'POST',
        headers: { Authorization: `Bearer ${packet.token}` }, credentials: 'include', signal: this.playerAbort.signal });
      if (!response.ok) throw await failure(response, packet.labels.error);
    } else {
      // Fail visibly before mounting a native player whose SDK may not expose
      // HTTP/authorization errors as a distinct playback status.
      const response = await fetch(url, { method: 'HEAD', headers: { Authorization: `Bearer ${packet.token}` },
        signal: this.playerAbort.signal });
      if (!response.ok) throw await failure(response, packet.labels.error);
    }
    return generation === this.playerGeneration;
  }

  async choose(packet: ForumFilePickerPacket, announce: (message: string) => void): Promise<void> {
    const base = mediaBaseURL(packet);
    const generation = this.generation;
    const picked = await DocumentPicker.getDocumentAsync({ multiple: false, copyToCacheDirectory: true, base64: false });
    if (picked.canceled) return;
    const asset = picked.assets[0];
    const nativeFile = Platform.OS !== 'web' ? new File(asset.uri) : null;
    const body = Platform.OS === 'web' ? asset.file : nativeFile;
    const size = asset.size ?? nativeFile?.size ?? 0;
    try {
      if (generation !== this.generation) return;
      if (!body || !Number.isSafeInteger(size) || size <= 0 || size > MAX_FILE_BYTES) {
        throw new ForumMediaUserError(packet.labels.size_error || packet.labels.error);
      }
      announce(packet.labels.uploading);
      const reserved = await fetch(`${base}/uploads`, { method: 'POST',
        headers: { Authorization: `Bearer ${packet.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: asset.name, size, draft_token: packet.draft_token }), signal: this.abort.signal });
      if (!reserved.ok) throw await failure(reserved, packet.labels.error);
      if (generation !== this.generation) return;
      const reservation = uploadURL(base, await reserved.json());
      if (generation !== this.generation) return;
      const response = await fetch(reservation.upload_url, { method: 'PUT',
        headers: { Authorization: `Bearer ${packet.token}`, ...(Platform.OS !== 'web' ? { 'Content-Length': String(size) } : {}) },
        body, signal: this.abort.signal });
      if (!response.ok) throw await failure(response, packet.labels.error);
      if (generation === this.generation) announce(packet.labels.processing);
    } catch (error) {
      if (generation === this.generation) throw error;
    } finally {
      // DocumentPicker supplied this app's temporary copy, never the original.
      if (nativeFile?.exists) nativeFile.delete();
    }
  }

  async save(packet: ForumOpenMediaPacket): Promise<void> {
    const url = mediaFileURL(packet);
    const generation = this.playerGeneration;
    if (Platform.OS === 'web') {
      const response = await fetch(url, { headers: { Authorization: `Bearer ${packet.token}` }, signal: this.playerAbort.signal });
      if (!response.ok) throw await failure(response, packet.labels.error);
      const objectURL = URL.createObjectURL(await response.blob());
      try {
        if (generation !== this.playerGeneration) return;
        const anchor = document.createElement('a');
        anchor.href = objectURL;
        anchor.download = packet.attachment.name;
        anchor.click();
      } finally { setTimeout(() => URL.revokeObjectURL(objectURL), 1000); }
      return;
    }
    const downloadDirectory = new Directory(this.cacheDirectory(), `download-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    downloadDirectory.create();
    const target = new File(downloadDirectory, packet.attachment.name.replace(/[\\/]/g, '_'));
    try {
      await File.downloadFileAsync(url, target, { headers: { Authorization: `Bearer ${packet.token}` }, idempotent: true });
      if (generation !== this.playerGeneration) return;
      if (target.size !== packet.attachment.size) throw new Error('Cannot save this file');
      const sharingAvailable = await Sharing.isAvailableAsync();
      if (generation !== this.playerGeneration) return;
      if (!sharingAvailable) throw new Error('Cannot save this file');
      await Sharing.shareAsync(target.uri, { mimeType: packet.attachment.mime, dialogTitle: packet.labels.download });
    } finally {
      if (target.exists) target.delete();
      if (downloadDirectory.exists) downloadDirectory.delete();
    }
  }
}
