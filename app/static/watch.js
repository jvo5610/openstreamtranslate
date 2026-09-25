const sessionSelect = document.querySelector("#session-select");
const status = document.querySelector("#audience-status");
const sessionState = document.querySelector("#session-state");
const sessionTitle = document.querySelector("#session-title");
const liveKicker = document.querySelector("#live-kicker");
const player = document.querySelector("#player-shell");
const video = document.querySelector("#stream-video");
const placeholder = document.querySelector("#video-placeholder");
const videoCaption = document.querySelector("#video-caption");
const overlayPrimary = document.querySelector("#overlay-primary");
const playToggle = document.querySelector("#play-toggle");
const muteToggle = document.querySelector("#mute-toggle");
const fullscreenToggle = document.querySelector("#fullscreen-toggle");
const languageButton = document.querySelector("#caption-language-button");
const languageLabel = document.querySelector("#caption-language-label");
const languageMenu = document.querySelector("#caption-language-menu");

let sessions = [];
let eventSource;
let lastCaption;
let activeMediaSignature = "";
let initialized = false;
let clearTimer;
let displayTimer;
let displayQueue = [];
let pendingDraft;
let currentDisplay;
let lastSequence = 0;
let lastConfirmedRaw = "";
const displayedDrafts = new Map();
const finalizedGroups = new Set();
let selectedLanguage = localStorage.getItem("caption-language") || "es";

function wrapCaptionLines(text, maxCharacters = window.innerWidth <= 600 ? 38 : 42) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > maxCharacters && line) {
      lines.push(line);
      line = word;
    } else line = candidate;
  }
  if (line) lines.push(line);
  return lines;
}

function captionText(caption) {
  if (!caption || selectedLanguage === "off") return "";
  if (caption.source_language === selectedLanguage || caption.language === selectedLanguage) return caption.original || "";
  if (caption.target_language === selectedLanguage) return caption.translation || "";
  return selectedLanguage === "es" ? caption.translation || caption.original : caption.original || caption.translation;
}

function captionGroup(caption) {
  return String(caption.audio_start_seconds ?? caption.sequence ?? "caption");
}

function normalizedWord(word) {
  return word.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

function removeDisplayedPrefix(previous, current) {
  const previousWords = String(previous || "").trim().split(/\s+/).filter(Boolean);
  const currentWords = String(current || "").trim().split(/\s+/).filter(Boolean);
  let shared = 0;
  while (
    shared < previousWords.length
    && shared < currentWords.length
    && normalizedWord(previousWords[shared]) === normalizedWord(currentWords[shared])
  ) shared += 1;
  return shared >= 2 ? currentWords.slice(shared).join(" ") : current;
}

function removePreviousSuffix(previous, current) {
  const previousWords = String(previous || "").trim().split(/\s+/).filter(Boolean);
  const currentWords = String(current || "").trim().split(/\s+/).filter(Boolean);
  const maximum = Math.min(10, previousWords.length, currentWords.length);
  for (let count = maximum; count >= 2; count -= 1) {
    const suffix = previousWords.slice(-count).map(normalizedWord).join(" ");
    const prefix = currentWords.slice(0, count).map(normalizedWord).join(" ");
    if (suffix === prefix) return currentWords.slice(count).join(" ");
  }
  return current;
}

function captionPages(text) {
  const lines = wrapCaptionLines(text);
  const pages = [];
  for (let index = 0; index < lines.length; index += 2) {
    pages.push(lines.slice(index, index + 2).join("\n"));
  }
  return pages.filter(Boolean);
}

function readingDuration(text, final) {
  const characters = text.replace(/\s+/g, " ").length;
  const calculated = characters / 20 * 1000;
  return Math.round(Math.max(final ? 1800 : 2300, Math.min(calculated, 3200)));
}

function displayCaption(item) {
  currentDisplay = item;
  overlayPrimary.textContent = item.text;
  videoCaption.hidden = !item.text || selectedLanguage === "off";
  clearTimeout(clearTimer);
  clearTimeout(displayTimer);
  const audioEnd = Number(item.audioEnd || 0);
  const lag = audioEnd > 0 && Number.isFinite(video.currentTime)
    ? Math.max(0, video.currentTime - audioEnd)
    : 0;
  let visibleFor = item.duration;
  if (lag >= 2.7) visibleFor = Math.max(1200, Math.round(visibleFor * 0.55));
  else if (lag >= 1.3) visibleFor = Math.max(1500, Math.round(visibleFor * 0.75));
  if (displayQueue.length >= 2) visibleFor = Math.max(1100, Math.round(visibleFor * 0.72));
  videoCaption.dataset.audioEnd = String(audioEnd);
  videoCaption.dataset.displayVideoTime = String(Number(video.currentTime || 0).toFixed(3));
  videoCaption.dataset.lag = String(lag.toFixed(3));
  videoCaption.dataset.visibleFor = String(visibleFor);
  videoCaption.dataset.queueDepth = String(displayQueue.length);
  videoCaption.dataset.final = String(item.final !== false);
  displayTimer = setTimeout(() => {
    currentDisplay = null;
    showNextCaption();
  }, visibleFor);
}

function showNextCaption() {
  if (selectedLanguage === "off") {
    videoCaption.hidden = true;
    overlayPrimary.textContent = "";
    return;
  }
  const confirmed = displayQueue.shift();
  if (confirmed) {
    displayCaption(confirmed);
    return;
  }
  if (pendingDraft) {
    const draft = pendingDraft;
    pendingDraft = null;
    if (!finalizedGroups.has(draft.group)) {
      const lines = wrapCaptionLines(draft.raw);
      const text = lines.slice(-2).join("\n");
      displayedDrafts.set(draft.group, draft.raw);
      displayCaption({
        text,
        duration: readingDuration(text, false),
        final: false,
        audioEnd: draft.audioEnd,
      });
      return;
    }
  }
  clearTimer = setTimeout(() => {
    videoCaption.hidden = true;
    overlayPrimary.textContent = "";
  }, 900);
}

function resetCaptionScheduler(showLatest = false) {
  clearTimeout(clearTimer);
  clearTimeout(displayTimer);
  displayQueue = [];
  pendingDraft = null;
  currentDisplay = null;
  lastSequence = 0;
  lastConfirmedRaw = "";
  displayedDrafts.clear();
  finalizedGroups.clear();
  videoCaption.hidden = true;
  overlayPrimary.textContent = "";
  if (showLatest && lastCaption && selectedLanguage !== "off") scheduleCaption(lastCaption);
}

function scheduleCaption(caption) {
  if (!caption) return;
  const sequence = Number(caption.sequence || 0);
  if (sequence === 1 && lastSequence > 1) resetCaptionScheduler();
  if (sequence > 0) lastSequence = sequence;
  lastCaption = caption;
  if (selectedLanguage === "off") return;
  const raw = captionText(caption).trim();
  if (!raw) return;
  const group = captionGroup(caption);
  if (caption.final === false) {
    pendingDraft = { raw, group, audioEnd: caption.audio_end_seconds };
    if (!currentDisplay && displayQueue.length === 0) showNextCaption();
    return;
  }

  finalizedGroups.add(group);
  if (pendingDraft?.group === group) pendingDraft = null;
  const displayedDraft = displayedDrafts.get(group);
  const confirmedText = (displayedDraft
    ? removeDisplayedPrefix(displayedDraft, raw)
    : removePreviousSuffix(lastConfirmedRaw, raw)).trim();
  lastConfirmedRaw = raw;
  for (const text of captionPages(confirmedText)) {
    displayQueue.push({
      text,
      duration: readingDuration(text, true),
      final: true,
      audioEnd: caption.audio_end_seconds,
    });
  }
  if (!currentDisplay) showNextCaption();
}

function updateLanguageMenu() {
  languageLabel.textContent = selectedLanguage === "off" ? "OFF" : selectedLanguage.toUpperCase();
  languageButton.classList.toggle("active", selectedLanguage !== "off");
  for (const button of languageMenu.querySelectorAll("[data-language]")) {
    button.setAttribute("aria-checked", String(button.dataset.language === selectedLanguage));
  }
  resetCaptionScheduler(true);
}

function connectEvents() {
  eventSource?.close();
  if (!sessionSelect.value) return;
  status.textContent = "Conectando…";
  status.classList.remove("ok");
  eventSource = new EventSource(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/events`);
  eventSource.addEventListener("caption", event => scheduleCaption(JSON.parse(event.data)));
  eventSource.onopen = () => {
    status.textContent = "Conectado";
    status.classList.add("ok");
  };
  eventSource.onerror = () => {
    status.textContent = "Reconectando…";
    status.classList.remove("ok");
  };
}

function syncVideo(session) {
  const signature = session?.media_url ? `${session.id}:${session.started_at || 0}` : "";
  if (!signature) {
    activeMediaSignature = "";
    video.pause();
    video.removeAttribute("src");
    video.load();
    placeholder.hidden = false;
    playToggle.textContent = "▶";
    return;
  }
  placeholder.hidden = true;
  if (signature === activeMediaSignature) return;
  if (activeMediaSignature) {
    lastCaption = null;
    resetCaptionScheduler();
  }
  activeMediaSignature = signature;
  video.src = `${session.media_url}?start=${session.started_at || 0}`;
  video.onloadedmetadata = async () => {
    const elapsed = Math.max(0, Date.now() / 1000 - Number(session.started_at || Date.now() / 1000));
    if (session.status === "live" && Number.isFinite(video.duration) && elapsed < video.duration) video.currentTime = elapsed;
    try {
      await video.play();
    } catch {
      status.textContent = "Señal lista · presioná play";
    }
  };
}

function syncMuteButton() {
  const muted = video.muted || video.volume === 0;
  muteToggle.innerHTML = muted
    ? '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9H4Z"/><path d="m17 9 5 5m0-5-5 5"/></svg>'
    : '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9H4Z"/><path d="M16 9.5a4 4 0 0 1 0 5m2.5-8a8 8 0 0 1 0 11"/></svg>';
  muteToggle.setAttribute("aria-label", muted ? "Activar sonido" : "Silenciar");
  muteToggle.setAttribute("aria-pressed", String(muted));
  muteToggle.title = muted ? "Activar sonido" : "Silenciar";
}

function renderSession() {
  const session = sessions.find(item => item.id === sessionSelect.value);
  if (!session) return;
  sessionState.textContent = String(session.status || "idle").toUpperCase();
  liveKicker.textContent = session.status === "live" ? "EN VIVO" : String(session.status || "esperando").toUpperCase();
  sessionTitle.textContent = session.title || session.id;
  syncVideo(session);
}

async function refreshSessions() {
  const response = await fetch("/api/sessions");
  if (!response.ok) throw new Error("No se pudo cargar el catálogo");
  sessions = (await response.json()).sessions;
  const previous = sessionSelect.value;
  const requested = new URLSearchParams(location.search).get("session");
  const selected = [previous, requested, "main-stage"].find(value => value && sessions.some(item => item.id === value)) || sessions[0]?.id;
  const signature = sessions.map(item => `${item.id}:${item.title}`).join("|");
  if (sessionSelect.dataset.signature !== signature) {
    sessionSelect.dataset.signature = signature;
    sessionSelect.innerHTML = "";
    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session.id;
      option.textContent = session.title || session.id;
      sessionSelect.append(option);
    }
  }
  sessionSelect.value = selected;
  renderSession();
  if (!initialized) {
    initialized = true;
    connectEvents();
  }
}

sessionSelect.addEventListener("change", () => {
  lastCaption = null;
  resetCaptionScheduler();
  activeMediaSignature = "";
  connectEvents();
  renderSession();
});

languageButton.addEventListener("click", event => {
  event.stopPropagation();
  languageMenu.hidden = !languageMenu.hidden;
  languageButton.setAttribute("aria-expanded", String(!languageMenu.hidden));
});

languageMenu.addEventListener("click", event => {
  const button = event.target.closest("[data-language]");
  if (!button) return;
  selectedLanguage = button.dataset.language;
  localStorage.setItem("caption-language", selectedLanguage);
  languageMenu.hidden = true;
  languageButton.setAttribute("aria-expanded", "false");
  updateLanguageMenu();
});

document.addEventListener("click", event => {
  if (!event.target.closest(".caption-control")) {
    languageMenu.hidden = true;
    languageButton.setAttribute("aria-expanded", "false");
  }
});

playToggle.addEventListener("click", async () => {
  if (video.paused) await video.play().catch(() => {});
  else video.pause();
});
video.addEventListener("click", () => playToggle.click());
video.addEventListener("play", () => { playToggle.textContent = "❚❚"; playToggle.setAttribute("aria-label", "Pausar"); });
video.addEventListener("pause", () => { playToggle.textContent = "▶"; playToggle.setAttribute("aria-label", "Reproducir"); });
muteToggle.addEventListener("click", () => {
  const shouldUnmute = video.muted || video.volume === 0;
  video.muted = !shouldUnmute;
  if (shouldUnmute && video.volume === 0) video.volume = 1;
  syncMuteButton();
});
video.addEventListener("volumechange", syncMuteButton);
fullscreenToggle.addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else player.requestFullscreen();
});

updateLanguageMenu();
syncMuteButton();
refreshSessions().catch(error => { status.textContent = error.message; });
setInterval(() => refreshSessions().catch(() => {}), 3000);
