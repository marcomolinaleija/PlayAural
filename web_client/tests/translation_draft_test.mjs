import assert from "node:assert/strict";
import test from "node:test";
import { TranslationDraft } from "../translationDraft.js";
import { createPacketValidator } from "../network.js";

function fixture() {
  let next = 0;
  const timers = new Map();
  const sent = [], updates = [];
  const drafts = new TranslationDraft((packet) => sent.push(packet), (state) => updates.push(state), {
    schedule: (callback) => { timers.set(++next, callback); return next; },
    cancel: (id) => timers.delete(id),
  });
  const drain = () => { const pending = [...timers.values()]; timers.clear(); pending.forEach((callback) => callback()); };
  const open = (token = "first") => drafts.open({ input_id: "translation_text_input", default_value: "", translation_draft: { token, original: "Hola" } });
  return { drafts, sent, updates, timers, drain, open };
}

test("typing is debounced and only the latest text is sent without speaking", () => {
  const f = fixture(); f.open();
  f.drafts.change("B"); f.drafts.change("Bon"); f.drafts.change("Bonjour");
  assert.equal(f.sent.length, 0);
  assert.equal(f.timers.size, 1);
  f.drain();
  assert.deepEqual(f.sent, [{ type: "translation_draft", input_id: "translation_text_input", token: "first", sequence: 1, text: "Bonjour" }]);
  f.drafts.change("Bonjour"); f.drain();
  assert.equal(f.sent.length, 1);
});

test("late callbacks and acknowledgements cannot update a replacement input", () => {
  const f = fixture(); f.open(); f.drafts.change("Old");
  const staleCallback = [...f.timers.values()][0];
  f.open("replacement"); staleCallback();
  assert.equal(f.sent.length, 0);
  const count = f.updates.length;
  f.drafts.receive({ input_id: "translation_text_input", token: "first", sequence: 1, preview: "Old" });
  assert.equal(f.updates.length, count);
  f.drafts.change("New"); f.drain();
  f.drafts.receive({ input_id: "translation_text_input", token: "replacement", sequence: 1, preview: "New", saved: true });
  assert.equal(f.updates.at(-1).preview, "New");
  f.drafts.close();
  f.drafts.receive({ input_id: "translation_text_input", token: "replacement", sequence: 2, preview: "After closing" });
  assert.equal(f.updates.at(-1).preview, "New");
});

test("old responses cannot replace the current preview; incomplete text remains saved", () => {
  const f = fixture(); f.open();
  f.drafts.flush("One"); f.drafts.flush("Two {");
  f.drafts.receive({ input_id: "translation_text_input", token: "first", sequence: 1, preview: "One" });
  assert.equal(f.updates.length, 1);
  f.drafts.receive({ input_id: "translation_text_input", token: "first", sequence: 2, error: "Incomplete", saved: true });
  assert.equal(f.updates.at(-1).saved, true);
  assert.equal(f.updates.at(-1).error, "Incomplete");
});

test("ordinary and read-only inputs keep their existing behavior", () => {
  const f = fixture();
  f.drafts.open({ input_id: "ordinary", default_value: "Original" });
  f.drafts.change("Changed"); f.drain();
  f.drafts.open({ input_id: "readonly", read_only: true, translation_draft: { token: "wrong" } });
  f.drafts.change("Changed"); f.drain();
  assert.equal(f.sent.length, 0);
});

test("strict packet validation accepts drafts in both directions and rejects malformed fields", () => {
  const validator = createPacketValidator({});
  assert.equal(validator.validateOutgoing({ type: "translation_draft", input_id: "translation_text_input", token: "bound", sequence: 1, text: "Bonjour" }).ok, true);
  assert.equal(validator.validateIncoming({ type: "translation_draft", input_id: "translation_text_input", token: "bound", sequence: 1, saved: true, preview: "Bonjour" }).ok, true);
  assert.equal(validator.validateOutgoing({ type: "translation_draft", input_id: "translation_text_input", token: "bound", sequence: "wrong", text: "Bonjour" }).ok, false);
  assert.equal(validator.validateIncoming({ type: "translation_draft", input_id: "translation_text_input", token: "bound", sequence: 1, saved: true, html: "<script>" }).ok, false);
});
