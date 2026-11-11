const TYPES = new Set(["forum_file_picker", "forum_open_media", "forum_media_session"]);
const ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

async function mediaFailure(response, fallback) {
  let message = '';
  try { message = (await response.json()).message; } catch { /* A proxy may return a plain error page. */ }
  const error = new Error('Media request failed');
  error.userMessage = typeof message === 'string' && message.length <= 1024 && message ? message : fallback;
  return error;
}

export function forumPacketDefinition(type, direction) {
  if (direction === "client_to_server") {
    return type === "forum_media_session"
      ? { properties: { type: { const: type } }, required: ["type"], additionalProperties: false } : null;
  }
  if (!TYPES.has(type)) return null;
  const properties = {
    type: { const: type }, base_url: { type: "string" }, token: { type: "string" }, expires_at: { type: "integer" },
  };
  if (type === "forum_file_picker") {
    properties.draft_token = { type: "string" };
    properties.labels = { type: "object" };
  }
  if (type === "forum_open_media") {
    properties.attachment = { type: "object" };
    properties.url = { type: "string" };
    properties.labels = { type: "object" };
    properties.captions_url = { type: 'string' };
  }
  return { properties, required: Object.keys(properties).filter((key) => key !== 'captions_url'), additionalProperties: false };
}

export function mediaBaseURL(value) {
  const url = new URL(value);
  if ((url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))
      || url.username || url.password || url.search || url.hash || url.pathname !== "/forum-media") {
    throw new Error("Invalid forum media endpoint");
  }
  return url.href.replace(/\/$/, "");
}

export function mediaFileURL(packet) {
  const base = mediaBaseURL(packet.base_url);
  if (!ID.test(packet.attachment?.id || "")) throw new Error("Invalid attachment");
  const expected = `${base}/files/${packet.attachment.id}`;
  if (packet.url !== expected) throw new Error("Unexpected attachment URL");
  return expected;
}

/** A single explicit player/picker. Binary content never enters WebSocket JSON. */
export class ForumMedia {
  constructor({ announce, onPlayback = () => {}, isSelfVoicing = () => false, document = globalThis.document, fetch = globalThis.fetch.bind(globalThis) }) {
    this.document = document;
    this.fetch = fetch;
    this.announce = announce;
    this.onPlayback = onPlayback;
    this.isSelfVoicing = isSelfVoicing;
    this.generation = 0;
    this.dialog = null;
    this.player = null;
    this.abort = null;
  }

  isOpen() { return Boolean(this.dialog); }

  close(restoreFocus = true) {
    this.generation += 1;
    this.abort?.abort();
    this.abort = null;
    if (this.player) {
      this.player.pause();
      this.player.removeAttribute("src");
      this.player.load();
      this.player = null;
    }
    this.onPlayback(false);
    if (this.dialog) {
      this.dialog.close();
      this.dialog.remove();
      this.dialog = null;
    }
    if (restoreFocus && this.returnFocus?.isConnected) this.returnFocus.focus();
    this.returnFocus = null;
  }

  element(tag, text = "") {
    const element = this.document.createElement(tag);
    if (text) element.textContent = text;
    return element;
  }

  button(text, action, parent) {
    const button = this.element("button", text);
    button.type = "button";
    button.addEventListener("click", action);
    button.addEventListener('focus', () => { if (this.isSelfVoicing()) this.announce(text); });
    parent.append(button);
    return button;
  }

  surface(title, labels) {
    const returnFocus = this.returnFocus || this.document.activeElement;
    this.close(false);
    this.returnFocus = returnFocus;
    this.abort = new AbortController();
    const dialog = this.element("dialog");
    dialog.className = "forum-media-dialog";
    dialog.setAttribute("aria-label", title);
    const heading = this.element("h2", title);
    dialog.append(heading);
    const content = this.element("div");
    content.className = "forum-media-content";
    dialog.append(content);
    const status = this.element("p");
    status.setAttribute("role", "status");
    status.tabIndex = -1;
    dialog.append(status);
    const actions = this.element("div");
    actions.className = "forum-media-actions";
    dialog.append(actions);
    this.button(labels.close, () => this.close(), actions);
    dialog.addEventListener("cancel", async (event) => {
      event.preventDefault();
      const generation = this.generation;
      // Escape resolves the visible fullscreen layer before the player dialog.
      if (this.document.fullscreenElement && this.document.exitFullscreen) {
        try { await this.document.exitFullscreen(); }
        catch (error) { this.error(error, { status, generation }, labels); }
        return;
      }
      if (this.player?.webkitDisplayingFullscreen && this.player.webkitExitFullscreen) {
        this.player.webkitExitFullscreen();
        return;
      }
      this.close();
    });
    this.document.body.append(dialog);
    this.dialog = dialog;
    dialog.showModal();
    status.focus();
    return { content, actions, status, generation: this.generation, signal: this.abort.signal };
  }

  async authorize(packet, signal) {
    const base = mediaBaseURL(packet.base_url);
    if (typeof packet.token !== "string" || !packet.token || packet.token.length > 100) throw new Error("Invalid media session");
    const response = await this.fetch(`${base}/session`, {
      method: "POST", headers: { Authorization: `Bearer ${packet.token}` },
      credentials: "include", cache: "no-store", signal,
    });
    if (!response.ok) throw await mediaFailure(response, packet.labels?.error);
    return base;
  }

  error(error, surface, labels) {
    if (surface.generation === this.generation && error?.name !== "AbortError") {
      console.warn('Forum media request failed', error);
      surface.status.textContent = error.userMessage || labels.error;
    }
  }

  choose(packet) {
    const labels = packet.labels;
    const surface = this.surface(labels.choose, labels);
    const input = this.element("input");
    input.type = "file";
    input.setAttribute("aria-label", labels.choose);
    surface.content.append(input);
    input.focus();
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file || !this.dialog) return;
      input.disabled = true;
      surface.status.textContent = labels.uploading;
      const progress = this.element("progress");
      progress.setAttribute("aria-label", labels.uploading);
      surface.content.append(progress);
      try {
        if (!file.size || file.size > 128 * 1024 * 1024) {
          const error = new Error('Invalid file size'); error.userMessage = labels.size_error || labels.error; throw error;
        }
        const base = await this.authorize(packet, surface.signal);
        if (surface.generation !== this.generation) return;
        const headers = { Authorization: `Bearer ${packet.token}` };
        const reserved = await this.fetch(`${base}/uploads`, {
          method: "POST", headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ draft_token: packet.draft_token, name: file.name, size: file.size }),
          credentials: "include", cache: "no-store", signal: surface.signal,
        });
        if (!reserved.ok) throw await mediaFailure(reserved, labels.error);
        const reservation = await reserved.json();
        if (surface.generation !== this.generation) return;
        if (!ID.test(reservation.id || "") || reservation.upload_url !== `${base}/uploads/${reservation.id}`) {
          throw new Error("Unexpected upload endpoint");
        }
        const uploaded = await this.fetch(reservation.upload_url, {
          method: "PUT", headers, body: file, credentials: "include", cache: "no-store", signal: surface.signal,
        });
        if (!uploaded.ok) throw await mediaFailure(uploaded, labels.error);
        if (surface.generation === this.generation) {
          this.announce(labels.processing);
          this.close();
        }
      } catch (error) {
        this.error(error, surface, labels);
        input.disabled = false;
      } finally {
        progress.remove();
      }
    });
  }

  async open(packet) {
    const labels = packet.labels;
    const attachment = packet.attachment;
    const url = mediaFileURL(packet);
    if (!["image", "audio", "video", "file"].includes(attachment.kind)) return;
    const surface = this.surface(attachment.name, labels);
    surface.status.textContent = labels.processing;
    try {
      await this.authorize(packet, surface.signal);
      if (surface.generation !== this.generation) return;
      surface.status.textContent = '';
      if (attachment.description) {
        const description = this.element('p', attachment.description);
        if (attachment.kind === 'image') description.setAttribute('aria-hidden', 'true');
        surface.content.append(description);
      }
      if (attachment.kind === "image") {
        const image = this.element("img");
        image.alt = attachment.description || attachment.name;
        image.crossOrigin = "use-credentials";
        image.src = url;
        image.tabIndex = 0;
        surface.content.prepend(image);
        let zoom = 1;
        for (const [label, factor] of [[labels.zoom_in, 1.25], [labels.zoom_out, 0.8]]) {
          this.button(label, () => { zoom = Math.max(0.25, Math.min(4, zoom * factor)); image.style.width = `${zoom * 100}%`; }, surface.actions);
        }
        image.addEventListener("error", () => { surface.status.textContent = labels.error; });
        image.addEventListener('focus', () => { if (this.isSelfVoicing()) this.announce(image.alt); });
        if (this.document.activeElement === surface.status) image.focus();
      } else if (["audio", "video"].includes(attachment.kind)) {
        const player = this.element(attachment.kind);
        player.controls = true;
        player.tabIndex = 0;
        player.autoplay = false;
        player.preload = "metadata";
        player.crossOrigin = "use-credentials";
        player.setAttribute("aria-label", attachment.name);
        if (attachment.kind === "video") player.playsInline = true;
        player.src = url;
        if (attachment.kind === 'video' && packet.captions_url) {
          if (packet.captions_url !== `${url}/captions`) throw new Error('Unexpected captions endpoint');
          const track = this.element('track');
          track.kind = 'captions';
          track.label = labels.captions;
          track.srclang = 'und';
          track.src = packet.captions_url;
          player.append(track);
        }
        this.player = player;
        player.addEventListener("play", () => { if (this.player === player) this.onPlayback(true); });
        for (const event of ["pause", "ended", "error"]) player.addEventListener(event, () => {
          if (this.player === player) this.onPlayback(false);
        });
        player.addEventListener("error", () => { surface.status.textContent = labels.error; });
        surface.content.prepend(player);
        const speedLabel = this.element("label", labels.speed);
        const speed = this.element("select");
        for (const rate of [0.5, 0.75, 1, 1.25, 1.5, 2]) {
          const option = this.element("option", `${rate}×`);
          option.value = String(rate);
          option.selected = rate === 1;
          speed.append(option);
        }
        speed.addEventListener("change", () => { player.playbackRate = Number(speed.value); });
        speed.addEventListener('focus', () => { if (this.isSelfVoicing()) this.announce(`${labels.speed}: ${speed.value}×`); });
        speedLabel.append(speed);
        surface.actions.append(speedLabel);
        if (this.document.activeElement === surface.status) player.focus();
      }
      let saving = false;
      const save = this.button(labels.download, async () => {
        if (saving || surface.generation !== this.generation) return;
        saving = true;
        save.disabled = true;
        try {
          const response = await this.fetch(url, { headers: { Authorization: `Bearer ${packet.token}` },
            credentials: "include", cache: "no-store", signal: surface.signal });
          if (!response.ok) throw await mediaFailure(response, labels.error);
          const blob = await response.blob();
          if (surface.generation !== this.generation) return;
          const localURL = URL.createObjectURL(blob);
          const link = this.element("a");
          link.href = localURL;
          link.download = attachment.name;
          link.click();
          setTimeout(() => URL.revokeObjectURL(localURL), 1000);
        } catch (error) { this.error(error, surface, labels); }
        finally { saving = false; save.disabled = false; }
      }, surface.actions);
      if (attachment.kind === 'file' && this.document.activeElement === surface.status) save.focus();
      // Keep the final action and native Escape as the same close operation.
      surface.actions.append(surface.actions.firstElementChild);
    } catch (error) { this.error(error, surface, labels); }
  }
}
