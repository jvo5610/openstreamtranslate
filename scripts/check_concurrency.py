#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from pathlib import Path

import websockets


def decode_pcm(path: Path, seconds: float) -> bytes:
    return subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-t", str(seconds), "-vn",
        "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
    ])


async def run_level(url: str, pcm: bytes, sessions: int) -> dict:
    start_event = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def run_session(index: int) -> dict:
        nonlocal ready
        result = {
            "session": index,
            "captions": 0,
            "first_caption_seconds": None,
            "final_seen": False,
            "original_nonempty": False,
            "translation_nonempty": False,
            "stopped": False,
            "error": None,
        }
        try:
            async with websockets.connect(url, max_size=2**22) as socket:
                async with ready_lock:
                    ready += 1
                    if ready == sessions:
                        start_event.set()
                await start_event.wait()
                started = time.perf_counter()

                async def send_audio() -> None:
                    bytes_per_quarter_second = 16000 * 2 // 4
                    for offset in range(0, len(pcm), bytes_per_quarter_second):
                        await socket.send(pcm[offset : offset + bytes_per_quarter_second])
                        await asyncio.sleep(0.25)
                    await socket.send(json.dumps({"type": "stop"}))

                sender = asyncio.create_task(send_audio())
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
                    if message.get("type") == "caption":
                        result["captions"] += 1
                        if result["first_caption_seconds"] is None:
                            result["first_caption_seconds"] = round(time.perf_counter() - started, 3)
                        result["final_seen"] = result["final_seen"] or bool(message.get("final"))
                        result["original_nonempty"] = result["original_nonempty"] or bool(message.get("original", "").strip())
                        result["translation_nonempty"] = result["translation_nonempty"] or bool(message.get("translation", "").strip())
                    elif message.get("type") == "stopped":
                        result["stopped"] = True
                        break
                await sender
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    wall_started = time.perf_counter()
    results = await asyncio.gather(*(run_session(index + 1) for index in range(sessions)))
    latencies = [item["first_caption_seconds"] for item in results if item["first_caption_seconds"] is not None]
    successful = [
        item for item in results
        if item["stopped"] and item["original_nonempty"] and item["translation_nonempty"] and not item["error"]
    ]
    return {
        "sessions": sessions,
        "successful_sessions": len(successful),
        "wall_seconds": round(time.perf_counter() - wall_started, 3),
        "first_caption_p50_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "first_caption_max_seconds": round(max(latencies), 3) if latencies else None,
        "passed": len(successful) == sessions and bool(latencies) and max(latencies) <= 5,
        "details": results,
    }


async def async_main(args: argparse.Namespace) -> dict:
    pcm = decode_pcm(args.sample, args.audio_seconds)
    levels = []
    for sessions in args.sessions:
        levels.append(await run_level(args.url, pcm, sessions))
    return {"url": args.url, "audio_seconds": args.audio_seconds, "levels": levels}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8080/api/live")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--sessions", type=int, nargs="+", default=[2, 5, 10])
    parser.add_argument("--audio-seconds", type=float, default=6.5)
    args = parser.parse_args()
    result = asyncio.run(async_main(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(level["passed"] for level in result["levels"]) else 1)


if __name__ == "__main__":
    main()
