from __future__ import annotations

import io
import os
import asyncio
import time
import wave

import httpx


ASR_URL = os.getenv("ASR_URL", "http://host.docker.internal:18081").rstrip("/")
TRANSLATION_URL = os.getenv("TRANSLATION_URL", "http://host.docker.internal:18080").rstrip("/")
SOURCE_LANGUAGE = os.getenv("SOURCE_LANGUAGE", "en")
TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "es")
LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}


def pcm16_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


async def normalize_audio(audio: bytes) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await process.communicate(audio)
    if process.returncode != 0:
        raise ValueError(f"Unsupported audio input: {error.decode(errors='replace')[-500:]}")
    return output


def translation_prompt(
    text: str,
    source_language: str,
    target_language: str,
    glossary: list[dict[str, str]] | None = None,
) -> str:
    source = LANGUAGE_NAMES.get(source_language, source_language)
    target = LANGUAGE_NAMES.get(target_language, target_language)
    glossary_rules = ""
    if glossary:
        rules = "\n".join(
            f"- {entry['source']} => {entry.get('target') or entry['source']}"
            for entry in glossary
        )
        glossary_rules = (
            "\nUse these glossary forms exactly when the matching source term is present. "
            "Never insert a glossary term that was not spoken:\n"
            f"{rules}\n"
        )
    return (
        "<start_of_turn>user\n"
        f"Translate this live conference subtitle from {source} ({source_language}) to {target} ({target_language}). "
        "Preserve meaning, technical terms, sentence fragments, and ellipses, but keep the subtitle concise: "
        "do not explain, paraphrase, or expand acronyms, job titles, or names. Prefer wording no longer than "
        f"the source when natural in {target}. Output only the {target} subtitle."
        f"{glossary_rules}\n"
        f"{text.strip()}<end_of_turn>\n<start_of_turn>model\n"
    )


class CaptionPipeline:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5))

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> dict:
        result: dict[str, dict] = {}
        for name, url in (("asr", f"{ASR_URL}/health"), ("translation", f"{TRANSLATION_URL}/health")):
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                result[name] = {"ok": True, **response.json()}
            except Exception as exc:
                result[name] = {"ok": False, "error": str(exc)}
        result["ok"] = all(service["ok"] for service in result.values())
        return result

    async def transcribe(
        self,
        audio: bytes,
        filename: str,
        prompt: str = "",
        source_language: str = SOURCE_LANGUAGE,
        hotwords: str = "",
    ) -> dict:
        started = time.perf_counter()
        response = await self.client.post(
            f"{ASR_URL}/transcribe",
            files={"file": (filename, audio, "application/octet-stream")},
            data={"language": source_language, "prompt": prompt, "hotwords": hotwords},
        )
        response.raise_for_status()
        result = response.json()
        result["roundtrip_seconds"] = round(time.perf_counter() - started, 3)
        return result

    async def translate(
        self,
        text: str,
        source_language: str = SOURCE_LANGUAGE,
        target_language: str = TARGET_LANGUAGE,
        glossary: list[dict[str, str]] | None = None,
    ) -> dict:
        if not text.strip():
            return {"text": "", "roundtrip_seconds": 0}
        started = time.perf_counter()
        response = await self.client.post(
            f"{TRANSLATION_URL}/completion",
            json={
                "prompt": translation_prompt(text, source_language, target_language, glossary),
                "n_predict": 512,
                "temperature": 0,
                "stop": ["<end_of_turn>"],
                "cache_prompt": True,
            },
        )
        response.raise_for_status()
        result = response.json()
        return {
            "text": result.get("content", "").strip(),
            "roundtrip_seconds": round(time.perf_counter() - started, 3),
            "tokens": result.get("tokens_predicted"),
        }

    async def process(
        self,
        audio: bytes,
        filename: str,
        prompt: str = "",
        source_language: str = SOURCE_LANGUAGE,
        target_language: str = TARGET_LANGUAGE,
        glossary: list[dict[str, str]] | None = None,
    ) -> dict:
        hotwords = ", ".join(entry["source"] for entry in glossary or [])
        asr = await self.transcribe(audio, filename, prompt, source_language, hotwords)
        translation = await self.translate(asr.get("text", ""), source_language, target_language, glossary)
        return {
            "original": asr.get("text", ""),
            "translation": translation["text"],
            "language": asr.get("language", source_language),
            "source_language": source_language,
            "target_language": target_language,
            "latency": {
                "asr": asr["roundtrip_seconds"],
                "translation": translation["roundtrip_seconds"],
                "total": round(asr["roundtrip_seconds"] + translation["roundtrip_seconds"], 3),
            },
        }
