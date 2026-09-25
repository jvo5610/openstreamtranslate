#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from websockets.asyncio.client import connect


async def bridge_once(input_url: str, caption_ws: str, chunk_bytes: int) -> None:
    print(f"Conectando {input_url} -> {caption_ws}", flush=True)
    async with connect(
        caption_ws,
        proxy=None,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        max_size=None,
    ) as websocket:
        ready = json.loads(await websocket.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(f"Respuesta WebSocket inesperada: {ready}")

        realtime_input = ["-re"] if Path(input_url).expanduser().is_file() else []
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            *realtime_input,
            "-i",
            input_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
        )

        try:
            if process.stdout is None:
                raise RuntimeError("FFmpeg no expuso audio por stdout")
            while chunk := await process.stdout.read(chunk_bytes):
                await websocket.send(chunk)
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait()
            try:
                await websocket.send(json.dumps({"type": "stop"}))
            except Exception:
                pass

        if process.returncode:
            raise RuntimeError(f"FFmpeg terminó con código {process.returncode}")


async def run(args: argparse.Namespace) -> None:
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    while not stopping.is_set():
        try:
            await bridge_once(args.input_url, args.caption_ws, args.chunk_bytes)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Bridge desconectado: {exc}; reintento en {args.retry_seconds:g} s", flush=True)

        try:
            await asyncio.wait_for(stopping.wait(), timeout=args.retry_seconds)
        except TimeoutError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae audio de RTMP/SRT/HLS y lo envía al WebSocket de captions."
    )
    parser.add_argument("--input-url", required=True, help="URL RTMP, SRT o HLS que leerá FFmpeg")
    parser.add_argument("--caption-ws", required=True, help="WebSocket /api/sessions/{id}/input")
    parser.add_argument("--chunk-bytes", type=int, default=8192)
    parser.add_argument("--retry-seconds", type=float, default=2)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
