/** Reply targets for a focused chat message. */

export const REPLY_QUOTE_LIMIT = 2000;

const PRIVATE_SPEAK_KEYS = new Set([
  "pm-received",
  "pm-sent-content",
  "pm-received-reply",
  "pm-sent-content-reply",
]);

export function clipQuote(message) {
  const text = String(message || "").trim();
  const chars = Array.from(text);
  if (chars.length <= REPLY_QUOTE_LIMIT) {
    return chars.join("");
  }
  return chars.slice(0, REPLY_QUOTE_LIMIT).join("");
}

export function metadataFromChatPacket(packet) {
  const convo = packet?.convo;
  let destination = "";
  if (convo === "global") {
    destination = "global";
  } else if (convo === "private") {
    destination = "private";
  } else if (convo === "local" || convo === "table" || convo === "game") {
    destination = "table";
  } else {
    return null;
  }
  const sender = typeof packet.sender === "string" ? packet.sender.trim() : "";
  const message = typeof packet.message === "string" ? packet.message : "";
  if (!sender || !message.trim()) {
    return null;
  }
  return { kind: "chat", convo: destination, sender, message };
}

export function metadataFromSpeakPacket(packet) {
  if (!PRIVATE_SPEAK_KEYS.has(packet?.key)) {
    return null;
  }
  const params = packet.params;
  if (!params || typeof params !== "object") {
    return null;
  }
  const sender = typeof params.username === "string" ? params.username.trim() : "";
  const message = typeof params.message === "string" ? params.message : "";
  if (!sender || !message.trim()) {
    return null;
  }
  return { kind: "chat", convo: "private", sender, message };
}

export function replyFormatKey(convo) {
  if (convo === "global") {
    return "chat-global-reply";
  }
  if (convo === "private") {
    return "chat-private-reply";
  }
  return "chat-local-reply";
}

export function replyChannelKey(convo) {
  if (convo === "global") {
    return "chat-reply-channel-global";
  }
  if (convo === "private") {
    return "chat-reply-channel-private";
  }
  return "chat-reply-channel-table";
}

export function outgoingChatPacket(message, reply) {
  const text = String(message || "").trim();
  if (!reply) {
    return { type: "chat", convo: "local", message: text };
  }
  const sender = String(reply.sender || "").trim();
  const quote = clipQuote(reply.message || "");
  let packet;
  if (reply.convo === "private" && sender) {
    packet = { type: "chat", convo: "local", message: `@${sender} ${text}` };
  } else if (reply.convo === "global") {
    packet = { type: "chat", convo: "global", message: text };
  } else {
    packet = { type: "chat", convo: "table", message: text };
  }
  if (sender && quote) {
    packet.reply_to = { sender, message: quote };
  }
  return packet;
}
