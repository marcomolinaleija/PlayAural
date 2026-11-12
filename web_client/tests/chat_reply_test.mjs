import assert from "node:assert/strict";
import test from "node:test";

import {
  REPLY_QUOTE_LIMIT,
  metadataFromChatPacket,
  metadataFromSpeakPacket,
  outgoingChatPacket,
} from "../chatReply.js";

test("chat metadata keeps the raw message and rejects announcements", () => {
  assert.deepEqual(
    metadataFromChatPacket({ convo: "local", sender: "Rayo", message: "hola" }),
    { kind: "chat", convo: "table", sender: "Rayo", message: "hola" },
  );
  assert.equal(
    metadataFromChatPacket({ convo: "announcement", sender: "Sistema", message: "hola" }),
    null,
  );
  assert.equal(
    metadataFromSpeakPacket({
      key: "pm-received",
      params: { username: "Rayo", message: "hola" },
    }).convo,
    "private",
  );
});

test("outgoing replies stay on their channel and clip the quote", () => {
  const quote = "á".repeat(REPLY_QUOTE_LIMIT + 50);
  const table = outgoingChatPacket("yo también", {
    convo: "table",
    sender: "Rayo",
    message: quote,
  });
  assert.equal(table.convo, "table");
  assert.equal(table.reply_to.message, "á".repeat(REPLY_QUOTE_LIMIT));
  assert.deepEqual(
    outgoingChatPacket("voy", { convo: "private", sender: "Nguyễn Văn An", message: "hola" }),
    {
      type: "chat",
      convo: "local",
      message: "@Nguyễn Văn An voy",
      reply_to: { sender: "Nguyễn Văn An", message: "hola" },
    },
  );
});
