import assert from "node:assert/strict";
import test from "node:test";
import { semanticMenuTitle } from "../ui/menuTitle.js";

test("forum navigation uses the localized server heading as its accessible name", () => {
  assert.equal(semanticMenuTitle([
    { id: "heading", read_only: true, text: "Conversación: Nuestra comunidad" },
    { id: "reply", text: "Escribir una respuesta" },
  ]), "Conversación: Nuestra comunidad");
  assert.equal(semanticMenuTitle([
    { id: "confirmation_prompt", read_only: true, text: "¿Descartar este borrador?" },
  ]), "¿Descartar este borrador?");
});

test("ordinary menu options and malformed data cannot override the accessible title", () => {
  assert.equal(semanticMenuTitle([{ id: "heading", text: "An actionable item" }]), "");
  assert.equal(semanticMenuTitle([null, "heading", { id: "heading", read_only: true, text: 42 }]), "");
  assert.equal(semanticMenuTitle(null), "");
});
