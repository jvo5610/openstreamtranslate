#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import time
from pathlib import Path

import httpx
import websockets


def decode_pcm(path: Path, seconds: float) -> bytes:
    return subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-t", str(seconds), "-vn",
        "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
    ])


async def watch_caption(
    base_url: str,
    session_id: str,
    started_ref: list[float],
    ready: asyncio.Event,
    ready_counter: list[int],
    ready_lock: asyncio.Lock,
    total_viewers: int,
    source_language: str,
    target_language: str,
) -> dict:
    result = {
        "session_id": None,
        "event_id": None,
        "end_to_end_seconds": None,
        "fanout_delivery_ms": None,
        "model_seconds": None,
        "valid": False,
        "error": None,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            async with client.stream("GET", f"{base_url}/api/sessions/{session_id}/events") as response:
                response.raise_for_status()
                async with ready_lock:
                    ready_counter[0] += 1
                    if ready_counter[0] == total_viewers:
                        ready.set()
                event_id = None
                async for line in response.aiter_lines():
                    if line.startswith("id:"):
                        event_id = line[3:].strip()
                    elif line.startswith("data:"):
                        event = json.loads(line[5:].strip())
                        result.update({
                            "session_id": event.get("session_id"),
                            "event_id": event.get("event_id") or event_id,
                            "end_to_end_seconds": round(time.perf_counter() - started_ref[0], 3),
                            "fanout_delivery_ms": round(
                                max(0, time.time() - float(event.get("published_at", time.time()))) * 1000,
                                2,
                            ),
                            "model_seconds": event.get("latency", {}).get("total"),
                            "valid": (
                                event.get("session_id") == session_id
                                and event.get("source_language") == source_language
                                and event.get("target_language") == target_language
                                and bool(event.get("original", "").strip())
                                and bool(event.get("translation", "").strip())
                            ),
                        })
                        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


async def main_async(args: argparse.Namespace) -> dict:
    pcm = decode_pcm(args.sample, args.audio_seconds)
    session_ids = [f"acceptance-{index + 1}" for index in range(args.sessions)]
    total_viewers = args.sessions * args.viewers_per_session
    ready = asyncio.Event()
    ready_counter = [0]
    ready_lock = asyncio.Lock()
    started_ref = [time.perf_counter()]

    sockets = []
    try:
        for session_id in session_ids:
            socket = await websockets.connect(
                f"{args.ws_base}/api/sessions/{session_id}/input?source={args.source_language}&target={args.target_language}",
                max_size=2**22,
            )
            await socket.recv()
            sockets.append(socket)

        watchers = [
            asyncio.create_task(watch_caption(
                args.base_url,
                session_id,
                started_ref,
                ready,
                ready_counter,
                ready_lock,
                total_viewers,
                args.source_language,
                args.target_language,
            ))
            for session_id in session_ids
            for _ in range(args.viewers_per_session)
        ]
        await asyncio.wait_for(ready.wait(), timeout=10)
        started_ref[0] = time.perf_counter()

        async def publish(socket) -> None:
            bytes_per_quarter_second = 16000 * 2 // 4
            for offset in range(0, len(pcm), bytes_per_quarter_second):
                await socket.send(pcm[offset:offset + bytes_per_quarter_second])
                await asyncio.sleep(0.25)
            await socket.send(json.dumps({"type": "stop"}))
            while True:
                message = json.loads(await socket.recv())
                if message.get("type") == "stopped":
                    return

        await asyncio.gather(*(publish(socket) for socket in sockets))
        viewer_results = await asyncio.gather(*watchers)
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

    async with httpx.AsyncClient(timeout=5) as client:
        await asyncio.gather(*(
            client.delete(f"{args.base_url}/api/sessions/{session_id}")
            for session_id in session_ids
        ), return_exceptions=True)

    valid = [item for item in viewer_results if item["valid"]]
    latencies = [item["end_to_end_seconds"] for item in valid]
    delivery_times = [item["fanout_delivery_ms"] for item in valid]
    model_times = [item["model_seconds"] for item in valid if item["model_seconds"] is not None]

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]
    per_session_event_ids = {
        session_id: sorted({item["event_id"] for item in valid if item["session_id"] == session_id})
        for session_id in session_ids
    }
    passed = (
        len(valid) == total_viewers
        and bool(latencies)
        and max(latencies) <= 5
        and all(len(event_ids) == 1 for event_ids in per_session_event_ids.values())
    )
    return {
        "source_sessions": args.sessions,
        "language_pair": f"{args.source_language}-{args.target_language}",
        "viewers_per_session": args.viewers_per_session,
        "total_viewers": total_viewers,
        "successful_viewers": len(valid),
        "first_caption_p50_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "first_caption_max_seconds": round(max(latencies), 3) if latencies else None,
        "model_p50_seconds": round(statistics.median(model_times), 3) if model_times else None,
        "fanout_delivery_p50_ms": round(statistics.median(delivery_times), 2) if delivery_times else None,
        "fanout_delivery_p95_ms": round(percentile(delivery_times, 0.95), 2) if delivery_times else None,
        "fanout_delivery_max_ms": round(max(delivery_times), 2) if delivery_times else None,
        "one_shared_event_per_session": all(len(ids) == 1 for ids in per_session_event_ids.values()),
        "event_ids_by_session": per_session_event_ids,
        "passed": passed,
        "details": viewer_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8080")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--viewers-per-session", type=int, default=10)
    parser.add_argument("--audio-seconds", type=float, default=4.5)
    parser.add_argument("--source-language", choices=["en", "es"], default="en")
    parser.add_argument("--target-language", choices=["en", "es"], default="es")
    args = parser.parse_args()
    result = asyncio.run(main_async(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
