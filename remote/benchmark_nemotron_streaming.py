#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from threading import Thread

import soundfile as sf
import torch
from transformers import AutoModelForRNNT, AutoProcessor, TextIteratorStreamer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookahead", type=int, nargs="+", default=[3, 6, 13])
    args = parser.parse_args()

    model_id = "nvidia/nemotron-3.5-asr-streaming-0.6b"
    load_started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForRNNT.from_pretrained(model_id, device_map="auto", dtype=torch.float16)
    load_seconds = time.perf_counter() - load_started
    audio, sampling_rate = sf.read(args.audio, dtype="float32")
    audio_seconds = len(audio) / sampling_rate
    results = []

    for lookahead in args.lookahead:
        processor.set_num_lookahead_tokens(lookahead)
        for run in range(2):
            first = processor(
                audio[: processor.num_samples_first_audio_chunk],
                sampling_rate=sampling_rate,
                is_streaming=True,
                is_first_audio_chunk=True,
                language="en-US",
                return_tensors="pt",
            ).to(model.device, dtype=model.dtype)

            def features():
                yield first.input_features[:, : processor.num_mel_frames_first_audio_chunk, :]
                frame = processor.num_mel_frames_first_audio_chunk
                hop = processor.feature_extractor.hop_length
                n_fft = processor.feature_extractor.n_fft
                start = frame * hop - n_fft // 2
                while (end := start + processor.num_samples_per_audio_chunk) < audio.shape[0]:
                    inputs = processor(
                        audio[start:end],
                        sampling_rate=sampling_rate,
                        is_streaming=True,
                        is_first_audio_chunk=False,
                        language="en-US",
                        return_tensors="pt",
                    ).to(model.device, dtype=model.dtype)
                    yield inputs.input_features
                    frame += processor.num_mel_frames_per_audio_chunk
                    start = frame * hop - n_fft // 2

            streamer = TextIteratorStreamer(processor.tokenizer, skip_special_tokens=True)
            kwargs = {**first, "input_features": features(), "streamer": streamer}
            torch.cuda.reset_peak_memory_stats()
            started = time.perf_counter()
            worker = Thread(target=model.generate, kwargs=kwargs)
            worker.start()
            pieces = []
            first_text_seconds = None
            for piece in streamer:
                if piece and first_text_seconds is None:
                    first_text_seconds = time.perf_counter() - started
                pieces.append(piece)
            worker.join()
            elapsed = time.perf_counter() - started
            results.append({
                "lookahead_tokens": lookahead,
                "configured_latency_ms": processor.streaming_latency_ms,
                "run": run + 1,
                "compute_seconds": round(elapsed, 4),
                "first_text_seconds": round(first_text_seconds or elapsed, 4),
                "realtime_multiple": round(audio_seconds / elapsed, 2),
                "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                "text": "".join(pieces).strip(),
            })

    payload = {
        "model": model_id,
        "audio_seconds": round(audio_seconds, 3),
        "load_seconds": round(load_seconds, 3),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
