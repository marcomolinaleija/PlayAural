import assert from 'node:assert/strict';
import test from 'node:test';
import { ForumMedia, mediaBaseURL, mediaFileURL } from '../ui/forumMedia.js';
import { createPacketValidator } from '../network.js';

const id = '82d6b540-9bd8-4153-92b4-cc89530f9b38';
const base = 'https://example.test/forum-media';
const labels = { close: 'Cerrar', error: 'Error', speed: 'Velocidad', download: 'Guardar', choose: 'Elegir', uploading: 'Subiendo', processing: 'Preparando' };
const packet = { type: 'forum_open_media', base_url: base, token: 'secret', expires_at: 1800000000,
  attachment: { id, name: 'test.mp3', kind: 'audio', description: '' }, url: `${base}/files/${id}`, labels };

class Element {
  constructor(tag, document) {
    this.tagName = tag;
    this.document = document;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.isConnected = true;
    this.style = {};
  }
  append(...elements) { for (const element of elements) { element.parent?.detach(element); this.children.push(element); element.parent = this; } }
  prepend(element) { this.children.unshift(element); element.parent = this; }
  detach(element) { this.children = this.children.filter((child) => child !== element); }
  remove() { this.parent?.detach(this); this.isConnected = false; }
  addEventListener(type, callback) { this.listeners.set(type, [...(this.listeners.get(type) || []), callback]); }
  dispatch(type) { return Promise.all((this.listeners.get(type) || []).map((listener) => listener({ preventDefault() {} }))); }
  click() { this.document.downloads.push(this); }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  focus() { this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  pause() { this.paused = true; this.dispatch('pause'); }
  load() { this.unloaded = true; }
  get firstElementChild() { return this.children[0]; }
}
function documentFixture() {
  const document = { createElement: (tag) => new Element(tag, document), downloads: [] };
  document.body = document.createElement('body');
  document.activeElement = document.createElement('button');
  return document;
}
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
function picker(media) {
  media.choose({ ...packet, type: 'forum_file_picker', draft_token: id });
  const input = media.dialog.children[1].children[0];
  input.files = [{ name: 'sample.mp3', size: 10 }];
  return input;
}

test('the default browser fetch retains its Window receiver', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async function () { assert.equal(this, globalThis); return { ok: true }; };
    const media = new ForumMedia({ document: documentFixture(), announce() {} });
    await media.open(packet);
    assert.ok(media.player);
    media.close();
  } finally { globalThis.fetch = original; }
});

test('closing a picker during cookie bootstrap prevents a late reservation', async () => {
  const ready = deferred();
  const requests = [];
  const media = new ForumMedia({ document: documentFixture(), announce() {}, fetch: (url, options) => {
    requests.push({ url, options }); return ready.promise;
  } });
  const input = picker(media);
  const choosing = input.dispatch('change');
  media.close();
  ready.resolve({ ok: true });
  await choosing;
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.signal.aborted, true);
});

test('closing a picker while reservation JSON resolves cannot start a stale binary upload', async () => {
  const entered = deferred();
  const reservation = deferred();
  const requests = [];
  const media = new ForumMedia({ document: documentFixture(), announce() {}, fetch: async (url, options) => {
    requests.push({ url, options });
    return url.endsWith('/session') ? { ok: true } : { ok: true, json: () => { entered.resolve(); return reservation.promise; } };
  } });
  const choosing = picker(media).dispatch('change');
  await entered.promise;
  media.close();
  reservation.resolve({ id, upload_url: `${base}/uploads/${id}` });
  await choosing;
  assert.equal(requests.length, 2);
});

test('saving is single activation and a late download cannot open after player close', async () => {
  const blob = deferred();
  const entered = deferred();
  const document = documentFixture();
  let downloads = 0;
  const media = new ForumMedia({ document, announce() {}, fetch: async (url) => {
    if (url.endsWith('/session')) return { ok: true };
    downloads++;
    return { ok: true, blob: () => { entered.resolve(); return blob.promise; } };
  } });
  await media.open(packet);
  const save = media.dialog.children[3].children.find((child) => child.textContent === labels.download);
  const first = save.dispatch('click');
  await entered.promise;
  await save.dispatch('click');
  assert.equal(downloads, 1);
  media.close();
  blob.resolve(new Blob(['sample']));
  await first;
  assert.deepEqual(document.downloads, []);
});

test('media URLs never accept credentials, URL tokens, arbitrary paths or file endpoints', () => {
  assert.equal(mediaFileURL(packet), packet.url);
  assert.equal(mediaBaseURL('http://127.0.0.1:8001/forum-media'), 'http://127.0.0.1:8001/forum-media');
  for (const url of ['file:///forum-media', 'javascript:alert(1)', 'http://remote.test/forum-media',
    'https://user:pass@example.test/forum-media', base + '?token=secret', base + '#secret', 'https://example.test/other']) {
    assert.throws(() => mediaBaseURL(url));
  }
  assert.throws(() => mediaFileURL({ ...packet, url: 'https://other.test/file' }));
  assert.throws(() => mediaFileURL({ ...packet, attachment: { id: '../../file' } }));
});

test('media extensions remain validated with a strict older packet schema', () => {
  const validator = createPacketValidator({});
  assert.equal(validator.validateIncoming(packet).ok, true);
  assert.equal(validator.validateIncoming({ ...packet, token: 5 }).ok, false);
  assert.equal(validator.validateIncoming({ ...packet, unexpected: 'value' }).ok, false);
  assert.equal(validator.validateOutgoing({ type: 'forum_media_session' }).ok, true);
  assert.equal(validator.validateOutgoing({ type: 'forum_media_session', user: 'forged' }).ok, false);
});

test('opening is silent, playback is explicit, and closing stops media and restores focus', async () => {
  const document = documentFixture();
  const returnFocus = document.activeElement;
  const events = [];
  const requests = [];
  const media = new ForumMedia({ document, announce() {}, onPlayback: (playing) => events.push(playing),
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true }; } });
  await media.open(packet);
  const player = media.player;
  assert.equal(player.autoplay, false);
  assert.equal(player.controls, true);
  assert.equal(player.src, packet.url);
  assert.ok(!events.includes(true));
  assert.equal(requests[0].url, `${base}/session`);
  assert.equal(requests[0].options.headers.Authorization, 'Bearer secret');
  assert.equal(requests[0].options.credentials, 'include');
  player.dispatch('play');
  assert.equal(events.at(-1), true);
  media.dialog.dispatch('cancel');
  assert.equal(player.paused, true);
  assert.equal(player.unloaded, true);
  assert.equal(events.at(-1), false);
  assert.equal(document.activeElement, returnFocus);
  assert.equal(media.isOpen(), false);
});

test('a late bootstrap response cannot reopen a player after session cleanup', async () => {
  const document = documentFixture();
  let resolve;
  const media = new ForumMedia({ document, announce() {}, fetch: () => new Promise((done) => { resolve = done; }) });
  const opening = media.open(packet);
  media.close(false);
  resolve({ ok: true });
  await opening;
  assert.equal(media.isOpen(), false);
  assert.equal(media.player, null);
});

test('Escape exits fullscreen before closing the underlying player', async () => {
  const document = documentFixture();
  const media = new ForumMedia({ document, announce() {}, fetch: async () => ({ ok: true }) });
  await media.open({ ...packet, attachment: { ...packet.attachment, kind: 'video' } });
  const player = media.player;
  document.fullscreenElement = player;
  let exits = 0;
  document.exitFullscreen = async () => { exits++; document.fullscreenElement = null; };
  await media.dialog.dispatch('cancel');
  assert.equal(exits, 1);
  assert.equal(media.player, player);
  assert.equal(media.isOpen(), true);
  await media.dialog.dispatch('cancel');
  assert.equal(media.isOpen(), false);
});

test('Escape preserves the player when exiting iOS native fullscreen', async () => {
  const document = documentFixture();
  const media = new ForumMedia({ document, announce() {}, fetch: async () => ({ ok: true }) });
  await media.open({ ...packet, attachment: { ...packet.attachment, kind: 'video' } });
  const player = media.player;
  player.webkitDisplayingFullscreen = true;
  player.webkitExitFullscreen = () => { player.webkitDisplayingFullscreen = false; };
  await media.dialog.dispatch('cancel');
  assert.equal(media.isOpen(), true);
  assert.equal(media.player, player);
  assert.equal(player.webkitDisplayingFullscreen, false);
  media.close();
});

test('switching files tears down the previous player and failed authorization exposes no file', async () => {
  const document = documentFixture();
  let allowed = true;
  const media = new ForumMedia({ document, announce() {}, fetch: async () => ({ ok: allowed }) });
  await media.open(packet);
  const previous = media.player;
  allowed = false;
  await media.open(packet);
  assert.equal(previous.paused, true);
  assert.equal(media.player, null);
  assert.equal(media.dialog.children[2].textContent, labels.error);
  media.close();
});
