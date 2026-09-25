#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import torch
from nemo.collections.speechlm2.models import SALM


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, nargs="+", required=True)
    parser.add_argument("--latency-audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model_id = "nvidia/canary-qwen-2.5b"
    load_started = time.perf_counter()
    model = SALM.from_pretrained(model_id).cuda().eval()
    load_seconds = time.perf_counter() - load_started
    audio_seconds = sum(duration_seconds(path) for path in args.audio)
    prompt = "Transcribe the following:"
    runs = []

    for run in range(2):
        texts = []
        segment_seconds = []
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        for path in args.audio:
            segment_started = time.perf_counter()
            answer_ids = model.generate(
                prompts=[[{
                    "role": "user",
                    "content": f"{prompt} {model.audio_locator_tag}",
                    "audio": [str(path)],
                }]],
                max_new_tokens=512,
            )
            segment_seconds.append(round(time.perf_counter() - segment_started, 4))
            texts.append(model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip())
        elapsed = time.perf_counter() - started
        runs.append({
            "run": run + 1,
            "seconds": round(elapsed, 4),
            "realtime_factor": round(elapsed / audio_seconds, 5),
            "realtime_multiple": round(audio_seconds / elapsed, 2),
            "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            "segment_seconds": segment_seconds,
            "text": " ".join(texts),
        })

    short_runs = []
    if args.latency_audio:
        for _ in range(5):
            started = time.perf_counter()
            answer_ids = model.generate(
                prompts=[[{
                    "role": "user",
                    "content": f"{prompt} {model.audio_locator_tag}",
                    "audio": [str(args.latency_audio)],
                }]],
                max_new_tokens=128,
            )
            short_runs.append({
                "seconds": round(time.perf_counter() - started, 4),
                "text": model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip(),
            })

    payload = {
        "model": model_id,
        "audio_seconds": round(audio_seconds, 3),
        "load_seconds": round(load_seconds, 3),
        "runs": runs,
        "short_chunk_seconds": round(duration_seconds(args.latency_audio), 3) if args.latency_audio else None,
        "short_runs": short_runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
