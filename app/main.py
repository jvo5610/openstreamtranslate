from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as redis
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from .pipeline import CaptionPipeline, normalize_audio, pcm16_to_wav


STATIC = Path(__file__).parent / "static"
SIMULATOR_DIR = Path("/tmp/vibeathon-live-simulator")
UPDATE_SECONDS = float(os.getenv("LIVE_UPDATE_SECONDS", "1.5"))
FINAL_SECONDS = float(os.getenv("LIVE_FINAL_SECONDS", "3"))
MAX_FINAL_SECONDS = float(os.getenv("LIVE_MAX_FINAL_SECONDS", "4.5"))
OVERLAP_SECONDS = float(os.getenv("LIVE_OVERLAP_SECONDS", "0.75"))
SIMULATOR_START_DELAY_SECONDS = float(os.getenv("SIMULATOR_START_DELAY_SECONDS", "2"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2
SESSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DEFAULT_SESSIONS = {
    "main-stage": "Main Stage",
    "data-stage": "Data & AI",
    "community-stage": "Community Stage",
}
SUPPORTED_LANGUAGES = {"en", "es"}
DEFAULT_GLOSSARY_TERMS = (
    "Nerdearla",
    "Kubernetes",
    "PostgreSQL",
    "Postgres",
    "CloudNativePG",
    "KubeRay",
    "OpenRouter",
    "TranslateGemma",
    "DevOps",
    "GitHub Copilot",
    "Docker",
    "Redis",
    "WebSocket",
    "SSE",
    "Kafka",
)
LOGGER = logging.getLogger("vibeathon.events")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(log_handler)
LOGGER.propagate = False
CAPTIONS = Counter("vibeathon_captions_total", "Caption events", ["source", "target", "final"])
ACTIVE_SSE = Gauge("vibeathon_sse_connections", "Active audience SSE connections")
ACTIVE_STREAMS = Gauge("vibeathon_active_streams", "Active audio sources")
MODEL_LATENCY = Histogram(
    "vibeathon_model_latency_seconds",
    "Combined ASR and translation latency",
    ["source", "target"],
    buckets=(0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10),
)
CAPTION_LAG = Histogram(
    "vibeathon_caption_lag_seconds",
    "Elapsed live-stream time beyond the caption audio end",
    ["source", "target"],
    buckets=(0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 7, 10),
)
SKIPPED_UPDATES = Counter(
    "vibeathon_skipped_caption_updates_total",
    "Obsolete interim hypotheses skipped to keep a stream near real time",
)
BROKER_PUBLISH = Histogram(
    "vibeathon_broker_publish_seconds",
    "Redis history and fan-out publish latency",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)
SIMULATIONS = Counter("vibeathon_simulations_total", "Server-side stream simulations", ["source", "target"])


def log_event(event: str, **fields: object) -> None:
    LOGGER.info(json.dumps({"event": event, "timestamp": time.time(), **fields}, ensure_ascii=False))


class DisconnectAwareStreamingResponse(StreamingResponse):
    """Run SSE cleanup as soon as ASGI reports that the client disconnected."""

    async def __call__(self, scope, receive, send) -> None:
        stream_task = asyncio.create_task(self.stream_response(send))
        disconnect_task = asyncio.create_task(self.listen_for_disconnect(receive))
        tasks = {stream_task, disconnect_task}
        error: BaseException | None = None
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    task.result()
                except (asyncio.CancelledError, OSError):
                    pass
                except BaseException as exc:
                    error = exc
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.background is not None:
                await self.background()
        if error is not None:
            raise error


def require_language_pair(source_language: str, target_language: str) -> tuple[str, str]:
    if source_language not in SUPPORTED_LANGUAGES or target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Supported languages are en and es")
    if source_language == target_language:
        raise HTTPException(status_code=422, detail="Source and target languages must differ")
    return source_language, target_language


class ExternalCaption(BaseModel):
    original: str = Field(min_length=1, max_length=4000)
    translation: str = Field(min_length=1, max_length=4000)
    source_language: str = "en"
    target_language: str = "es"
    final: bool = True
    sequence: int = Field(default=1, ge=1)
    audio_start_seconds: float = Field(default=0, ge=0)
    audio_end_seconds: float = Field(default=0, ge=0)
    latency: dict[str, float] = Field(default_factory=dict)


class GlossaryEntry(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(default="", max_length=100)


class SessionGlossary(BaseModel):
    source_language: str = "en"
    target_language: str = "es"
    entries: list[GlossaryEntry] = Field(default_factory=list, max_length=100)


def default_glossary(source_language: str, target_language: str) -> list[dict[str, str]]:
    return [{"source": term, "target": term} for term in DEFAULT_GLOSSARY_TERMS]


def normalize_glossary(entries: list[GlossaryEntry]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        source = " ".join(entry.source.split())
        target = " ".join((entry.target or source).split())
        key = source.casefold()
        if not source or key in seen:
            continue
        seen.add(key)
        normalized.append({"source": source, "target": target})
    return normalized


def subtitle_timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def transcript_text(events: list[dict], language: str, output_format: str) -> str:
    cues: list[tuple[float, float, str]] = []
    for event in events:
        if not event.get("final"):
            continue
        source_language = str(event.get("source_language", event.get("language", "")))
        target_language = str(event.get("target_language", ""))
        if language == source_language:
            text = str(event.get("original", "")).strip()
        elif language == target_language:
            text = str(event.get("translation", "")).strip()
        else:
            continue
        if not text:
            continue
        start = float(event.get("audio_start_seconds", 0) or 0)
        end = float(event.get("audio_end_seconds", start + 2) or start + 2)
        cues.append((start, max(start + 0.25, end), text))

    if output_format == "txt":
        return "\n".join(text for _, _, text in cues) + ("\n" if cues else "")

    separator = "." if output_format == "vtt" else ","
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        timing = f"{subtitle_timestamp(start, separator)} --> {subtitle_timestamp(end, separator)}"
        blocks.append(f"{timing}\n{text}" if output_format == "vtt" else f"{index}\n{timing}\n{text}")
    prefix = "WEBVTT\n\n" if output_format == "vtt" else ""
    return prefix + "\n\n".join(blocks) + ("\n" if blocks else "")


def require_session_id(session_id: str) -> str:
    if not SESSION_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="Invalid session id")
    return session_id


class SessionBroker:
    """Durable caption history plus low-latency fan-out across app replicas."""

    def __init__(self, url: str) -> None:
        self.redis = redis.from_url(url, decode_responses=True)

    @staticmethod
    def state_key(session_id: str) -> str:
        return f"session:{session_id}:state"

    @staticmethod
    def history_key(session_id: str) -> str:
        return f"session:{session_id}:captions"

    @staticmethod
    def channel(session_id: str) -> str:
        return f"session:{session_id}:live"

    @staticmethod
    def glossary_key(session_id: str, source_language: str, target_language: str) -> str:
        return f"session:{session_id}:glossary:{source_language}:{target_language}"

    async def initialize(self) -> None:
        await self.redis.ping()
        for session_id, title in DEFAULT_SESSIONS.items():
            await self.redis.sadd("sessions", session_id)
            await self.redis.hsetnx(self.state_key(session_id), "title", title)
            await self.redis.hsetnx(self.state_key(session_id), "status", "idle")
            await self.redis.hdel(self.state_key(session_id), "viewers")

    async def close(self) -> None:
        await self.redis.aclose()

    async def health(self) -> dict:
        try:
            return {"ok": bool(await self.redis.ping()), "status": "ok"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def set_state(self, session_id: str, **values: object) -> None:
        await self.redis.sadd("sessions", session_id)
        mapping = {key: str(value) for key, value in values.items() if value is not None}
        mapping["updated_at"] = str(time.time())
        await self.redis.hset(self.state_key(session_id), mapping=mapping)

    async def reset_captions(self, session_id: str) -> None:
        await self.redis.delete(self.history_key(session_id))
        await self.redis.hdel(self.state_key(session_id), "last_caption", "sequence", "ended_at")

    async def state_value(self, session_id: str, key: str) -> str | None:
        return await self.redis.hget(self.state_key(session_id), key)

    async def get_glossary(
        self,
        session_id: str,
        source_language: str,
        target_language: str,
    ) -> list[dict[str, str]]:
        encoded = await self.redis.get(self.glossary_key(session_id, source_language, target_language))
        if not encoded:
            return default_glossary(source_language, target_language)
        try:
            entries = json.loads(encoded)
        except (json.JSONDecodeError, TypeError):
            log_event(
                "glossary_invalid",
                session_id=session_id,
                source_language=source_language,
                target_language=target_language,
            )
            return default_glossary(source_language, target_language)
        return entries if isinstance(entries, list) else default_glossary(source_language, target_language)

    async def set_glossary(
        self,
        session_id: str,
        source_language: str,
        target_language: str,
        entries: list[dict[str, str]],
    ) -> None:
        await self.redis.set(
            self.glossary_key(session_id, source_language, target_language),
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
        )

    async def delete_session(self, session_id: str) -> None:
        await self.redis.srem("sessions", session_id)
        glossary_keys = [
            self.glossary_key(session_id, source, target)
            for source in SUPPORTED_LANGUAGES
            for target in SUPPORTED_LANGUAGES
            if source != target
        ]
        await self.redis.delete(self.state_key(session_id), self.history_key(session_id), *glossary_keys)

    async def list_sessions(self) -> list[dict]:
        session_ids = sorted(await self.redis.smembers("sessions"))
        sessions: list[dict] = []
        for session_id in session_ids:
            state = await self.redis.hgetall(self.state_key(session_id))
            parsed: dict[str, object] = {"id": session_id, **state}
            parsed.pop("viewers", None)
            for key in ("sequence",):
                if key in parsed:
                    try:
                        parsed[key] = int(str(parsed[key]))
                    except ValueError:
                        parsed[key] = 0
            for key in ("started_at", "updated_at", "ended_at"):
                if key in parsed:
                    try:
                        parsed[key] = float(str(parsed[key]))
                    except ValueError:
                        parsed.pop(key, None)
            parsed.pop("media_path", None)
            sessions.append(parsed)
        return sessions

    async def publish(self, session_id: str, payload: dict) -> dict:
        publish_started = time.perf_counter()
        measured_payload = {**payload, "published_at": time.time()}
        encoded_history = json.dumps(measured_payload, ensure_ascii=False, separators=(",", ":"))
        event_id = await self.redis.xadd(
            self.history_key(session_id),
            {"data": encoded_history},
            maxlen=2000,
            approximate=True,
        )
        event = {**measured_payload, "event_id": event_id, "session_id": session_id}
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        await self.redis.hset(
            self.state_key(session_id),
            mapping={
                "status": "live",
                "sequence": payload.get("sequence", 0),
                "last_caption": encoded,
                "updated_at": time.time(),
            },
        )
        await self.redis.publish(self.channel(session_id), encoded)
        publish_seconds = time.perf_counter() - publish_started
        BROKER_PUBLISH.observe(publish_seconds)
        source = str(payload.get("source_language", payload.get("language", "unknown")))
        target = str(payload.get("target_language", "unknown"))
        CAPTIONS.labels(source=source, target=target, final=str(bool(payload.get("final"))).lower()).inc()
        if payload.get("latency", {}).get("total") is not None:
            MODEL_LATENCY.labels(source=source, target=target).observe(float(payload["latency"]["total"]))
        if payload.get("latency", {}).get("caption_lag") is not None:
            CAPTION_LAG.labels(source=source, target=target).observe(float(payload["latency"]["caption_lag"]))
        log_event(
            "caption_published",
            session_id=session_id,
            sequence=payload.get("sequence"),
            final=payload.get("final"),
            source_language=source,
            target_language=target,
            model_seconds=payload.get("latency", {}).get("total"),
            caption_lag_seconds=payload.get("latency", {}).get("caption_lag"),
            broker_publish_ms=round(publish_seconds * 1000, 2),
        )
        return event

    async def subscribe(self, session_id: str, last_event_id: str | None) -> AsyncIterator[dict | None]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel(session_id))
        try:
            if last_event_id:
                records = await self.redis.xread(
                    {self.history_key(session_id): last_event_id},
                    count=200,
                )
                for _, entries in records:
                    for event_id, fields in entries:
                        event = json.loads(fields["data"])
                        yield {**event, "event_id": event_id, "session_id": session_id}
            else:
                latest = await self.redis.hget(self.state_key(session_id), "last_caption")
                if latest:
                    yield json.loads(latest)

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if message and message.get("type") == "message":
                    yield json.loads(message["data"])
                else:
                    yield None
        finally:
            await pubsub.unsubscribe(self.channel(session_id))
            await pubsub.aclose()

    async def replay(self, session_id: str, last_event_id: str | None) -> list[dict]:
        if last_event_id:
            records = await self.redis.xread(
                {self.history_key(session_id): last_event_id},
                count=200,
            )
            return [
                {**json.loads(fields["data"]), "event_id": event_id, "session_id": session_id}
                for _, entries in records
                for event_id, fields in entries
            ]
        status = await self.redis.hget(self.state_key(session_id), "status")
        if status != "live":
            return []
        latest = await self.redis.hget(self.state_key(session_id), "last_caption")
        return [json.loads(latest)] if latest else []

    async def transcript(self, session_id: str) -> list[dict]:
        records = await self.redis.xrange(self.history_key(session_id), count=2000)
        return [json.loads(fields["data"]) for _, fields in records]

    async def pump_live(
        self,
        session_id: str,
        ready: asyncio.Event,
        callback: CaptionCallback,
    ) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel(session_id))
        ready.set()
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if message and message.get("type") == "message":
                    await callback(json.loads(message["data"]))
        finally:
            await pubsub.unsubscribe(self.channel(session_id))
            await pubsub.aclose()

CaptionCallback = Callable[[dict], Awaitable[None]]


class LocalSessionFanout:
    """One Redis subscription per session, fanned out to local SSE clients."""

    def __init__(self, broker: SessionBroker) -> None:
        self.broker = broker
        self.queues: dict[str, set[asyncio.Queue]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.ready: dict[str, asyncio.Event] = {}
        self.lock = asyncio.Lock()

    async def add(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        async with self.lock:
            self.queues.setdefault(session_id, set()).add(queue)
            task = self.tasks.get(session_id)
            if not task or task.done():
                ready = asyncio.Event()
                self.ready[session_id] = ready
                self.tasks[session_id] = asyncio.create_task(self._pump(session_id, ready))
            ready = self.ready[session_id]
        await ready.wait()
        return queue

    async def remove(self, session_id: str, queue: asyncio.Queue) -> None:
        task: asyncio.Task | None = None
        async with self.lock:
            session_queues = self.queues.get(session_id)
            if session_queues:
                session_queues.discard(queue)
                if not session_queues:
                    self.queues.pop(session_id, None)
                    task = self.tasks.pop(session_id, None)
                    self.ready.pop(session_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _pump(self, session_id: str, ready: asyncio.Event) -> None:
        async def distribute(event: dict) -> None:
            for queue in tuple(self.queues.get(session_id, ())):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(event)

        await self.broker.pump_live(session_id, ready, distribute)

    async def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.queues.clear()


class LiveSessionProcessor:
    """Turns a real-time PCM stream into stable caption events."""

    def __init__(
        self,
        pipeline: CaptionPipeline,
        callback: CaptionCallback,
        source_language: str = "en",
        target_language: str = "es",
        glossary: list[dict[str, str]] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.callback = callback
        self.source_language = source_language
        self.target_language = target_language
        self.glossary = glossary or []
        self.buffer = bytearray()
        self.sequence = 0
        self.context = "Technical conference about AI, LLMs, Kubernetes, infrastructure, GitHub Copilot and open source."
        if self.glossary:
            expected_terms = ", ".join(entry["source"] for entry in self.glossary)
            self.context = f"{self.context} Expected terminology: {expected_terms}."
        self.audio_ready = asyncio.Event()
        self.stopped = False
        self.group_start = 0
        self.next_emit = int(UPDATE_SECONDS * BYTES_PER_SECOND)
        self.updates_per_group = max(1, round(FINAL_SECONDS / UPDATE_SECONDS))
        self.max_updates_per_group = max(self.updates_per_group, round(MAX_FINAL_SECONDS / UPDATE_SECONDS))
        self.group_updates = 0
        self.last_processed_end = 0
        self.last_caption: dict | None = None
        self.task: asyncio.Task | None = None
        self.started_at_monotonic = 0.0

    async def start(self) -> None:
        self.started_at_monotonic = time.monotonic()
        self.task = asyncio.create_task(self._process_audio())

    async def feed(self, pcm: bytes) -> None:
        self.buffer.extend(pcm)
        self.audio_ready.set()

    async def finish(self) -> None:
        self.stopped = True
        self.audio_ready.set()
        if self.task:
            await self.task

    async def abort(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _emit_chunk(
        self,
        pcm: bytes,
        final_candidate: bool,
        force_final: bool = False,
        start_seconds: float = 0,
        end_seconds: float = 0,
    ) -> bool:
        if len(pcm) < BYTES_PER_SECOND // 2:
            return False
        result = await self.pipeline.process(
            pcm16_to_wav(pcm),
            f"live-{self.sequence}.wav",
            self.context[-700:],
            self.source_language,
            self.target_language,
            self.glossary,
        )
        text = result["original"].rstrip()
        if not text:
            return False
        has_stable_ending = text.endswith((".", "?", "!")) and not text.endswith("...")
        final = final_candidate and (has_stable_ending or force_final)
        if final:
            self.context = f"{self.context} {text}"
        caption_lag = max(0.0, time.monotonic() - self.started_at_monotonic - end_seconds)
        self.sequence += 1
        self.last_caption = {
            "type": "caption",
            "sequence": self.sequence,
            "final": final,
            "audio_start_seconds": round(start_seconds, 3),
            "audio_end_seconds": round(end_seconds, 3),
            **result,
            "latency": {
                **result.get("latency", {}),
                "caption_lag": round(caption_lag, 3),
            },
        }
        await self.callback(self.last_caption)
        return final

    async def _process_audio(self) -> None:
        while True:
            await self.audio_ready.wait()
            self.audio_ready.clear()

            while len(self.buffer) >= self.next_emit:
                update_bytes = int(UPDATE_SECONDS * BYTES_PER_SECOND)
                available_updates = max(1, (len(self.buffer) - self.group_start) // update_bytes)
                end = self.group_start + available_updates * update_bytes
                skipped_updates = max(0, (end - self.next_emit) // update_bytes)
                if skipped_updates:
                    SKIPPED_UPDATES.inc(skipped_updates)
                    log_event(
                        "caption_updates_skipped",
                        count=skipped_updates,
                        buffered_seconds=round(len(self.buffer) / BYTES_PER_SECOND, 3),
                        next_audio_end_seconds=round(end / BYTES_PER_SECOND, 3),
                    )
                self.group_updates = available_updates
                final_candidate = self.group_updates >= self.updates_per_group
                force_final = self.group_updates >= self.max_updates_per_group
                final = await self._emit_chunk(
                    bytes(self.buffer[self.group_start:end]),
                    final_candidate,
                    force_final,
                    self.group_start / BYTES_PER_SECOND,
                    end / BYTES_PER_SECOND,
                )
                self.last_processed_end = end
                if final:
                    overlap = int(OVERLAP_SECONDS * BYTES_PER_SECOND)
                    self.group_start = max(0, end - overlap)
                    self.group_updates = 0
                    # Keep commit points on the live clock. The overlap is context,
                    # not a reason to emit the next caption earlier.
                    self.next_emit = end + update_bytes
                else:
                    self.next_emit = end + update_bytes

            if self.stopped:
                if len(self.buffer) > self.last_processed_end + BYTES_PER_SECOND // 2:
                    await self._emit_chunk(
                        bytes(self.buffer[self.group_start:]),
                        True,
                        True,
                        self.group_start / BYTES_PER_SECOND,
                        len(self.buffer) / BYTES_PER_SECOND,
                    )
                elif self.last_caption and not self.last_caption["final"]:
                    self.sequence += 1
                    self.last_caption = {**self.last_caption, "sequence": self.sequence, "final": True}
                    await self.callback(self.last_caption)
                return


async def run_simulator(
    app: FastAPI,
    session_id: str,
    media_path: Path,
    starts_at: float,
    source_language: str,
    target_language: str,
    glossary: list[dict[str, str]],
) -> None:
    processor: LiveSessionProcessor | None = None
    ffmpeg: asyncio.subprocess.Process | None = None
    stream_counted = False
    try:
        await asyncio.sleep(max(0, starts_at - time.time()))
        await app.state.broker.set_state(session_id, status="live", started_at=starts_at)
        ACTIVE_STREAMS.inc()
        stream_counted = True
        log_event(
            "simulation_started",
            session_id=session_id,
            source_language=source_language,
            target_language=target_language,
            glossary_terms=len(glossary),
        )

        async def publish(caption: dict) -> None:
            await app.state.broker.publish(session_id, caption)

        processor = LiveSessionProcessor(
            app.state.pipeline,
            publish,
            source_language,
            target_language,
            glossary,
        )
        await processor.start()
        ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert ffmpeg.stdout is not None
        while chunk := await ffmpeg.stdout.read(BYTES_PER_SECOND // 4):
            await processor.feed(chunk)
        await ffmpeg.wait()
        await processor.finish()
        await app.state.broker.set_state(session_id, status="ended", ended_at=time.time())
        log_event("simulation_ended", session_id=session_id)
    except asyncio.CancelledError:
        if ffmpeg and ffmpeg.returncode is None:
            ffmpeg.terminate()
            await ffmpeg.wait()
        if processor:
            await processor.abort()
        await app.state.broker.set_state(session_id, status="stopped", ended_at=time.time())
        raise
    except Exception as exc:
        if processor:
            await processor.abort()
        await app.state.broker.set_state(session_id, status="error", error=str(exc))
        log_event("simulation_error", session_id=session_id, error=str(exc))
    finally:
        if stream_counted:
            ACTIVE_STREAMS.dec()


@asynccontextmanager
async def lifespan(app: FastAPI):
    SIMULATOR_DIR.mkdir(parents=True, exist_ok=True)
    app.state.pipeline = CaptionPipeline()
    app.state.broker = SessionBroker(REDIS_URL)
    app.state.simulation_tasks: dict[str, asyncio.Task] = {}
    app.state.media_paths: dict[str, Path] = {}
    await app.state.broker.initialize()
    app.state.fanout = LocalSessionFanout(app.state.broker)
    yield
    for task in app.state.simulation_tasks.values():
        task.cancel()
    await asyncio.gather(*app.state.simulation_tasks.values(), return_exceptions=True)
    await app.state.fanout.close()
    await app.state.pipeline.close()
    await app.state.broker.close()


app = FastAPI(title="Vibeathon Live Captions", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "watch.html")


@app.get("/studio")
async def studio():
    return FileResponse(STATIC / "index.html")


@app.get("/watch")
async def watch():
    return FileResponse(STATIC / "watch.html")


@app.get("/embed/{session_id}")
async def embed(session_id: str):
    require_session_id(session_id)
    return FileResponse(STATIC / "embed.html")


@app.get("/api/health")
async def health():
    result = await app.state.pipeline.health()
    result["broker"] = await app.state.broker.health()
    result["ok"] = result["ok"] and result["broker"]["ok"]
    return JSONResponse(result, status_code=200 if result["ok"] else 503)


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/sessions")
async def sessions():
    return {"sessions": await app.state.broker.list_sessions()}


@app.get("/api/sessions/{session_id}/glossary")
async def get_session_glossary(
    session_id: str,
    source_language: str = "en",
    target_language: str = "es",
):
    require_session_id(session_id)
    require_language_pair(source_language, target_language)
    entries = await app.state.broker.get_glossary(session_id, source_language, target_language)
    return {
        "session_id": session_id,
        "source_language": source_language,
        "target_language": target_language,
        "entries": entries,
    }


@app.put("/api/sessions/{session_id}/glossary")
async def put_session_glossary(session_id: str, glossary: SessionGlossary):
    require_session_id(session_id)
    require_language_pair(glossary.source_language, glossary.target_language)
    entries = normalize_glossary(glossary.entries)
    await app.state.broker.set_glossary(
        session_id,
        glossary.source_language,
        glossary.target_language,
        entries,
    )
    log_event(
        "glossary_updated",
        session_id=session_id,
        source_language=glossary.source_language,
        target_language=glossary.target_language,
        glossary_terms=len(entries),
    )
    return {
        "session_id": session_id,
        "source_language": glossary.source_language,
        "target_language": glossary.target_language,
        "entries": entries,
    }


@app.post("/api/sessions/{session_id}/captions")
async def publish_external_caption(session_id: str, caption: ExternalCaption):
    require_session_id(session_id)
    require_language_pair(caption.source_language, caption.target_language)
    payload = {
        "type": "caption",
        "language": caption.source_language,
        **caption.model_dump(),
    }
    event = await app.state.broker.publish(session_id, payload)
    await app.state.broker.set_state(
        session_id,
        status="live",
        source="external-caption-api",
        source_language=caption.source_language,
        target_language=caption.target_language,
    )
    return event


@app.get("/api/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    require_session_id(session_id)

    ACTIVE_SSE.inc()
    queue: asyncio.Queue | None = None
    try:
        queue = await app.state.fanout.add(session_id)
        replay = await app.state.broker.replay(session_id, last_event_id)
    except BaseException:
        ACTIVE_SSE.dec()
        if queue is not None:
            await app.state.fanout.remove(session_id, queue)
        raise

    async def stream() -> AsyncIterator[str]:
        seen_event_ids: set[str] = set()
        for event in replay:
            event_id = event.get("event_id", "")
            seen_event_ids.add(event_id)
            data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {event_id}\nevent: caption\ndata: {data}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            event_id = event.get("event_id", "")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            if len(seen_event_ids) > 500:
                seen_event_ids.pop()
            data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {event_id}\nevent: caption\ndata: {data}\n\n"

    async def cleanup() -> None:
        ACTIVE_SSE.dec()
        await app.state.fanout.remove(session_id, queue)

    return DisconnectAwareStreamingResponse(
        stream(),
        media_type="text/event-stream",
        background=BackgroundTask(cleanup),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/sessions/{session_id}/transcript/{output_format}")
async def export_transcript(session_id: str, output_format: str, language: str = "es"):
    require_session_id(session_id)
    if output_format not in {"srt", "vtt", "txt"}:
        raise HTTPException(status_code=422, detail="Supported transcript formats are srt, vtt and txt")
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Supported transcript languages are en and es")
    events = await app.state.broker.transcript(session_id)
    content = transcript_text(events, language, output_format)
    media_types = {
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
    }
    return Response(
        content,
        media_type=media_types[output_format],
        headers={"Content-Disposition": f'attachment; filename="{session_id}-{language}.{output_format}"'},
    )


@app.get("/api/sessions/{session_id}/media")
async def session_media(session_id: str):
    require_session_id(session_id)
    media_path = app.state.media_paths.get(session_id)
    if not media_path:
        stored_path = await app.state.broker.state_value(session_id, "media_path")
        if stored_path:
            media_path = Path(stored_path)
    if not media_path or not media_path.exists():
        raise HTTPException(status_code=404, detail="This session has no simulated stream")
    return FileResponse(media_path)


@app.post("/api/sessions/{session_id}/simulate")
async def simulate_stream(
    session_id: str,
    file: UploadFile = File(...),
    source_language: str = Form("en"),
    target_language: str = Form("es"),
):
    require_session_id(session_id)
    require_language_pair(source_language, target_language)
    existing = app.state.simulation_tasks.get(session_id)
    if existing and not existing.done():
        existing.cancel()
        await asyncio.gather(existing, return_exceptions=True)

    previous_media = app.state.media_paths.get(session_id)
    if not previous_media:
        stored_path = await app.state.broker.state_value(session_id, "media_path")
        if stored_path:
            previous_media = Path(stored_path)
    if previous_media and previous_media.exists():
        previous_media.unlink()

    suffix = Path(file.filename or "stream.webm").suffix.lower()
    if suffix not in {".webm", ".mp4", ".mov", ".mkv", ".mp3", ".wav", ".ogg"}:
        suffix = ".bin"
    media_path = SIMULATOR_DIR / f"{session_id}-{uuid.uuid4().hex}{suffix}"
    with media_path.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            target.write(chunk)
    app.state.media_paths[session_id] = media_path

    starts_at = time.time() + SIMULATOR_START_DELAY_SECONDS
    media_url = f"/api/sessions/{session_id}/media"
    await app.state.broker.reset_captions(session_id)
    await app.state.broker.set_state(
        session_id,
        title=DEFAULT_SESSIONS.get(session_id, session_id.replace("-", " ").title()),
        status="starting",
        started_at=starts_at,
        media_url=media_url,
        media_path=media_path,
        source_language=source_language,
        target_language=target_language,
        error="",
    )
    SIMULATIONS.labels(source=source_language, target=target_language).inc()
    glossary = await app.state.broker.get_glossary(session_id, source_language, target_language)
    task = asyncio.create_task(
        run_simulator(
            app,
            session_id,
            media_path,
            starts_at,
            source_language,
            target_language,
            glossary,
        )
    )
    app.state.simulation_tasks[session_id] = task
    return {
        "session_id": session_id,
        "status": "starting",
        "starts_at": starts_at,
        "media_url": media_url,
        "events_url": f"/api/sessions/{session_id}/events",
        "source_language": source_language,
        "target_language": target_language,
        "glossary_terms": len(glossary),
    }


@app.post("/api/sessions/{session_id}/stop")
async def stop_simulation(session_id: str):
    require_session_id(session_id)
    task = app.state.simulation_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await app.state.broker.set_state(session_id, status="stopped", ended_at=time.time())
    return {"session_id": session_id, "status": "stopped"}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    require_session_id(session_id)
    if session_id in DEFAULT_SESSIONS:
        raise HTTPException(status_code=409, detail="Default sessions cannot be deleted")
    task = app.state.simulation_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    media_path = app.state.media_paths.pop(session_id, None)
    if media_path and media_path.exists():
        media_path.unlink()
    await app.state.broker.delete_session(session_id)
    return {"deleted": session_id}


@app.post("/api/process")
async def process_file(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    source_language: str = Form("en"),
    target_language: str = Form("es"),
):
    require_language_pair(source_language, target_language)
    payload = await file.read()
    normalized = await normalize_audio(payload)
    return await app.state.pipeline.process(
        normalized,
        "normalized.wav",
        prompt,
        source_language,
        target_language,
    )


@app.websocket("/api/sessions/{session_id}/input")
async def session_input(websocket: WebSocket, session_id: str):
    if not SESSION_PATTERN.fullmatch(session_id):
        await websocket.close(code=1008, reason="Invalid session id")
        return
    source_language = websocket.query_params.get("source", "en")
    target_language = websocket.query_params.get("target", "es")
    if source_language not in SUPPORTED_LANGUAGES or target_language not in SUPPORTED_LANGUAGES or source_language == target_language:
        await websocket.close(code=1008, reason="Supported language pairs are en-es and es-en")
        return
    await websocket.accept()
    await app.state.broker.reset_captions(session_id)
    await app.state.broker.set_state(
        session_id,
        status="live",
        started_at=time.time(),
        source="websocket",
        source_language=source_language,
        target_language=target_language,
    )

    async def publish(caption: dict) -> None:
        await app.state.broker.publish(session_id, caption)

    glossary = await app.state.broker.get_glossary(session_id, source_language, target_language)
    processor = LiveSessionProcessor(
        app.state.pipeline,
        publish,
        source_language,
        target_language,
        glossary,
    )
    await processor.start()
    ACTIVE_STREAMS.inc()
    log_event(
        "input_connected",
        session_id=session_id,
        source_language=source_language,
        target_language=target_language,
    )
    await websocket.send_json({"type": "ready", "session_id": session_id})
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await processor.feed(message["bytes"])
            elif message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "stop":
                    await processor.finish()
                    await app.state.broker.set_state(session_id, status="ended", ended_at=time.time())
                    await websocket.send_json({"type": "stopped", "session_id": session_id})
                    log_event("input_ended", session_id=session_id)
                    return
    except WebSocketDisconnect:
        await processor.abort()
        await app.state.broker.set_state(session_id, status="disconnected", ended_at=time.time())
        log_event("input_disconnected", session_id=session_id)
    finally:
        ACTIVE_STREAMS.dec()


@app.websocket("/api/live")
async def legacy_live(websocket: WebSocket):
    """Compatibility endpoint used by the low-level concurrent inference check."""
    await websocket.accept()

    async def echo(caption: dict) -> None:
        await websocket.send_json(caption)

    processor = LiveSessionProcessor(app.state.pipeline, echo)
    await processor.start()
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await processor.feed(message["bytes"])
            elif message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "stop":
                    await processor.finish()
                    await websocket.send_json({"type": "stopped"})
                    return
    except WebSocketDisconnect:
        await processor.abort()
