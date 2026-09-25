#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import websockets


@dataclass(frozen=True)
class StreamCase:
    session_id: str
    sample: Path
    source: str
    target: str


def decode_pcm(path: Path, seconds: float) -> bytes:
    return subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-t", str(seconds), "-vn",
        "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
    ])


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


async def watch(
    client: httpx.AsyncClient,
    base_url: str,
    case: StreamCase,
    index: int,
    ready: asyncio.Event,
    ready_count: list[int],
    ready_lock: asyncio.Lock,
    total_viewers: int,
    started_at: list[float],
) -> dict:
    result = {
        "viewer": index,
        "session_id": case.session_id,
        "event_id": None,
        "first_caption_seconds": None,
        "delivery_ms": None,
        "original": "",
        "translation": "",
        "valid": False,
        "error": None,
    }
    try:
        async with client.stream(
            "GET",
            f"{base_url}/api/sessions/{case.session_id}/events",
        ) as response:
            response.raise_for_status()
            async with ready_lock:
                ready_count[0] += 1
                if ready_count[0] == total_viewers:
                    ready.set()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                original = event.get("original", "").strip()
                translation = event.get("translation", "").strip()
                result.update({
                    "event_id": event.get("event_id"),
                    "first_caption_seconds": round(time.perf_counter() - started_at[0], 3),
                    "delivery_ms": round(
                        max(0, time.time() - float(event.get("published_at", time.time()))) * 1000,
                        2,
                    ),
                    "original": original,
                    "translation": translation,
                    "valid": (
                        event.get("session_id") == case.session_id
                        and event.get("source_language") == case.source
                        and event.get("target_language") == case.target
                        and bool(original)
                        and bool(translation)
                    ),
                })
                return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def publish(socket, pcm: bytes) -> None:
    bytes_per_quarter_second = 16000 * 2 // 4
    for offset in range(0, len(pcm), bytes_per_quarter_second):
        await socket.send(pcm[offset:offset + bytes_per_quarter_second])
        await asyncio.sleep(0.25)
    await socket.send(json.dumps({"type": "stop"}))
    while True:
        message = json.loads(await socket.recv())
        if message.get("type") == "stopped":
            return


async def run(args: argparse.Namespace) -> dict:
    suffix = str(int(time.time() * 1000))[-7:]
    cases = [
        StreamCase(f"bilingual-en-es-{suffix}", args.english_sample, "en", "es"),
        StreamCase(f"bilingual-es-en-{suffix}", args.spanish_sample, "es", "en"),
    ]
    audio = {case.session_id: decode_pcm(case.sample, args.audio_seconds) for case in cases}
    total_viewers = len(cases) * args.viewers_per_stream
    ready = asyncio.Event()
    ready_count = [0]
    ready_lock = asyncio.Lock()
    started_at = [time.perf_counter()]
    sockets = []
    limits = httpx.Limits(max_connections=total_viewers + 10, max_keepalive_connections=10)
    timeout = httpx.Timeout(args.timeout, connect=10, pool=10)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        try:
            for case in cases:
                socket = await websockets.connect(
                    f"{args.ws_base}/api/sessions/{case.session_id}/input"
                    f"?source={case.source}&target={case.target}",
                    max_size=2**22,
                )
                ready_message = json.loads(await socket.recv())
                if ready_message.get("type") != "ready":
                    raise RuntimeError(f"Unexpected WebSocket response: {ready_message}")
                sockets.append(socket)

            watchers = [
                asyncio.create_task(watch(
                    client,
                    args.base_url,
                    case,
                    index + 1,
                    ready,
                    ready_count,
                    ready_lock,
                    total_viewers,
                    started_at,
                ))
                for case in cases
                for index in range(args.viewers_per_stream)
            ]
            await asyncio.wait_for(ready.wait(), timeout=10)
            started_at[0] = time.perf_counter()
            publishers = [
                publish(socket, audio[case.session_id])
                for socket, case in zip(sockets, cases, strict=True)
            ]
            await asyncio.wait_for(asyncio.gather(*publishers), timeout=args.timeout)
            viewer_results = await asyncio.wait_for(asyncio.gather(*watchers), timeout=args.timeout)
        finally:
            await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)
            await asyncio.gather(*(
                client.delete(f"{args.base_url}/api/sessions/{case.session_id}")
                for case in cases
            ), return_exceptions=True)

    streams = []
    all_passed = True
    for case in cases:
        results = [item for item in viewer_results if item["session_id"] == case.session_id]
        valid = [item for item in results if item["valid"]]
        first_caption = [item["first_caption_seconds"] for item in valid]
        delivery = [item["delivery_ms"] for item in valid]
        event_ids = {item["event_id"] for item in valid}
        stream_passed = (
            len(valid) == args.viewers_per_stream
            and bool(first_caption)
            and max(first_caption) <= args.max_first_caption_seconds
            and len(event_ids) == 1
        )
        all_passed = all_passed and stream_passed
        representative = valid[0] if valid else {}
        streams.append({
            "session_id": case.session_id,
            "language_pair": f"{case.source}-{case.target}",
            "viewers": args.viewers_per_stream,
            "successful_viewers": len(valid),
            "first_caption_p50_seconds": round(statistics.median(first_caption), 3) if first_caption else None,
            "first_caption_max_seconds": round(max(first_caption), 3) if first_caption else None,
            "delivery_p95_ms": round(percentile(delivery, 0.95), 2) if delivery else None,
            "one_shared_event": len(event_ids) == 1,
            "original_preview": representative.get("original", "")[:180],
            "translation_preview": representative.get("translation", "")[:180],
            "passed": stream_passed,
            "errors": [item for item in results if item["error"]][:5],
        })

    return {
        "simultaneous_streams": len(cases),
        "viewers_per_stream": args.viewers_per_stream,
        "max_first_caption_seconds": args.max_first_caption_seconds,
        "streams": streams,
        "passed": all_passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8080")
    parser.add_argument("--english-sample", type=Path, required=True)
    parser.add_argument("--spanish-sample", type=Path, required=True)
    parser.add_argument("--viewers-per-stream", type=int, default=10)
    parser.add_argument("--audio-seconds", type=float, default=6.5)
    parser.add_argument("--max-first-caption-seconds", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
