// Server-authored headings keep accessible menu names in the user's locale.
// Plain text is returned as data; callers assign it through text/ARIA APIs.
export function semanticMenuTitle(items) {
  if (!Array.isArray(items)) return "";
  const heading = items.find((item) => item
    && typeof item === "object"
    && item.read_only === true
    && (item.id === "heading" || item.id === "confirmation_prompt")
    && typeof item.text === "string"
    && item.text.trim());
  return heading?.text || "";
}
