from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from faster_whisper import WhisperModel


MODEL_NAME = os.getenv("ASR_MODEL", "large-v3-turbo")
WORKERS = int(os.getenv("ASR_WORKERS", "10"))
COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")

app = FastAPI(title="Vibeathon ASR")
model = WhisperModel(MODEL_NAME, device="cuda", compute_type=COMPUTE_TYPE, num_workers=WORKERS)
slots = asyncio.Semaphore(WORKERS)


def run_transcription(path: str, language: str, prompt: str, hotwords: str) -> dict:
    started = time.perf_counter()
    segments, info = model.transcribe(
        path,
        language=language or None,
        beam_size=5,
        best_of=5,
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
        initial_prompt=prompt or None,
        hotwords=hotwords or None,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "processing_seconds": round(time.perf_counter() - started, 3),
        "model": MODEL_NAME,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "workers": WORKERS}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form("en"),
    prompt: str = Form(""),
    hotwords: str = Form(""),
):
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    payload = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        path = handle.name
    try:
        async with slots:
            return await asyncio.to_thread(run_transcription, path, language, prompt, hotwords)
    finally:
        Path(path).unlink(missing_ok=True)
