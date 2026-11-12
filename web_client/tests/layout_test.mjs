import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { installKeybinds } from "../keybinds.js";
import { createCollapsiblePanel, installCollapsiblePanels } from "../ui/collapsiblePanels.js";
import { isMenuItemActionable, normalizeServerMenuItems } from "../ui/menus.js";

class FakeElement {
  constructor({ expanded = "true", hidden = false } = {}) {
    this.attributes = new Map([["aria-expanded", expanded]]);
    this.children = [];
    this.hidden = hidden;
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  contains(element) {
    return element === this || this.children.some((child) => child === element || child.contains?.(element));
  }

  dispatch(type) {
    this.listeners.get(type)?.({ currentTarget: this, type });
  }

  focus() {
    document.activeElement = this;
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

test('a full read-only multiline message starts at the top without selecting all text', async () => {
  const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');
  const start = source.indexOf('  showInlineInput(packet) {');
  const end = source.indexOf('\n  hideInlineInput()', start);
  const show = new Function('requestAnimationFrame', `return ({${source.slice(start, end)}}).showInlineInput;`)((callback) => callback());
  const input = () => ({ hidden: false, scrollTop: 1000, selections: [], selectedAll: false,
    setAttribute() {}, removeAttribute() {}, focus() {},
    select() { this.selectedAll = true; },
    setSelectionRange(...range) { this.selections.push(range); } });
  const textarea = input();
  const spoken = [];
  const app = { elements: { inlineInputValue: textarea, inlineInputText: input(),
    inlineInput: {}, inlineInputPrompt: { setAttribute() {} } },
    speak(text) { spoken.push(text); } };
  const body = 'First line\n' + 'x'.repeat(63989);
  show.call(app, { prompt: 'Message', default_value: body, multiline: true, read_only: true, max_length: 64000 });
  assert.equal(textarea.value, body);
  assert.equal(textarea.readOnly, true);
  assert.deepEqual(textarea.selections, [[0, 0]]);
  assert.equal(textarea.scrollTop, 0);
  assert.equal(textarea.selectedAll, false);
  assert.deepEqual(spoken, ['Message']);
  show.call(app, { prompt: 'Edit', default_value: body, multiline: true, read_only: false, max_length: 64000 });
  assert.equal(textarea.selectedAll, true);
});

test("read-only and legacy text menu rows are never actionable", () => {
  assert.equal(isMenuItemActionable({ id: "confirm", text: "Confirm" }), true);
  assert.equal(isMenuItemActionable({ id: "summary", read_only: true, text: "Summary" }), false);
  assert.equal(isMenuItemActionable({ text: "Legacy information" }), false);
  assert.equal(isMenuItemActionable("Legacy information"), false);
});

test("server menu normalization preserves read-only and copy directive semantics", () => {
  const directive = {
    version: 1,
    text: "first\nsecond",
    success_text: "Copied.",
    failure_text: "Failed.",
  };
  const items = normalizeServerMenuItems([
    { id: "summary", read_only: true, text: "Summary" },
    { id: "copy_page", text: "Copy", copy_directive: directive },
    { id: "invalid_copy", text: "Invalid copy", copy_directive: null },
    "Legacy information",
    null,
  ]);

  assert.equal(isMenuItemActionable(items[0]), false);
  assert.equal(isMenuItemActionable(items[1]), true);
  assert.equal(items[1].copyDirectivePresent, true);
  assert.deepEqual(items[1].copyDirective, directive);
  assert.equal(items[2].copyDirectivePresent, true);
  assert.equal(items[2].copyDirective, null);
  assert.equal(isMenuItemActionable(items[2]), true);
  assert.equal(isMenuItemActionable(items[3]), false);
  assert.equal(isMenuItemActionable(items[4]), false);
});

test("collapsible panels honor markup defaults and keep state synchronized", () => {
  globalThis.document = { activeElement: null };
  const toggle = new FakeElement({ expanded: "false" });
  const content = new FakeElement();
  const panel = createCollapsiblePanel({ toggleEl: toggle, contentEl: content });

  assert.equal(panel.isCollapsed(), true);
  assert.equal(content.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");

  toggle.dispatch("click");
  assert.equal(panel.isCollapsed(), false);
  assert.equal(content.hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
});

test("collapsing a panel moves focus out of content before hiding it", () => {
  const toggle = new FakeElement();
  const content = new FakeElement();
  const child = new FakeElement();
  content.children.push(child);
  globalThis.document = { activeElement: child };

  const panel = createCollapsiblePanel({ toggleEl: toggle, contentEl: content });
  panel.setCollapsed(true);

  assert.equal(document.activeElement, toggle);
  assert.equal(content.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
});

test("the installer creates one controller per complete panel", () => {
  globalThis.document = { activeElement: null };
  const completePanel = {
    dataset: { collapsiblePanel: "chat" },
    querySelector(selector) {
      return selector === ".collapsible-panel-toggle" ? new FakeElement() : new FakeElement();
    },
  };
  const incompletePanel = {
    dataset: { collapsiblePanel: "incomplete" },
    querySelector: () => null,
  };
  const root = { querySelectorAll: () => [completePanel, incompletePanel] };

  const panels = installCollapsiblePanels(root);
  assert.equal(panels.size, 1);
  assert.equal(panels.get("chat")?.isCollapsed(), false);
});

test("game panels expose disclosures without changing the established Tab loop", async () => {
  const [html, appSource] = await Promise.all([
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../app.js", import.meta.url), "utf8"),
  ]);

  for (const name of ["chat", "volume", "shortcuts"]) {
    assert.match(html, new RegExp(`id="${name}-toggle"[\\s\\S]*?aria-controls="${name}-content"`));
  }
  assert.match(html, /id="volume-toggle"[^>]*aria-expanded="false"/);
  assert.match(html, /id="volume-content"[^>]*hidden/);
  assert.match(html, /id="chat-toggle"[^>]*aria-expanded="true"/);
  assert.match(html, /id="shortcuts-toggle"[^>]*aria-expanded="true"/);

  const trapStart = appSource.indexOf("  installInGameTabTrap() {");
  const trapEnd = appSource.indexOf("\n  isVisibleFocusTarget", trapStart);
  const trap = appSource.slice(trapStart, trapEnd);
  assert.match(
    trap,
    /this\.elements\.menuList,[\s\S]*?this\.elements\.historyToggle,[\s\S]*?this\.elements\.historyBuffer,[\s\S]*?this\.elements\.historyBufferMute,[\s\S]*?historyTarget,[\s\S]*?this\.elements\.chatInput/,
  );
  assert.doesNotMatch(trap, /chatToggle|volumeToggle|shortcutsToggle/);
  assert.match(appSource, /this\.collapsiblePanels\.get\("chat"\)\?\.setCollapsed\(false\)/);
  assert.match(
    appSource,
    /!this\.app\.elements\.gameScreen\?\.hidden[\s\S]*?this\.app\.collapsiblePanels\.get\("chat"\)\?\.isCollapsed\(\)[\s\S]*?this\.app\.announceInterface\(text\)/,
  );
});

test("touch-rendered menu cells retain hardware-keyboard navigation", () => {
  const menuButton = { tagName: "BUTTON" };
  const menuElement = { contains: (element) => element === menuButton };
  let keydown = null;
  let selected = null;
  let prevented = false;
  globalThis.document = {
    activeElement: menuButton,
    addEventListener(type, listener) {
      if (type === "keydown") {
        keydown = listener;
      }
    },
  };
  installKeybinds({
    store: {
      state: {
        connection: { authenticated: true },
        currentMenu: {
          gridEnabled: true,
          gridWidth: 12,
          items: Array.from({ length: 144 }, (_, index) => ({ id: `cell_${index}` })),
          selection: 0,
        },
      },
    },
    menuView: {
      getElement: () => menuElement,
      setSelection: (index) => {
        selected = index;
      },
    },
  });

  keydown({
    key: "End",
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    metaKey: false,
    preventDefault: () => {
      prevented = true;
    },
  });

  assert.equal(selected, 11);
  assert.equal(prevented, true);
});

test("F1 requests focused menu help while Ctrl+F1 remains How to Play", () => {
  const menuButton = { tagName: "BUTTON" };
  const menuElement = { contains: (element) => element === menuButton };
  const descriptions = [];
  const keybinds = [];
  let keydown = null;
  globalThis.document = {
    activeElement: menuButton,
    addEventListener(type, listener) {
      if (type === "keydown") {
        keydown = listener;
      }
    },
  };
  installKeybinds({
    store: {
      state: {
        connection: { authenticated: true },
        currentMenu: {
          gridEnabled: false,
          gridWidth: 1,
          items: [{ id: "status_row", read_only: true, text: "Status" }],
          menuId: "turn_menu",
          selection: 0,
        },
      },
    },
    menuView: { getElement: () => menuElement },
    sendKeybind: (packet) => keybinds.push(packet),
    sendMenuDescription: (...args) => descriptions.push(args),
  });

  const pressF1 = (control = false) => keydown({
    key: "F1",
    altKey: false,
    ctrlKey: control,
    shiftKey: false,
    metaKey: false,
    preventDefault() {},
  });

  pressF1();
  assert.deepEqual(descriptions, [["turn_menu", "status_row"]]);
  assert.deepEqual(keybinds, []);

  pressF1(true);
  assert.equal(keybinds.length, 1);
  assert.equal(keybinds[0].key, "f1");
  assert.equal(keybinds[0].control, true);
  assert.equal(keybinds[0].menu_item_id, null);
});

test("message-history punctuation shortcuts keep their established dispatch", () => {
  const menuElement = { contains: () => false };
  const calls = [];
  let keydown = null;
  globalThis.document = {
    activeElement: menuElement,
    addEventListener(type, listener) {
      if (type === "keydown") {
        keydown = listener;
      }
    },
  };
  installKeybinds({
    store: {
      state: {
        connection: { authenticated: true },
        currentMenu: {
          gridEnabled: false,
          gridWidth: 1,
          items: [],
          selection: 0,
        },
      },
    },
    menuView: { getElement: () => menuElement },
    onOlderMessage: () => calls.push("older"),
    onNewerMessage: () => calls.push("newer"),
    onOldestMessage: () => calls.push("oldest"),
    onNewestMessage: () => calls.push("newest"),
  });

  for (const [key, shiftKey, code] of [
    [",", false, "Comma"],
    [".", false, "Period"],
    ["<", true, "Comma"],
    [">", true, "Period"],
    [";", true, "Comma"],
    [":", true, "Period"],
  ]) {
    keydown({
      key,
      code,
      altKey: false,
      ctrlKey: false,
      shiftKey,
      metaKey: false,
      preventDefault() {},
    });
  }

  assert.deepEqual(calls, ["older", "newer", "oldest", "newest", "oldest", "newest"]);
});

test('Ctrl+Shift+F opens the forum while Ctrl+F keeps opening Friends', () => {
  const menu = { contains: () => false };
  const calls = [];
  let keydown;
  globalThis.document = { activeElement: menu, addEventListener(type, listener) {
    if (type === 'keydown') keydown = listener;
  } };
  const store = { state: { connection: { authenticated: true },
    currentMenu: { menuId: 'turn_menu', items: [], selection: 0 } } };
  let modal = false;
  installKeybinds({ store, menuView: { getElement: () => menu },
    sendKeybind: (packet) => calls.push(packet), onOpenFriends: () => calls.push('friends'),
    isModalOpen: () => modal });
  const press = (shiftKey) => keydown({ key: 'F', ctrlKey: true, shiftKey, altKey: false, metaKey: false,
    preventDefault() { calls.push('prevented'); } });
  press(true);
  assert.deepEqual(calls, ['prevented', { key: 'f', control: true, shift: true, alt: false, meta: false, menu_id: 'turn_menu' }]);
  calls.length = 0;
  press(false);
  assert.deepEqual(calls, ['prevented', 'friends']);
  calls.length = 0;
  modal = true;
  press(true);
  assert.deepEqual(calls, []);
  modal = false;
  store.state.connection.authenticated = false;
  press(true);
  assert.deepEqual(calls, []);
});

test('forum post keys read in place, open optional text and request context without moving selection', () => {
  const menu = { contains: () => false };
  let keydown;
  globalThis.document = { activeElement: menu, addEventListener(type, callback) {
    if (type === 'keydown') keydown = callback;
  } };
  const calls = [];
  const store = { state: { connection: { authenticated: true }, currentMenu: {
    menuId:'forum_thread', selection:0, multiletterEnabled:true,
    items:[{id:'post:7'},{id:'thread_poll'}], gridEnabled:false,
  } } };
  installKeybinds({ store, menuView: { getElement:() => menu, moveSelection:() => calls.push('move') },
    sendKeybind:packet => calls.push(packet) });
  const press = (key, shiftKey=false) => keydown({key,shiftKey,ctrlKey:false,altKey:false,metaKey:false,preventDefault(){}});
  for (const [key, shift, expected] of [['ArrowRight',false,'right'],['Enter',false,'enter'],
      ['Enter',true,'enter'],['ContextMenu',false,'applications'],['F10',true,'f10']]) {
    calls.length = 0;
    press(key, shift);
    assert.deepEqual(calls, [{key:expected, shift, control:false, alt:false, meta:false,
      menu_id:'forum_thread', menu_index:1, menu_item_id:'post:7'}]);
  }
  calls.length = 0;
  store.state.currentMenu.selection = 1;
  press('ArrowRight');
  assert.deepEqual(calls, ['move']);
});

test("large grids retain accessible cells and pan on both axes", async () => {
  const css = await readFile(new URL("../style.css", import.meta.url), "utf8");
  const gridStart = css.indexOf(".menu-list.grid-mode {");
  const gridEnd = css.indexOf("\n}", gridStart);
  const gridRule = css.slice(gridStart, gridEnd);

  assert.match(css, /--control-min:\s*44px/);
  assert.match(css, /--grid-cell-min:\s*72px/);
  assert.match(gridRule, /repeat\(var\(--grid-cols\), minmax\(var\(--grid-cell-min\), 1fr\)\)/);
  assert.match(gridRule, /touch-action:\s*pan-x pan-y/);
  assert.match(css, /\.menu-list \{[\s\S]*?overflow:\s*auto/);
  assert.match(css, /\.menu-list \{[\s\S]*?-webkit-overflow-scrolling:\s*touch/);
  assert.match(css, /\.menu-list \{[\s\S]*?max-height:\s*56vh;[\s\S]*?max-height:\s*56dvh/);
  assert.match(css, /\.game-grid > \* \{[\s\S]*?min-width:\s*0/);
  assert.match(css, /\.grid-mode \.menu-item \{[\s\S]*?overflow-wrap:\s*anywhere/);
});

test("every Web locale provides the disclosure headings without obsolete labels", async () => {
  for (const locale of ["en", "vi", "fa", "es", "pt"]) {
    const messages = await import(`../locales/${locale}.js`).then((module) => module.default);
    for (const key of ["chat-heading", "volume-heading", "shortcuts-heading"]) {
      assert.ok(messages[key], `${locale} is missing ${key}`);
    }
    assert.equal(messages["audio-controls-label"], undefined);
    assert.equal(messages["players-title"], undefined);
  }
});

test("locale metadata identifies Persian as right-to-left", async () => {
  const { LOCALE_METADATA } = await import("../locales/manifest.js");
  assert.equal(LOCALE_METADATA.fa.direction, "rtl");
  assert.equal(LOCALE_METADATA.en.direction || "ltr", "ltr");

  const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
  assert.match(
    appSource,
    /document\.documentElement\.dir = LOCALE_METADATA\[bundle\.locale\]\?\.direction \|\| "ltr"/,
  );
});

test("locale bundle changes preserve packet order and authentication chrome", async () => {
  const source = await readFile(new URL("../app.js", import.meta.url), "utf8");
  const packetHandler = source.split("  handlePacket(packet) {", 2)[1].split(
    "\n  beginLocaleUpdate(locale)",
    1,
  )[0];
  assert.match(
    packetHandler,
    /this\.localeUpdateBarrier && packet\.type !== "update_locale"/u,
  );
  assert.match(packetHandler, /this\.localeUpdateGeneration === generation/u);
  assert.match(packetHandler, /this\.handlePacket\(packet\)/u);
  assert.match(packetHandler, /this\.beginLocaleUpdate\(packet\.locale\)/u);

  const updater = source.split("  beginLocaleUpdate(locale) {", 2)[1].split(
    "\n  handleLoginFailed(packet)",
    1,
  )[0];
  assert.match(updater, /const previous = this\.localeUpdateBarrier \|\| Promise\.resolve\(\)/u);
  assert.match(updater, /Localization\.load\(locale/u);
  assert.match(updater, /shouldApply:/u);
  assert.match(updater, /this\.localeUpdateGeneration === generation/u);
  assert.match(updater, /this\.applyLocalization\(\)/u);

  const authorization = source.split("  handleAuthorizeSuccess(packet) {", 2)[1].split(
    "\n  retireLocalSession(",
    1,
  )[0];
  assert.match(
    authorization,
    /this\.beginLocaleUpdate\(packet\.locale\)\.then\(\(applied\)/u,
  );
  assert.match(authorization, /if \(applied\)/u);

  const cleanup = source.split("  cleanupRuntime(full = false) {", 2)[1].split(
    "\n  clearSessionHistory()",
    1,
  )[0];
  assert.match(cleanup, /this\.localeUpdateGeneration \+= 1/u);
  assert.match(cleanup, /this\.localeUpdateBarrier = null/u);
});

test("the offline shell precaches the updated UI modules", async () => {
  const [serviceWorker, gameEntry] = await Promise.all([
    readFile(new URL("../sw.js", import.meta.url), "utf8"),
    readFile(new URL("../game.js", import.meta.url), "utf8"),
  ]);
  const version = gameEntry.match(/PLAYAURAL_WEB_VERSION = "([^"]+)"/u)?.[1];
  assert.ok(version, "the Web entry point must declare its release version");
  const escapedVersion = version.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  assert.match(serviceWorker, new RegExp(`playaural-web-v${escapedVersion}-shell-\\d+`, "u"));
  for (const asset of [
    "store.js",
    "spatial_audio.js",
    "voice_settings.js",
    "ui/history.js",
    "ui/collapsiblePanels.js",
    "vendor/stb-vorbis.js",
  ]) {
    assert.match(serviceWorker, new RegExp(`\\./${asset.replace("/", "\\/")}`));
  }
});

test("the checked-in Web vendors carry complete dependency notices", async () => {
  const [bundle, lockText, notices] = await Promise.all([
    readFile(new URL("../vendor/livekit-client.umd.js", import.meta.url), "utf8"),
    readFile(new URL("../package-lock.json", import.meta.url), "utf8"),
    readFile(new URL("../vendor/THIRD_PARTY_NOTICES.md", import.meta.url), "utf8"),
  ]);
  const lock = JSON.parse(lockText);
  assert.match(bundle, /2\.18\.2/);
  for (const path of Object.keys(lock.packages)) {
    if (!path.startsWith("node_modules/") || path.startsWith("node_modules/@types/")) {
      continue;
    }
    const packageName = path.slice("node_modules/".length);
    assert.ok(
      notices.includes(`| \`${packageName}\``),
      `missing bundled dependency notice for ${packageName}`,
    );
  }
  for (const file of [
    "Apache-2.0.txt",
    "buf-protobuf-BSD-3-Clause.txt",
    "events-MIT.txt",
    "jose-MIT.txt",
    "loglevel-MIT.txt",
    "sdp-MIT.txt",
    "sdp-transform-MIT.txt",
    "tslib-0BSD.txt",
    "typed-emitter-MIT.txt",
    "webrtc-adapter-BSD-3-Clause.txt",
    "stb_vorbis-MIT-or-Public-Domain.txt",
  ]) {
    assert.ok(
      (await readFile(new URL(`../vendor/licenses/${file}`, import.meta.url), "utf8")).trim(),
      `${file} must contain its license text`,
    );
  }
  assert.ok(
    (await readFile(new URL("../vendor/LIVEKIT_NOTICE", import.meta.url), "utf8")).trim(),
  );
});


test("table roster shortcuts preserve key and modifier dispatch", () => {
  const menuElement = { contains: () => false };
  const packets = [];
  let keydown;
  globalThis.document = {
    activeElement: menuElement,
    addEventListener(type, handler) { if (type === "keydown") keydown = handler; },
  };
  installKeybinds({
    store: { state: {
      connection: { authenticated: true },
      currentMenu: { menuId: "turn_menu", items: [{id: "whos_at_table", text: "People"}], selection: 0, multiletter: false },
    } },
    menuView: { getElement: () => menuElement },
    sendKeybind: packet => packets.push(packet),
  });
  for (const [key, control, alt] of [["w", false, false], ["w", true, false], ["u", true, false], ["w", false, true]]) {
    keydown({key, ctrlKey: control, altKey: alt, shiftKey: false, metaKey: false, preventDefault() {}});
    assert.equal(packets.at(-1).key, key);
    assert.equal(packets.at(-1).control, control);
    assert.equal(packets.at(-1).alt, alt);
  }
  assert.equal(packets.length, 4);
  // These assertions cover dispatched application events; browsers may reserve Ctrl+W.
  document.activeElement = { tagName: "INPUT" };
  keydown({key: "w", ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, preventDefault() {}});
  assert.equal(packets.length, 4);
});

test("desktop global hotkeys match remapped layout for friends, chat, volume, and personal options", () => {
  const actions = [];
  let keydown = null;
  const menuElement = { contains: () => true };
  globalThis.document = {
    activeElement: menuElement,
    addEventListener(type, listener) {
      if (type === "keydown") keydown = listener;
    },
  };
  installKeybinds({
    store: {
      state: {
        connection: { authenticated: true },
        currentMenu: { items: [], selection: 0 },
      },
    },
    menuView: { getElement: () => menuElement },
    onOpenFriends: () => actions.push("friends"),
    onToggleTableChat: () => actions.push("table_chat"),
    onToggleGlobalChat: () => actions.push("global_chat"),
    onCycleVolumeNext: () => actions.push("vol_next"),
    onCycleVolumePrev: () => actions.push("vol_prev"),
    onActiveVolumeDown: () => actions.push("vol_down"),
    onActiveVolumeUp: () => actions.push("vol_up"),
    onOpenPersonalOptions: () => actions.push("personal_options"),
  });

  const press = (key, { ctrl = false, alt = false, shift = false } = {}) => {
    keydown({
      key,
      ctrlKey: ctrl,
      altKey: alt,
      shiftKey: shift,
      metaKey: false,
      preventDefault() {},
    });
  };

  press("f", { ctrl: true });
  press("F5");
  press("F5", { shift: true });
  press("F6");
  press("F6", { shift: true });
  press("F7");
  press("F8");
  press("F9");

  assert.deepEqual(actions, [
    "friends",
    "table_chat",
    "global_chat",
    "vol_next",
    "vol_prev",
    "vol_down",
    "vol_up",
    "personal_options",
  ]);
});
