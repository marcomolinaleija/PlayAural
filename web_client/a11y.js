export function createA11y({ politeEl, assertiveEl }) {
  const ANNOUNCEMENT_MUTATION_GAP_MS = 140;
  const DUPLICATE_WINDOW_MS = 700;
  let announcementNonce = 0;
  const queues = new Map();

  function queueFor(target) {
    if (!target) {
      return null;
    }
    if (!queues.has(target)) {
      queues.set(target, {
        active: false,
        items: [],
        lastAnnouncementAt: 0,
        lastAnnouncementText: "",
        lastRenderedText: "",
        timer: null,
      });
    }
    return queues.get(target);
  }

  function normalize(text) {
    return String(text)
      .replace(/\s*\n+\s*/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function processQueue(target, state) {
    if (state.active) {
      return;
    }
    let next = state.items.shift();
    if (!next) {
      return;
    }

    let now = performance.now();
    while (next) {
      now = performance.now();
      if (
        next.interrupt
        || next.text !== state.lastAnnouncementText
        || now - state.lastAnnouncementAt >= DUPLICATE_WINDOW_MS
      ) {
        break;
      }
      next = state.items.shift();
    }
    if (!next) {
      return;
    }

    const renderedText = (
      next.interrupt && state.lastRenderedText === next.text
        ? `${next.text}\u00A0`
        : next.text
    );
    state.active = true;
    state.lastAnnouncementText = next.text;
    state.lastRenderedText = renderedText;
    state.lastAnnouncementAt = now;
    target.replaceChildren();

    requestAnimationFrame(() => {
      const span = document.createElement("span");
      span.setAttribute("data-announce-id", String(next.id));
      span.textContent = renderedText;
      target.replaceChildren(span);

      state.timer = window.setTimeout(() => {
        state.timer = null;
        state.active = false;
        processQueue(target, state);
      }, ANNOUNCEMENT_MUTATION_GAP_MS);
    });
  }

  function announce(text, options = {}) {
    const { assertive = false, interrupt = false } = options;
    const target = assertive ? assertiveEl : politeEl;
    const state = queueFor(target);
    if (!target || !state) {
      return;
    }
    const normalized = normalize(text);
    if (!normalized) {
      return;
    }
    if (interrupt) {
      state.items.length = 0;
      if (state.timer) {
        window.clearTimeout(state.timer);
        state.timer = null;
      }
      state.active = false;
    }
    announcementNonce += 1;
    state.items.push({
      id: announcementNonce,
      interrupt: Boolean(interrupt),
      text: normalized,
    });
    processQueue(target, state);
  }

  return { announce };
}
