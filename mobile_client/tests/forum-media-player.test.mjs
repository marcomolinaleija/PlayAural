import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const labels = { play: 'Reproducir', pause: 'Pausar', position: 'Posición', volume: 'Volumen', speed: 'Velocidad',
  fullscreen: 'Pantalla completa', download: 'Guardar', close: 'Cerrar', error: 'No se pudo abrir el archivo.',
  captions_on: 'Activar subtítulos', captions_off: 'Desactivar subtítulos', captions_error: 'Sin subtítulos' };
function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
const settle = () => new Promise(setImmediate);

function playerHarness(kind = 'video', selfVoicing = true) {
  const calls = { play: 0, pause: 0, prepared: 0, speechStopped: 0, announcements: [], playback: [], sources: [] };
  const events = { playingChange: { isPlaying: false }, statusChange: { status: 'readyToPlay' }, timeUpdate: { currentTime: 0 } };
  const status = { playing: false, currentTime: 0, duration: 120 };
  const player = { status: 'readyToPlay', duration: 120, currentTime: 0, volume: 1, playbackRate: 1,
    availableSubtitleTracks: [{ id: 'captions' }],
    play: () => calls.play++, pause: () => calls.pause++,
    seekBy: (delta) => { player.currentTime = Math.max(0, Math.min(player.duration, player.currentTime + delta)); },
    seekTo: async (value) => { player.currentTime = value; },
    setPlaybackRate: (value) => { player.playbackRate = value; } };
  const slots = [];
  const appStateListeners = new Set();
  let cursor = 0;
  let pendingEffects = [];
  const same = (old, next) => old && next && old.length === next.length && old.every((value, index) => Object.is(value, next[index]));
  const react = {
    useState(initial) {
      const index = cursor++;
      slots[index] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, (value) => { slots[index].value = typeof value === 'function' ? value(slots[index].value) : value; }];
    },
    useRef(initial) { const index = cursor++; slots[index] ??= { current: initial }; return slots[index]; },
    useMemo(callback, dependencies) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].dependencies, dependencies)) slots[index] = { value: callback(), dependencies };
      return slots[index].value;
    },
    useCallback(callback, dependencies) { return react.useMemo(() => callback, dependencies); },
    useEffect(callback, dependencies) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].dependencies, dependencies)) {
        const previous = slots[index];
        slots[index] = { dependencies };
        pendingEffects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback(); });
      }
    },
  };
  const element = (type, props) => ({ type, props });
  let initialized = false;
  const dependencies = {
    react,
    'react/jsx-runtime': { jsx: element, jsxs: element, Fragment: 'Fragment' },
    'react-native': { ActivityIndicator: 'ActivityIndicator', Image: 'Image', Modal: 'Modal', Pressable: 'Pressable',
      ScrollView: 'ScrollView', Text: 'Text', View: 'View', StyleSheet: { create: (value) => value },
      AppState: { currentState: 'active', addEventListener: (_, listener) => {
        appStateListeners.add(listener);
        return { remove() { appStateListeners.delete(listener); } };
      } } },
    '@react-native-community/slider': { default: 'Slider' },
    'expo-audio': { useAudioPlayer: (source) => { calls.sources.push(source); return player; }, useAudioPlayerStatus: () => status },
    'expo-video': { VideoView: 'VideoView', useVideoPlayer: (source, setup) => {
      calls.sources.push(source);
      if (!initialized) { initialized = true; setup(player); }
      return player;
    } },
    expo: { useEvent: (_, name) => events[name] },
    '../gestures/useSelfVoicingGestures': { useSelfVoicingGestures: (callbacks) => { calls.gestures = callbacks; return { panHandlers: {} }; } },
    '../app/useFocusScroll': { useFocusScroll: (key, nodes) => { calls.scroll = { key, nodes }; return {}; } },
    './transport': { ForumMediaUserError: class extends Error {} },
  };
  const source = readFileSync(new URL('../src/forum/ForumMediaModal.tsx', import.meta.url), 'utf8');
  const js = ts.transpileModule(source + '\nexport const testComponents = { AudioAttachment, VideoAttachment, Actions };', {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', js)(module, module.exports, (id) => {
    assert.ok(id in dependencies, `Unexpected dependency ${id}`);
    return dependencies[id];
  });
  const component = kind === 'modal' ? module.exports.ForumMediaModal
    : module.exports.testComponents[kind === 'actions' ? 'Actions' : kind === 'audio' ? 'AudioAttachment' : 'VideoAttachment'];
  const props = { selfVoicing, packet: { token: 'credential', url: 'https://play.example/forum-media/files/id',
    captions_url: 'https://play.example/forum-media/files/id/captions', labels,
    attachment: { kind, name: 'Example', description: 'Description' } },
    announce: (text) => calls.announcements.push(text), stopSpeech: () => calls.speechStopped++,
    preparePlayback: async () => { calls.prepared++; }, onPlayback: (playing) => calls.playback.push(playing),
    onClose() {}, onSave: async () => {} };
  return { calls, player, events, status, props,
    background() { for (const listener of appStateListeners) listener('background'); },
    render(renderProps = props) {
      cursor = 0; pendingEffects = [];
      const tree = component(renderProps);
      for (const effect of pendingEffects) effect();
      return tree;
    },
    unmount() { for (const slot of slots) slot?.cleanup?.(); },
  };
}
function action(tree, id) { return tree.props.actions.find((item) => item.id === id); }
function descendants(tree, type) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap((child) => descendants(child, type));
  return [...(tree.type === type ? [tree] : []), ...descendants(tree.props?.children, type)];
}

for (const kind of ['audio', 'video']) {
  test(`${kind} opens paused and waits for the shared audio coordinator before explicit playback`, async () => {
    const harness = playerHarness(kind);
    const ready = deferred();
    harness.props.preparePlayback = () => { harness.calls.prepared++; return ready.promise; };
    const tree = harness.render();
    assert.equal(harness.calls.play, 0);
    assert.equal(harness.player.volume, 0.8);
    assert.equal(harness.calls.sources[0].headers.Authorization, 'Bearer credential');
    action(tree, 'play').run();
    assert.equal(harness.calls.prepared, 1);
    assert.equal(harness.calls.speechStopped, 1);
    assert.equal(harness.calls.play, 0);
    ready.resolve();
    await settle();
    assert.equal(harness.calls.play, 1);
    harness.unmount();
    assert.equal(harness.calls.playback.at(-1), false);
  });

  test(`${kind} cannot start late after its view closes`, async () => {
    const harness = playerHarness(kind);
    const ready = deferred();
    harness.props.preparePlayback = () => ready.promise;
    action(harness.render(), 'play').run();
    harness.unmount();
    ready.resolve();
    await settle();
    assert.equal(harness.calls.play, 0);
  });

  test(`${kind} does not start in background or duplicate a pending Play request`, async () => {
    const harness = playerHarness(kind);
    const ready = deferred();
    harness.props.preparePlayback = () => { harness.calls.prepared++; return ready.promise; };
    const tree = harness.render();
    action(tree, 'play').run();
    action(tree, 'play').run();
    assert.equal(harness.calls.prepared, 1);
    harness.background();
    assert.equal(harness.calls.pause, 1);
    ready.resolve();
    await settle();
    assert.equal(harness.calls.play, 0);
    harness.unmount();
  });

  test(`${kind} announces self-voicing speed and volume changes, including silence`, () => {
    const harness = playerHarness(kind);
    action(harness.render(), 'speed').run();
    assert.equal(harness.player.playbackRate, 1.25);
    assert.equal(harness.calls.announcements.at(-1), 'Velocidad: 1.25×');
    action(harness.render(), 'volume').run();
    assert.equal(harness.player.volume, 1);
    action(harness.render(), 'volume').run();
    assert.equal(harness.player.volume, 0);
    assert.equal(harness.calls.announcements.at(-1), 'Volumen: 0%');
    harness.unmount();
  });
}

test('video playback controls share the gesture surface and never bypass coordinated Play', () => {
  const harness = playerHarness('video', false);
  const tree = harness.render();
  assert.equal(descendants(tree, 'VideoView')[0].props.nativeControls, false);
  assert.ok(action(tree, 'play'));
  const slider = descendants(tree, 'Slider').find((item) => item.props.accessibilityLabel === labels.volume);
  slider.props.onValueChange(0.25);
  assert.equal(harness.player.volume, 0.25);
  assert.equal(harness.calls.play, 0);
  harness.unmount();
});

test('video time updates leave an in-progress seek at the user-selected position', () => {
  const harness = playerHarness();
  const seek = (tree) => descendants(tree, 'Slider').find((item) => item.props.accessibilityLabel === labels.position);
  seek(harness.render()).props.onSlidingStart(30);
  harness.events.timeUpdate.currentTime = 10;
  assert.equal(seek(harness.render()).props.value, 30);
  seek(harness.render()).props.onSlidingComplete(35);
  assert.equal(harness.player.currentTime, 35);
  harness.unmount();
});

test('video errors announce once, restore app mixing and retain Close and Save', () => {
  const harness = playerHarness();
  harness.render();
  harness.events.statusChange.status = 'error';
  const tree = harness.render();
  harness.render();
  assert.deepEqual(harness.calls.announcements, [labels.error]);
  assert.equal(harness.calls.playback.at(-1), false);
  assert.ok(action(tree, 'close'));
  assert.ok(action(tree, 'save'));
  assert.ok(descendants(tree, 'Text').some((item) => item.props.children === labels.error));
  harness.unmount();
});

test('rapid repeated Save activation opens only one system dialog', async () => {
  const harness = playerHarness();
  const saved = deferred();
  let count = 0;
  harness.props.onSave = () => { count++; return saved.promise; };
  const tree = harness.render();
  action(tree, 'save').run();
  action(tree, 'save').run();
  assert.equal(count, 1);
  saved.resolve();
  await settle();
  harness.unmount();
});

test('rapid self-voicing navigation advances immediately and reveals actions by stable id', () => {
  const harness = playerHarness('actions');
  const focused = [], activated = [];
  harness.props.onActionFocus = (id) => focused.push(id);
  harness.props.actionNodes = { current: new Map() };
  const actions = ['play', 'speed', 'save', 'close'].map((id) => ({ id, label: id, run: () => activated.push(id) }));
  harness.render({ actions, props: harness.props });
  harness.calls.gestures.onSingleFingerSwipe('down');
  harness.calls.gestures.onSingleFingerSwipe('down');
  harness.calls.gestures.onDoubleTap();
  assert.deepEqual(focused, ['speed', 'save']);
  assert.deepEqual(activated, ['save']);
  harness.calls.gestures.onThreeFingerSwipe('down');
  harness.calls.gestures.onDoubleTap();
  const expanded = [...actions.slice(0, 3), { id: 'volume', label: 'volume', run() {} }, actions[3]];
  const tree = harness.render({ actions: expanded, props: harness.props });
  const buttons = descendants(tree, 'Pressable');
  const close = buttons.at(-1);
  const node = {};
  close.props.ref(node);
  assert.equal(harness.props.actionNodes.current.get('close'), node);
  assert.equal(close.props.style.at(-1).borderColor, '#fff');
  assert.deepEqual(focused, ['speed', 'save', 'close']);
  assert.deepEqual(activated, ['save', 'close']);
  close.props.ref(null);
  assert.equal(harness.props.actionNodes.current.size, 0);
  harness.unmount();
});

test('the media modal connects action focus to the existing scroll-reveal coordinator', () => {
  const harness = playerHarness('modal');
  const tree = harness.render();
  const scroll = descendants(tree, 'ScrollView')[0];
  const media = scroll.props.children;
  assert.equal(harness.calls.scroll.key, null);
  assert.equal(media.props.actionNodes, harness.calls.scroll.nodes);
  media.props.onActionFocus('close');
  harness.render();
  assert.equal(harness.calls.scroll.key, 'close');
  harness.props.selfVoicing = false;
  harness.render();
  assert.equal(harness.calls.scroll.key, null);
  harness.unmount();
});

test('video Back exits fullscreen before closing its player', async () => {
  const harness = playerHarness();
  let closed = 0, exited = 0;
  harness.props.onClose = () => closed++;
  const tree = harness.render();
  const video = descendants(tree, 'VideoView')[0];
  video.props.ref.current = { exitFullscreen: async () => exited++ };
  video.props.onFullscreenEnter();
  const fullscreen = harness.render();
  fullscreen.props.props.onClose();
  await settle();
  assert.equal(exited, 1);
  assert.equal(closed, 0);
  descendants(fullscreen, 'VideoView')[0].props.onFullscreenExit();
  action(harness.render(), 'close').run();
  assert.equal(closed, 1);
  harness.unmount();
});
