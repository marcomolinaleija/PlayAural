export function translationPacketDefinition(type, direction) {
  if (type !== "translation_draft") return null;
  const properties = { type: { const: type }, input_id: { type: "string" }, token: { type: "string" }, sequence: { type: "integer" } };
  const required = ["type", "input_id", "token", "sequence"];
  if (direction === "client_to_server") {
    properties.text = { type: "string" };
    required.push("text");
  } else {
    properties.preview = { type: "string" };
    properties.error = { type: "string" };
    properties.saved = { type: "boolean" };
    required.push("saved");
  }
  return { type: "object", properties, required, additionalProperties: false };
}

/** Debounced, input-bound drafts. Late callbacks never affect another input. */
export class TranslationDraft {
  constructor(send, update, { schedule = setTimeout, cancel = clearTimeout } = {}) {
    this.send = send;
    this.update = update;
    this.schedule = schedule;
    this.cancel = cancel;
    this.context = null;
    this.timer = null;
  }

  open(packet) {
    this.close();
    const draft = packet.translation_draft;
    if (!draft?.token || packet.read_only) return;
    this.context = { token: draft.token, inputId: packet.input_id, sequence: 0,
      acknowledged: 0, lastValue: packet.default_value || "", original: draft.original || "" };
    this.update({ original: this.context.original, preview: "", error: "", saved: false });
  }

  change(value) {
    if (!this.context) return;
    if (this.timer !== null) this.cancel(this.timer);
    const context = this.context;
    this.timer = this.schedule(() => {
      this.timer = null;
      if (this.context === context) this.flush(value);
    }, 600);
  }

  flush(value) {
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    const context = this.context;
    if (!context || value === context.lastValue) return;
    context.lastValue = value;
    this.send({ type: "translation_draft", input_id: context.inputId, token: context.token,
      sequence: ++context.sequence, text: value });
  }

  receive(packet) {
    const context = this.context;
    if (!context || packet.token !== context.token || packet.input_id !== context.inputId
      || packet.sequence !== context.sequence || packet.sequence <= context.acknowledged) return;
    context.acknowledged = packet.sequence;
    this.update({ original: context.original, preview: packet.preview || "", error: packet.error || "", saved: packet.saved === true });
  }

  close() {
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    this.context = null;
  }
}
