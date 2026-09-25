#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import torch
import soundfile as sf
from transformers import pipeline


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load_started = time.perf_counter()
    recognizer = pipeline(
        "automatic-speech-recognition",
        model=args.model,
        device=0,
        dtype=torch.float16,
    )
    load_seconds = time.perf_counter() - load_started
    audio_seconds = duration_seconds(args.audio)
    audio, sample_rate = sf.read(args.audio, dtype="float32")
    runs = []
    for index in range(2):
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        result = recognizer({"raw": audio.copy(), "sampling_rate": sample_rate})
        elapsed = time.perf_counter() - started
        runs.append({
            "run": index + 1,
            "seconds": round(elapsed, 4),
            "realtime_factor": round(elapsed / audio_seconds, 5),
            "realtime_multiple": round(audio_seconds / elapsed, 2),
            "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            "text": result["text"].strip(),
        })

    payload = {
        "model": args.model,
        "audio_seconds": round(audio_seconds, 3),
        "load_seconds": round(load_seconds, 3),
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
