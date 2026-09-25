const caption = document.querySelector("#embed-caption");
const pathParts = location.pathname.split("/").filter(Boolean);
const sessionId = pathParts[pathParts.length - 1];
const language = new URLSearchParams(location.search).get("lang") || "es";

let clearTimer;
let displayTimer;
let displayQueue = [];
let pendingDraft;
let currentDisplay;
let lastSequence = 0;
let lastConfirmedRaw = "";
const displayedDrafts = new Map();
const finalizedGroups = new Set();

function wrapCaptionLines(text, maxCharacters = window.innerWidth <= 600 ? 28 : 42) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > maxCharacters && line) { lines.push(line); line = word; }
    else line = candidate;
  }
  if (line) lines.push(line);
  return lines;
}

function captionText(data) {
  return data.source_language === language || data.language === language
    ? data.original || ""
    : data.translation || "";
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
  const calculated = text.replace(/\s+/g, " ").length / 20 * 1000;
  return Math.round(Math.max(final ? 1800 : 2300, Math.min(calculated, 3200)));
}

function displayCaption(item) {
  currentDisplay = item;
  caption.innerHTML = "";
  const span = document.createElement("span");
  span.textContent = item.text;
  caption.append(span);
  caption.hidden = !item.text;
  clearTimeout(clearTimer);
  clearTimeout(displayTimer);
  let visibleFor = item.duration;
  if (displayQueue.length >= 2) visibleFor = Math.max(1200, Math.round(visibleFor * 0.5));
  else if (displayQueue.length >= 1) visibleFor = Math.max(1500, Math.round(visibleFor * 0.72));
  displayTimer = setTimeout(() => {
    currentDisplay = null;
    showNextCaption();
  }, visibleFor);
}

function showNextCaption() {
  const confirmed = displayQueue.shift();
  if (confirmed) {
    displayCaption(confirmed);
    return;
  }
  if (pendingDraft) {
    const draft = pendingDraft;
    pendingDraft = null;
    if (!finalizedGroups.has(draft.group)) {
      const text = wrapCaptionLines(draft.raw).slice(-2).join("\n");
      displayedDrafts.set(draft.group, draft.raw);
      displayCaption({ text, duration: readingDuration(text, false), audioEnd: draft.audioEnd, final: false });
      return;
    }
  }
  clearTimer = setTimeout(() => { caption.hidden = true; }, 900);
}

function resetCaptionScheduler() {
  clearTimeout(clearTimer);
  clearTimeout(displayTimer);
  displayQueue = [];
  pendingDraft = null;
  currentDisplay = null;
  lastSequence = 0;
  lastConfirmedRaw = "";
  displayedDrafts.clear();
  finalizedGroups.clear();
  caption.hidden = true;
  caption.innerHTML = "";
}

function scheduleCaption(data) {
  const sequence = Number(data.sequence || 0);
  if (sequence === 1 && lastSequence > 1) resetCaptionScheduler();
  if (sequence > 0) lastSequence = sequence;
  const raw = captionText(data).trim();
  if (!raw) return;
  const group = String(data.audio_start_seconds ?? data.sequence ?? "caption");
  if (data.final === false) {
    pendingDraft = { raw, group, audioEnd: data.audio_end_seconds };
    if (!currentDisplay && displayQueue.length === 0) showNextCaption();
    return;
  }
  finalizedGroups.add(group);
  if (pendingDraft?.group === group) pendingDraft = null;
  const displayedDraft = displayedDrafts.get(group);
  const confirmed = (displayedDraft
    ? removeDisplayedPrefix(displayedDraft, raw)
    : removePreviousSuffix(lastConfirmedRaw, raw)).trim();
  lastConfirmedRaw = raw;
  for (const text of captionPages(confirmed)) {
    displayQueue.push({ text, duration: readingDuration(text, true), audioEnd: data.audio_end_seconds, final: true });
  }
  if (!currentDisplay) showNextCaption();
}

const events = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/events`);
events.addEventListener("caption", event => scheduleCaption(JSON.parse(event.data)));
