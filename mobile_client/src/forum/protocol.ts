export type ForumMediaSession = { base_url: string; token: string; expires_at: number };
export type ForumMediaLabels = Record<string, string>;
export type ForumFilePickerPacket = ForumMediaSession & {
  type: 'forum_file_picker'; draft_token: string; labels: ForumMediaLabels;
};
export type ForumOpenMediaPacket = ForumMediaSession & {
  type: 'forum_open_media'; url: string; captions_url?: string; labels: ForumMediaLabels;
  attachment: { id: string; name: string; description: string; kind: 'image' | 'audio' | 'video' | 'file';
    mime: string; size: number; duration: number | null; width: number | null; height: number | null };
};

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export const MAX_FILE_BYTES = 128 * 1024 * 1024;

export function mediaBaseURL(packet: ForumMediaSession): string {
  const url = new URL(packet.base_url);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)))
    || url.username || url.password || url.search || url.hash || url.pathname !== '/forum-media'
    || typeof packet.token !== 'string' || !packet.token || packet.token.length > 100) {
    throw new Error('Invalid forum media endpoint');
  }
  return url.href.replace(/\/$/, '');
}

export function mediaFileURL(packet: ForumOpenMediaPacket): string {
  const base = mediaBaseURL(packet);
  const attachment = packet.attachment;
  if (!UUID.test(attachment?.id || '') || !['image', 'audio', 'video', 'file'].includes(attachment?.kind)
    || !Number.isSafeInteger(attachment.size) || attachment.size <= 0 || attachment.size > MAX_FILE_BYTES
    || typeof attachment.name !== 'string' || attachment.name.length > 120
    || typeof attachment.description !== 'string' || attachment.description.length > 1000) {
    throw new Error('Invalid forum attachment');
  }
  const expected = `${base}/files/${attachment.id}`;
  if (packet.url !== expected) throw new Error('Unexpected attachment endpoint');
  if (packet.captions_url && packet.captions_url !== expected + '/captions') throw new Error('Unexpected captions endpoint');
  return expected;
}

export function uploadURL(base: string, value: unknown): { id: string; upload_url: string } {
  const row = value as { id?: string; upload_url?: string };
  if (!UUID.test(row?.id || '') || row.upload_url !== `${base}/uploads/${row.id}`) {
    throw new Error('Unexpected upload endpoint');
  }
  return row as { id: string; upload_url: string };
}
