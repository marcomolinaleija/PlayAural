import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

function compile(name, dependencies = {}) {
  const source = readFileSync(new URL(`../src/forum/${name}.ts`, import.meta.url), 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', js)(module, module.exports, (id) => {
    assert.ok(id in dependencies, `Unexpected dependency ${id}`);
    return dependencies[id];
  });
  return module.exports;
}
const protocol = compile('protocol');
const base = 'https://play.example/forum-media';
const id = '82d6b540-9bd8-4153-92b4-cc89530f9b38';
const labels = { uploading: 'Subiendo', processing: 'Preparando', error: 'Error', size_error: 'Tamaño no permitido', download: 'Guardar' };
const session = { base_url: base, token: 'private-credential', expires_at: 1800000000 };
const picker = { ...session, type: 'forum_file_picker', draft_token: id, labels };
const open = { ...session, type: 'forum_open_media', url: `${base}/files/${id}`, labels,
  attachment: { id, name: 'notes.txt', description: '', kind: 'file', mime: 'text/plain', size: 5, duration: null, width: null, height: null } };
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function harness() {
  const state = { files: new Map([['cache/picked', { size: 5 }]]), deleted: [], directories: new Set(),
    requests: [], announcements: [], shares: [], platform: { OS: 'android' },
    pick: async () => ({ canceled: false, assets: [{ uri: 'cache/picked', name: 'notes.txt', size: 5 }] }),
    request: async (url) => url.endsWith('/uploads')
      ? { ok: true, json: async () => ({ id, upload_url: `${base}/uploads/${id}` }) } : { ok: true },
    sharing: async () => true,
    download: async (url, target) => { state.files.set(target.uri, { size: 5 }); } };
  class Directory {
    constructor(parent, name) { this.uri = `${typeof parent === 'string' ? parent : parent.uri}/${name}`; }
    get exists() { return state.directories.has(this.uri); }
    create() { state.directories.add(this.uri); }
    delete() {
      state.directories.delete(this.uri);
      for (const path of state.files.keys()) if (path.startsWith(this.uri + '/')) state.files.delete(path);
      for (const path of state.directories) if (path.startsWith(this.uri + '/')) state.directories.delete(path);
    }
  }
  class File {
    constructor(parent, name) { this.uri = name === undefined ? parent : `${parent.uri}/${name}`; }
    get exists() { return state.files.has(this.uri); }
    get size() { return state.files.get(this.uri)?.size || 0; }
    delete() { state.deleted.push(this.uri); state.files.delete(this.uri); }
    static async downloadFileAsync(url, target, options) { await state.download(url, target, options); return target; }
  }
  const { ForumMediaTransport, ForumMediaUserError } = compile('transport', {
    './protocol': protocol,
    'expo-document-picker': { getDocumentAsync: (options) => state.pick(options) },
    'expo-file-system': { Directory, File, Paths: { cache: 'cache' } },
    'expo/fetch': { fetch: (url, options) => { state.requests.push({ url, ...options }); return state.request(url, options); } },
    'expo-sharing': { isAvailableAsync: () => state.sharing(), shareAsync: async (...args) => { state.shares.push(args); } },
    'react-native': { Platform: state.platform },
  });
  return { state, transport: new ForumMediaTransport(), ForumMediaUserError,
    announce: (value) => state.announcements.push(value) };
}

test('media credentials and files stay bound to the expected HTTPS endpoint', () => {
  assert.equal(protocol.mediaFileURL(open), open.url);
  assert.equal(protocol.mediaFileURL({ ...open, captions_url: open.url + '/captions' }), open.url);
  for (const base_url of ['http://play.example/forum-media', 'https://user:secret@play.example/forum-media',
    base + '?token=secret', base + '#fragment', 'https://other.example/']) {
    assert.throws(() => protocol.mediaBaseURL({ ...session, base_url }));
  }
  assert.throws(() => protocol.mediaFileURL({ ...open, url: 'https://other.example/private' }));
  assert.throws(() => protocol.mediaFileURL({ ...open, captions_url: 'https://other.example/captions' }));
  assert.throws(() => protocol.uploadURL(base, { id, upload_url: 'https://other.example/uploads/' + id }));
  assert.throws(() => protocol.mediaFileURL({ ...open, attachment: { ...open.attachment, id: '../secret' } }));
  assert.throws(() => protocol.mediaFileURL({ ...open, attachment: { ...open.attachment, size: protocol.MAX_FILE_BYTES + 1 } }));
});

test('native picker uploads bytes over HTTP, binds the draft, and deletes only its temporary copy', async () => {
  const { state, transport, announce } = harness();
  await transport.choose(picker, announce);
  assert.equal(state.requests.length, 2);
  assert.deepEqual(JSON.parse(state.requests[0].body), { name: 'notes.txt', size: 5, draft_token: id });
  assert.equal(state.requests[1].method, 'PUT');
  assert.equal(state.requests[1].headers['Content-Length'], '5');
  assert.equal(state.requests[1].headers.Authorization, `Bearer ${session.token}`);
  assert.deepEqual(state.announcements, [labels.uploading, labels.processing]);
  assert.deepEqual(state.deleted, ['cache/picked']);
});

test('a late picker result after logout is cleaned without reserving or uploading', async () => {
  const { state, transport, announce } = harness();
  const picked = deferred();
  state.pick = () => picked.promise;
  const choosing = transport.choose(picker, announce);
  transport.reset();
  picked.resolve({ canceled: false, assets: [{ uri: 'cache/picked', name: 'notes.txt', size: 5 }] });
  await choosing;
  assert.deepEqual(state.requests, []);
  assert.deepEqual(state.announcements, []);
  assert.deepEqual(state.deleted, ['cache/picked']);
});

test('logout while the reservation body resolves cannot start an upload in the new session', async () => {
  const { state, transport, announce } = harness();
  const entered = deferred();
  const payload = deferred();
  state.request = async () => ({ ok: true, json: () => { entered.resolve(); return payload.promise; } });
  const choosing = transport.choose(picker, announce);
  await entered.promise;
  transport.reset();
  payload.resolve({ id, upload_url: `${base}/uploads/${id}` });
  await choosing;
  assert.equal(state.requests.length, 1);
  assert.equal(state.requests[0].signal.aborted, true);
  assert.deepEqual(state.announcements, [labels.uploading]);
  assert.deepEqual(state.deleted, ['cache/picked']);
});

test('oversized uploads and localized server failures retain actionable feedback', async () => {
  const { state, transport, announce, ForumMediaUserError } = harness();
  state.pick = async () => ({ canceled: false, assets: [{ uri: 'cache/picked', name: 'large.mp4', size: protocol.MAX_FILE_BYTES + 1 }] });
  await assert.rejects(transport.choose(picker, announce), (error) => error instanceof ForumMediaUserError && error.message === labels.size_error);
  assert.deepEqual(state.requests, []);
  state.files.set('cache/picked', { size: 5 });
  state.pick = async () => ({ canceled: false, assets: [{ uri: 'cache/picked', name: 'notes.txt', size: 5 }] });
  state.request = async () => ({ ok: false, json: async () => ({ message: 'Espera a que termine el mantenimiento.' }) });
  await assert.rejects(transport.choose(picker, announce), /Espera a que termine el mantenimiento/);
  assert.equal(state.files.has('cache/picked'), false);
});

test('a replacement session cancels a pending web media bootstrap', async () => {
  const { state, transport } = harness();
  state.platform.OS = 'web';
  const response = deferred();
  state.request = () => response.promise;
  const preparing = transport.prepare(open);
  assert.equal(state.requests[0].credentials, 'include');
  transport.reset();
  response.resolve({ ok: true });
  assert.equal(await preparing, false);
  assert.equal(state.requests[0].signal.aborted, true);
});

test('native opening verifies authorization before mounting a player', async () => {
  const { state, transport, ForumMediaUserError } = harness();
  assert.equal(await transport.prepare(open), true);
  assert.equal(state.requests[0].url, open.url);
  assert.equal(state.requests[0].method, 'HEAD');
  assert.equal(state.requests[0].headers.Authorization, `Bearer ${session.token}`);
  state.request = async () => ({ ok: false, json: async () => ({ message: 'Ya no tienes acceso a este archivo.' }) });
  await assert.rejects(transport.prepare(open), (error) => error instanceof ForumMediaUserError && error.message === 'Ya no tienes acceso a este archivo.');
});

test('closing a player cancels its preparation while preserving a pending draft upload', async () => {
  const { state, transport, announce } = harness();
  const entered = deferred();
  const reserved = deferred();
  state.request = async (url) => url.endsWith('/uploads')
    ? { ok: true, json: () => { entered.resolve(); return reserved.promise; } } : { ok: true };
  const uploading = transport.choose(picker, announce);
  await entered.promise;
  transport.closePlayer();
  assert.equal(state.requests[0].signal.aborted, false);
  reserved.resolve({ id, upload_url: `${base}/uploads/${id}` });
  await uploading;
  assert.equal(state.requests[1].method, 'PUT');
  const ready = deferred();
  state.request = () => ready.promise;
  const opening = transport.prepare(open);
  transport.closePlayer();
  assert.equal(state.requests.at(-1).signal.aborted, true);
  ready.resolve({ ok: true });
  assert.equal(await opening, false);
});

test('native save authenticates its download, opens the OS picker, then removes its private copy', async () => {
  const { state, transport } = harness();
  state.download = async (url, target, options) => {
    assert.equal(url, open.url);
    assert.equal(options.headers.Authorization, `Bearer ${session.token}`);
    state.files.set(target.uri, { size: 5 });
  };
  await transport.save(open);
  assert.equal(state.shares.length, 1);
  assert.equal(state.shares[0][1].mimeType, 'text/plain');
  assert.equal(state.files.has(state.shares[0][0]), false);
  transport.reset();
  assert.equal(state.directories.size, 0);
});

test('closing the player while querying system sharing cannot open a stale save dialog', async () => {
  const { state, transport } = harness();
  const entered = deferred();
  const available = deferred();
  state.sharing = () => { entered.resolve(); return available.promise; };
  const saving = transport.save(open);
  await entered.promise;
  transport.closePlayer();
  available.resolve(true);
  await saving;
  assert.deepEqual(state.shares, []);
  assert.equal(state.directories.size, 0);
});
