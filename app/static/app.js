const sessionSelect = document.querySelector("#session-select");
const directionSelect = document.querySelector("#direction-select");
const micButton = document.querySelector("#mic");
const streamInput = document.querySelector("#stream-file");
const stopButton = document.querySelector("#stop-stream");
const health = document.querySelector("#health");
const mode = document.querySelector("#mode");
const sourceStatus = document.querySelector("#source-status");
const preview = document.querySelector("#preview");
const placeholder = document.querySelector("#video-placeholder");
const videoCaption = document.querySelector("#video-caption");
const overlay = document.querySelector("#overlay-primary");
const glossaryEntries = document.querySelector("#glossary-entries");
const glossaryDirection = document.querySelector("#glossary-direction");
const glossaryStatus = document.querySelector("#glossary-status");
const saveGlossaryButton = document.querySelector("#save-glossary");
const exportLanguage = document.querySelector("#export-language");
const exportButtons = document.querySelectorAll(".export-button");

let socket;
let eventSource;
let audioContext;
let mediaStream;
let sourceNode;
let processor;
let sourceKind;
let active = false;
let clearTimer;
let glossaryLoadSequence = 0;

function languages() {
  const [source, target] = directionSelect.value.split("-");
  return { source, target };
}

function updateExportLinks() {
  const { source, target } = languages();
  const selected = exportLanguage.value;
  exportLanguage.innerHTML = "";
  for (const language of [source, target]) {
    const option = document.createElement("option");
    option.value = language;
    option.textContent = language === "es" ? "Español" : "English";
    exportLanguage.append(option);
  }
  exportLanguage.value = [source, target].includes(selected) ? selected : target;
  for (const button of exportButtons) {
    const format = button.dataset.format;
    button.href = `/api/sessions/${encodeURIComponent(sessionSelect.value)}/transcript/${format}?language=${encodeURIComponent(exportLanguage.value)}`;
  }
}

function fitCaption(text, maxCharacters = window.innerWidth <= 600 ? 38 : 42) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > maxCharacters && line) { lines.push(line); line = word; }
    else line = candidate;
  }
  if (line) lines.push(line);
  return lines.slice(-2).join("\n");
}

function glossaryFromText() {
  const entries = [];
  const seen = new Set();
  for (const line of glossaryEntries.value.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    const source = (separator >= 0 ? trimmed.slice(0, separator) : trimmed).trim();
    const target = (separator >= 0 ? trimmed.slice(separator + 1) : source).trim() || source;
    const key = source.toLocaleLowerCase();
    if (!source || seen.has(key)) continue;
    seen.add(key);
    entries.push({ source, target });
  }
  return entries;
}

function glossaryToText(entries) {
  return entries.map(entry => (
    entry.target && entry.target !== entry.source
      ? `${entry.source} = ${entry.target}`
      : entry.source
  )).join("\n");
}

async function loadGlossary() {
  const sequence = ++glossaryLoadSequence;
  const { source, target } = languages();
  glossaryDirection.textContent = `${source.toUpperCase()} → ${target.toUpperCase()}`;
  glossaryStatus.textContent = "Cargando…";
  const query = new URLSearchParams({ source_language: source, target_language: target });
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/glossary?${query}`);
  if (!response.ok) throw new Error("No se pudo cargar el glosario");
  const data = await response.json();
  if (sequence !== glossaryLoadSequence) return;
  glossaryEntries.value = glossaryToText(data.entries);
  glossaryStatus.textContent = `${data.entries.length} términos listos para esta dirección.`;
}

async function saveGlossary() {
  const { source, target } = languages();
  const entries = glossaryFromText();
  glossaryStatus.textContent = "Guardando…";
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/glossary`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_language: source, target_language: target, entries }),
  });
  if (!response.ok) throw new Error("No se pudo guardar el glosario");
  const data = await response.json();
  glossaryEntries.value = glossaryToText(data.entries);
  glossaryStatus.textContent = `${data.entries.length} términos guardados · se aplican al próximo stream.`;
  return data.entries;
}

function renderCaption(data) {
  overlay.textContent = fitCaption(data.translation || data.original);
  videoCaption.hidden = !overlay.textContent;
  clearTimeout(clearTimer);
  if (data.final !== false) clearTimer = setTimeout(() => { videoCaption.hidden = true; }, 6500);
}

async function loadSessions() {
  const response = await fetch("/api/sessions");
  const sessions = (await response.json()).sessions;
  const previous = sessionSelect.value;
  sessionSelect.innerHTML = "";
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = session.title || session.id;
    sessionSelect.append(option);
  }
  sessionSelect.value = sessions.some(item => item.id === previous) ? previous : "main-stage";
}

function connectEvents() {
  eventSource?.close();
  eventSource = new EventSource(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/events`);
  eventSource.addEventListener("caption", event => renderCaption(JSON.parse(event.data)));
}

function downsample(input, inputRate, outputRate = 16000) {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const result = new Float32Array(Math.round(input.length / ratio));
  for (let i = 0; i < result.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    result[i] = sum / Math.max(1, end - start);
  }
  return result;
}

function floatToPcm16(input) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const value = Math.max(-1, Math.min(1, input[i]));
    output[i] = value < 0 ? value * 0x8000 : value * 0x7fff;
  }
  return output.buffer;
}

function attachAudioProcessor() {
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = event => {
    if (!active || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(floatToPcm16(downsample(event.inputBuffer.getChannelData(0), audioContext.sampleRate)));
  };
  sourceNode.connect(processor);
  processor.connect(audioContext.destination);
}

function openInputSocket() {
  return new Promise((resolve, reject) => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const { source, target } = languages();
    socket = new WebSocket(`${protocol}://${location.host}/api/sessions/${encodeURIComponent(sessionSelect.value)}/input?source=${source}&target=${target}`);
    socket.onopen = () => resolve();
    socket.onerror = () => reject(new Error("No se pudo conectar la entrada"));
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === "stopped") mode.textContent = "LISTO";
    };
  });
}

function setActive(kind) {
  active = true;
  sourceKind = kind;
  sessionSelect.disabled = true;
  directionSelect.disabled = true;
  micButton.disabled = true;
  glossaryEntries.disabled = true;
  saveGlossaryButton.disabled = true;
  stopButton.disabled = false;
  mode.textContent = kind === "simulation" ? "STREAM · PREPARANDO" : "MICRÓFONO · EN VIVO";
}

function setIdle() {
  active = false;
  sourceKind = null;
  sessionSelect.disabled = false;
  directionSelect.disabled = false;
  micButton.disabled = false;
  glossaryEntries.disabled = false;
  saveGlossaryButton.disabled = false;
  stopButton.disabled = true;
  mode.textContent = "LISTO";
}

async function startMicrophone() {
  const { source, target } = languages();
  await saveGlossary();
  setActive("microphone");
  sourceStatus.textContent = `Micrófono conectado · ${source.toUpperCase()} → ${target.toUpperCase()}`;
  audioContext = new AudioContext();
  await audioContext.resume();
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  attachAudioProcessor();
  await openInputSocket();
}

async function startSimulation(file) {
  const { source, target } = languages();
  await saveGlossary();
  setActive("simulation");
  sourceStatus.textContent = `Subiendo y preparando ${file.name} · ${source.toUpperCase()} → ${target.toUpperCase()}`;
  const form = new FormData();
  form.append("file", file);
  form.append("source_language", source);
  form.append("target_language", target);
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/simulate`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await response.text());
  const simulation = await response.json();
  preview.src = `${simulation.media_url}?v=${Date.now()}`;
  placeholder.hidden = true;
  await new Promise((resolve, reject) => {
    preview.onloadedmetadata = resolve;
    preview.onerror = () => reject(new Error("El video no se pudo abrir"));
  });
  const delay = Math.max(0, simulation.starts_at * 1000 - Date.now());
  setTimeout(async () => {
    if (!active || sourceKind !== "simulation") return;
    await preview.play().catch(() => {});
    mode.textContent = "STREAM · EN VIVO";
    sourceStatus.textContent = `Señal activa · ${source.toUpperCase()} → ${target.toUpperCase()}`;
  }, delay);
  preview.onended = () => {
    sourceStatus.textContent = "La señal terminó · SRT, VTT y TXT listos para descargar.";
    setIdle();
  };
}

async function stopSource() {
  if (!active) return;
  const kind = sourceKind;
  active = false;
  if (kind === "simulation") {
    preview.pause();
    await fetch(`/api/sessions/${encodeURIComponent(sessionSelect.value)}/stop`, { method: "POST" });
  }
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "stop" }));
  mediaStream?.getTracks().forEach(track => track.stop());
  sourceNode?.disconnect();
  processor?.disconnect();
  await audioContext?.close();
  audioContext = null;
  mediaStream = null;
  sourceNode = null;
  processor = null;
  sourceStatus.textContent = "Fuente detenida · SRT, VTT y TXT listos para descargar.";
  setIdle();
}

micButton.addEventListener("click", () => startMicrophone().catch(error => {
  sourceStatus.textContent = error.message;
  stopSource();
}));
streamInput.addEventListener("change", () => {
  const file = streamInput.files[0];
  if (file) startSimulation(file).catch(error => {
    sourceStatus.textContent = error.message;
    stopSource();
  });
  streamInput.value = "";
});
stopButton.addEventListener("click", stopSource);
saveGlossaryButton.addEventListener("click", () => saveGlossary().catch(error => {
  glossaryStatus.textContent = error.message;
}));
sessionSelect.addEventListener("change", () => {
  connectEvents();
  updateExportLinks();
  loadGlossary().catch(error => { glossaryStatus.textContent = error.message; });
});
directionSelect.addEventListener("change", () => {
  updateExportLinks();
  loadGlossary().catch(error => { glossaryStatus.textContent = error.message; });
});
exportLanguage.addEventListener("change", updateExportLinks);

async function bootstrap() {
  await loadSessions();
  connectEvents();
  updateExportLinks();
  await loadGlossary();
  const response = await fetch("/api/health");
  const data = await response.json();
  health.textContent = data.ok ? "Servicios conectados" : "Servicios degradados";
  health.classList.toggle("ok", data.ok);
}

bootstrap().catch(error => { health.textContent = error.message; });
